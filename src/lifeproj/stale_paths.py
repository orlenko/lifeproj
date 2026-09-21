"""Find and fix absolute paths a teka carried over from another machine.

A teka pulled onto a new machine (different username, different teka home)
still spells the old one's paths inside its scripts and settings: a hook's
``/Users/old/...``, a script's ``~/personal/<teka>``. cmirror restores bytes, not
meaning, so ``lifeproj restore`` reports them and, given the old teka home,
rewrites the ones in code and config.

Prose is reported, never rewritten: filed mail, notes and timelines record what
was true when they were written.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

# Rewritten only in these: code and config, where a stale path breaks something.
CODE_SUFFIXES = {".py", ".sh", ".zsh", ".bash", ".json", ".toml", ".plist",
                 ".yaml", ".yml", ".env", ".cfg", ".ini"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "tmp"}
MAX_BYTES = 2_000_000

_HOME_RE = re.compile(r"/Users/([A-Za-z0-9._-]+)/")


def _text_files(wd: Path):
    for dirpath, dirnames, filenames in os.walk(wd):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                if p.is_symlink() or p.stat().st_size > MAX_BYTES:
                    continue
                text = p.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            yield p, text


def _is_code(path: Path) -> bool:
    return path.suffix in CODE_SUFFIXES or path.name == ".env"


def _rewrites(old_home: Optional[Path], new_home: Path, home: Path) -> list:
    """Ordered (old, new) string pairs, most specific first."""
    if old_home is None:
        return []
    pairs = [(str(old_home).rstrip("/") + "/", str(new_home) + "/")]
    m = _HOME_RE.match(str(old_home) + "/")
    if m:
        old_user_home = f"/Users/{m.group(1)}"
        rel = str(old_home)[len(old_user_home):].strip("/")
        new_rel = os.path.relpath(new_home, home)
        if rel and not new_rel.startswith(".."):
            pairs.append((f"~/{rel}/", f"~/{new_rel}/"))
        pairs.append((old_user_home + "/", str(home) + "/"))
    return pairs


def scan(wd: Path, *, old_home: Optional[Path] = None, fix: bool = False,
         home: Optional[Path] = None) -> dict:
    """Report files under ``wd`` that name another user's home (or ``old_home``).

    With ``fix`` and ``old_home``, code and config files are rewritten:
    ``<old_home>/`` → ``<wd's parent>/``, its ``~/`` form likewise, then the
    old user's ``/Users/<old>/`` → this home. Returns
    ``{"fixed": [rel, ...], "remaining": [(rel, count), ...]}``.
    """
    home = home or Path.home()
    me = home.name
    pairs = _rewrites(old_home, wd.parent, home)
    fixed, remaining = [], []
    for path, text in _text_files(wd):
        rel = str(path.relative_to(wd))
        if fix and pairs and _is_code(path):
            new = text
            for old, repl in pairs:
                new = new.replace(old, repl)
            if new != text:
                path.write_text(new)
                fixed.append(rel)
                text = new
        count = sum(1 for m in _HOME_RE.finditer(text) if m.group(1) != me)
        if old_home is not None:
            for old, _ in pairs:
                if old.startswith("~/"):
                    count += text.count(old)
        if count:
            remaining.append((rel, count))
    return {"fixed": fixed, "remaining": remaining}
