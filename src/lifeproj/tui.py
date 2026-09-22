"""Terminal primitives for the interactive starter.

`lifeproj` with no arguments on a terminal opens a menu (see `menu.py`). It is
drawn with plain ANSI escapes on the alternate screen — no curses, no widget
library: lifeproj stays a thin orchestrator with one runtime dependency, and a
starter menu is not a reason to grow another.

Everything here is mechanical — keys in, cells out. What the menu *means* lives
in `menu.py`.
"""

from __future__ import annotations

import os
import select
import shutil
import signal
import sys
import unicodedata
from dataclasses import dataclass
from typing import Optional

try:                                    # POSIX only; absent on Windows
    import termios
    import tty
except ImportError:                     # pragma: no cover - not our platform
    termios = None
    tty = None

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
REVERSE = "\x1b[7m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
CYAN = "\x1b[36m"

_ALT_ON = "\x1b[?1049h\x1b[?25l"
_ALT_OFF = "\x1b[?25h\x1b[?1049l"

# --- keys ---

KEY_CHAR = 0
KEY_UP = 1
KEY_DOWN = 2
KEY_LEFT = 3
KEY_RIGHT = 4
KEY_HOME = 5
KEY_END = 6
KEY_ENTER = 7
KEY_ESC = 8
KEY_BACKSPACE = 9
KEY_TAB = 10
KEY_CLEAR = 11                          # ctrl-u
KEY_QUIT = 12                           # ctrl-c / ctrl-d


@dataclass(frozen=True)
class Key:
    code: int = KEY_CHAR
    char: str = ""


_FINAL = {"A": KEY_UP, "B": KEY_DOWN, "C": KEY_RIGHT, "D": KEY_LEFT,
          "H": KEY_HOME, "F": KEY_END}
_TILDE = {"1": KEY_HOME, "7": KEY_HOME, "4": KEY_END, "8": KEY_END}


def parse_keys(data: bytes) -> list:
    """Split one read from the terminal into key presses.

    Unknown escape sequences are dropped rather than leaked as text; an
    incomplete one at the end of the buffer is dropped too (the next read
    carries it whole in practice).
    """
    out, i, n = [], 0, len(data)
    while i < n:
        c = data[i]
        if c == 0x1b and i + 1 < n and data[i + 1] in (0x5b, 0x4f):   # CSI / SS3
            j = i + 2
            while j < n and not 0x40 <= data[j] <= 0x7e:
                j += 1
            if j >= n:
                break
            final = chr(data[j])
            code = (_TILDE.get(data[i + 2:j].decode("ascii", "replace"))
                    if final == "~" else _FINAL.get(final))
            if code:
                out.append(Key(code))
            i = j + 1
        elif c == 0x1b:
            out.append(Key(KEY_ESC))
            i += 1
        elif c in (0x0d, 0x0a):
            out.append(Key(KEY_ENTER))
            i += 1
        elif c in (0x7f, 0x08):
            out.append(Key(KEY_BACKSPACE))
            i += 1
        elif c in (0x03, 0x04):
            out.append(Key(KEY_QUIT))
            i += 1
        elif c == 0x09:
            out.append(Key(KEY_TAB))
            i += 1
        elif c == 0x15:
            out.append(Key(KEY_CLEAR))
            i += 1
        elif c < 0x20:
            i += 1                       # some other control byte: ignore
        else:
            j = i + 1
            while j < n and 0x80 <= data[j] < 0xc0:   # utf-8 continuation
                j += 1
            out.append(Key(KEY_CHAR, data[i:j].decode("utf-8", "replace")))
            i = j
    return out


# --- text metrics ---

def cells(text: str) -> int:
    """Display width of ``text`` in terminal cells."""
    n = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        n += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return n


def truncate(text: str, width: int) -> str:
    """Cut ``text`` to at most ``width`` cells, ending in … when it had to cut."""
    if cells(text) <= width:
        return text
    if width <= 0:
        return ""
    out, used = "", 0
    for ch in text:
        c = cells(ch)
        if used + c > width - 1:
            break
        out += ch
        used += c
    return out + "…"


def pad(text: str, width: int) -> str:
    """Truncate or right-pad ``text`` to exactly ``width`` cells."""
    text = truncate(text, width)
    return text + " " * (width - cells(text))


def wrap(text: str, width: int) -> list:
    """Break ``text`` into lines of at most ``width`` cells."""
    width = max(width, 10)
    lines = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for word in words:
            if cur and cells(cur) + 1 + cells(word) > width:
                lines.append(cur)
                cur = ""
            cur = f"{cur} {word}" if cur else word
            while cells(cur) > width:    # a long path: hard-split it
                lines.append(truncate(cur, width))
                cur = ""
        if cur:
            lines.append(cur)
    return lines


# --- drawing ---

@dataclass
class Seg:
    """One run of text on a line, drawn with one style."""
    text: str
    style: str = ""


def clip(line: list, width: int) -> list:
    """Cut a line of segments to ``width`` cells, dropping what runs past it."""
    out, room = [], width
    for seg in line:
        if room <= 0:
            break
        text = seg.text if cells(seg.text) <= room else truncate(seg.text, room)
        room -= cells(text)
        out.append(Seg(text, seg.style))
    return out


@dataclass
class Done:
    """What `run` returns: the argv the menu composed, or None to just quit."""
    args: Optional[list] = None


class Terminal:
    """Raw mode + the alternate screen, restored on the way out."""

    def __init__(self, stdin=None, stdout=None):
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self._saved = None
        self._prev_winch = None
        self.resized = True

    def __enter__(self):
        fd = self.stdin.fileno()
        self._saved = termios.tcgetattr(fd)
        tty.setraw(fd)
        self.stdout.write(_ALT_ON)
        self.stdout.flush()
        try:
            self._prev_winch = signal.signal(signal.SIGWINCH, self._on_winch)
        except (ValueError, AttributeError):   # not the main thread, or no SIGWINCH
            self._prev_winch = None
        return self

    def __exit__(self, *exc):
        if self._prev_winch is not None:
            signal.signal(signal.SIGWINCH, self._prev_winch)
        self.stdout.write(_ALT_OFF)
        self.stdout.flush()
        termios.tcsetattr(self.stdin.fileno(), termios.TCSADRAIN, self._saved)
        return False

    def _on_winch(self, *_):
        self.resized = True

    def size(self):
        w, h = shutil.get_terminal_size((80, 24))
        return max(w, 20), max(h, 8)

    def read(self, timeout: float):
        """One read of whatever is typed, or None when nothing arrived in time."""
        try:
            ready, _, _ = select.select([self.stdin], [], [], timeout)
        except (OSError, ValueError):
            return b""
        if not ready:
            return None
        return os.read(self.stdin.fileno(), 1024)

    def draw(self, lines: list, footer: list, w: int, h: int) -> None:
        """Paint one frame: ``lines`` from the top, ``footer`` on the last row."""
        body = list(lines[:max(h - 1, 0)])
        body += [[]] * (h - 1 - len(body))
        body.append(footer)
        out = ["\x1b[H"]
        for i, line in enumerate(body):
            for seg in clip(line, w):
                out.append(f"{seg.style}{seg.text}{RESET}" if seg.style else seg.text)
            out.append("\x1b[K")
            if i < len(body) - 1:
                out.append("\r\n")
        out.append("\x1b[J")
        self.stdout.write("".join(out))
        self.stdout.flush()


def available(stdin=None, stdout=None) -> bool:
    """True when this process can open the menu at all."""
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    if termios is None:
        return False
    try:
        return bool(stdin.isatty() and stdout.isatty() and stdin.fileno() >= 0)
    except (AttributeError, OSError, ValueError):
        return False


def run(app, term=None):
    """Draw ``app`` until one of its keys finishes it; return that `Done`.

    ``app`` supplies ``render(w, h) -> [[Seg]]``, ``footer() -> [Seg]``,
    ``handle(Key) -> Done | None`` and ``tick() -> bool`` (True when background
    work changed what is on screen).
    """
    term = term or Terminal()
    with term:
        dirty = True
        while True:
            if dirty or term.resized:
                w, h = term.size()
                term.resized = False
                term.draw(app.render(w, h), app.footer(), w, h)
                dirty = False
            data = term.read(0.2)
            if data is None:
                dirty = app.tick()      # background detail arrived, or nothing did
                continue
            if data == b"":
                return Done()
            for key in parse_keys(data):
                done = app.handle(key)
                if done is not None:
                    return done
            dirty = True
