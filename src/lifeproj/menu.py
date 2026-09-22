"""The interactive starter — what `lifeproj` with no arguments opens.

It is a front door, not a second control plane. Every screen composes one
ordinary `lifeproj` command, shows it as it changes, and on Enter runs exactly
that: the menu can start nothing the command line cannot, so the CLI stays the
single surface and the menu stays a way to *discover* it. That is also why the
module rows carry each module's own one-line summary — `--module` is otherwise
a name you have to already know.

The shape is borrowed from aiq's start menu: rows of choices, a hint for the
focused one, the composed command at the bottom, and the last choice remembered
so the next run is one Enter.
"""

from __future__ import annotations

import json
import queue
import shlex
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from lifeproj import __version__, overview, registry, tui
from lifeproj.modules import MODULES, OVERLAYS
from lifeproj.tui import BOLD, CYAN, DIM, GREEN, REVERSE, YELLOW, Done, Key, Seg

STATE_PATH = Path("~/.local/share/lifeproj/menu.json").expanduser()

# Every domain that ships an overlay, plus the two that deliberately do not —
# so an overlay added to modules.OVERLAYS is offered here without a second edit.
DOMAINS = list(dict.fromkeys(["general", *OVERLAYS, "tax"]))
LIFECYCLES = ["ongoing", "finite"]
INTAKE = ["email", "docs", "github"]
ARTIFACTS = ["timeline", "ledger", "chapters", "entities"]

# Each chip is one module; the hint line is the module's own summary, so the
# menu documents what `--module` accepts without a second list to keep in sync.
CHIP_MODULE = {"email": "email-intake", "docs": "docs-intake", "github": "github-source",
               "timeline": "timeline", "ledger": "ledger", "chapters": "chapters",
               "entities": "entities"}

OVERLAY_HINT = {
    "legal": "Adds the legal overlay: evidence stays immutable, transcription is"
             " verbatim, strategy defers to counsel.",
    "tenancy": "Adds the tenancy overlay: cite the governing statute for every notice"
               " period, rent-increase limit and deposit rule.",
    "condo": "Adds the condo/strata overlay: cite the statute, regulation and"
             " registered bylaw for every threshold, vote and fee.",
    "product": "Adds the product overlay: live in the app, log friction as catalog"
               " items, draft issues for its tracker.",
}


def domain_hint(domain: str) -> str:
    """What picking this domain does — read off the overlays that actually ship."""
    if domain in OVERLAYS:
        return OVERLAY_HINT.get(domain, f"Adds the {domain} overlay to the manual.")
    if domain == "general":
        return "No domain overlay — the spine and whatever modules you switch on."
    return (f"No {domain} overlay ships yet — you get the spine plus the modules you"
            " switch on.")


@dataclass
class Choice:
    """What the New screen composes — and, in part, what it remembers."""
    name: str = ""
    domain: str = "general"
    lifecycle: str = "ongoing"
    summary: str = ""
    intake: list = field(default_factory=list)
    artifact: list = field(default_factory=list)
    path: str = ""
    imap_folder: str = ""
    chapter_noun: str = "chapter"
    register: bool = True
    dry_run: bool = False


# Remembered between runs: the shape of teka you tend to make. Never the
# name, summary, path or IMAP label — those belong to one teka — and never
# dry_run, which would silently turn the next real creation into a rehearsal.
REMEMBERED = ("domain", "lifecycle", "intake", "artifact", "chapter_noun", "register")


def load_choice(path: Path = STATE_PATH) -> Choice:
    c = Choice()
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        return c
    for key in REMEMBERED:
        if key in saved and isinstance(saved[key], type(getattr(c, key))):
            setattr(c, key, saved[key])
    c.domain = c.domain if c.domain in DOMAINS else "general"
    c.lifecycle = c.lifecycle if c.lifecycle in LIFECYCLES else "ongoing"
    c.intake = [v for v in INTAKE if v in c.intake]
    c.artifact = [v for v in ARTIFACTS if v in c.artifact]
    return c


def save_choice(c: Choice, path: Path = STATE_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in asdict(c).items() if k in REMEMBERED}
        path.write_text(json.dumps(data, indent=2) + "\n")
    except OSError:
        pass                     # remembering is a convenience, never a failure


# --- what the menu knows about this machine ---

@dataclass
class Teka:
    name: str
    working_dir: Path
    encrypted_dir: Path
    imap_folder: str = ""
    archived: bool = False
    exists: Optional[bool] = None      # None: not looked at disk yet
    intake: Optional[int] = None
    backup: Optional[str] = None


@dataclass
class Env:
    tekas: list = field(default_factory=list)
    root: Optional[Path] = None        # encrypted_root (`lifeproj root`)
    home: Optional[Path] = None        # teka_home (`lifeproj home`)
    loaded: bool = False               # disk detail filled in yet?
    config: Optional[Path] = None

    def homeless(self) -> list:
        """Active tekas the registry knows but this machine has no copy of."""
        return [t for t in self.tekas if not t.archived and t.exists is False]

    def teka(self, name: str) -> Optional[Teka]:
        for t in self.tekas:
            if t.name == name:
                return t
        return None


def environment(config: Optional[Path] = None) -> Env:
    """The registry alone — names and paths, no disk walk. Cheap enough to
    open the menu on; `enrich` fills in the rest from a background thread."""
    try:
        doc = registry.load(config)
    except OSError:
        return Env(config=config)
    tekas = []
    for archived, section in ((False, registry.projects(doc)), (True, registry.archived(doc))):
        for name, table in section.items():
            get = table.get if hasattr(table, "get") else (lambda k, d=None: d)
            tekas.append(Teka(
                name=name,
                working_dir=Path(str(get("working_dir", ""))).expanduser(),
                encrypted_dir=Path(str(get("encrypted_dir", ""))).expanduser(),
                imap_folder=str(get("imap_folder", "") or ""),
                archived=archived,
            ))
    return Env(tekas=tekas, root=registry.encrypted_root(doc),
               home=registry.teka_home(doc), config=config)


def enrich(env: Env) -> Env:
    """Intake counts and backup ages — a walk of every teka's intake/, which is
    why it runs off the drawing thread."""
    try:
        data = overview.collect(env.config)
    except OSError:
        env.loaded = True
        return env
    for row in data["active"]:
        t = env.teka(row["name"])
        if t:
            t.exists, t.intake, t.backup = row["exists"], row["intake"], row["backup"]
    for t in env.tekas:
        if t.archived:
            t.exists = t.working_dir.is_dir()
    env.loaded = True
    return env


# --- the commands the menu composes ---

def new_args(c: Choice) -> list:
    args = ["new", c.name]
    if c.path:
        args += ["--path", c.path]
    if c.domain != "general":
        args += ["--domain", c.domain]
    if c.lifecycle != "ongoing":
        args += ["--lifecycle", c.lifecycle]
    if c.summary:
        args += ["--summary", c.summary]
    if c.intake:
        args += ["--intake", ",".join(v for v in INTAKE if v in c.intake)]
    if c.artifact:
        args += ["--artifact", ",".join(v for v in ARTIFACTS if v in c.artifact)]
    if c.imap_folder and "email" in c.intake:
        args += ["--imap-folder", c.imap_folder]
    if c.chapter_noun and c.chapter_noun != "chapter" and "chapters" in c.artifact:
        args += ["--chapter-noun", c.chapter_noun]
    if not c.register:
        args.append("--no-register")
    if c.dry_run:
        args.append("--dry-run")
    return args


def teka_args(action: str, t: Teka) -> list:
    if action == "publish":
        return ["publish", "--path", str(t.working_dir)]
    if action == "drain":
        return ["drain", "--path", str(t.working_dir)]
    if action == "equip":
        return ["equip", t.name]
    if action == "archive":
        return ["archive", t.name]
    if action == "restore":
        return ["restore", t.name]
    return []


def valid_name(name: str) -> bool:
    """The rule `lifeproj new` enforces: a plain folder name, not a path.

    It is a registry key and the last component under the teka home, so
    anything path-like would escape the home when joined.
    """
    return bool(name) and name not in (".", "..") and "/" not in name \
        and not Path(name).is_absolute()


def preview(args: list) -> str:
    return "lifeproj " + " ".join(shlex.quote(a) for a in args)


def home_rel(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


# --- rows ---

@dataclass
class Row:
    key: str
    label: str
    kind: str = "select"          # select | chips | text | action
    opts: list = field(default_factory=list)      # [(value, label)]
    cur: str = ""                 # select: the value; text: the text
    on: list = field(default_factory=list)        # chips: the values switched on
    desc: str = ""                # action rows
    off: str = ""                 # why the row does not apply; empty when it does
    empty: str = ""               # text rows: what to show when unset


class Menu:
    """The screens, their keys, and the command each one stands for."""

    def __init__(self, env: Env, choice: Optional[Choice] = None):
        self.env = env
        self.c = choice if choice is not None else Choice()
        self.screen = "home"
        self.focus = {"home": "new", "new": "name", "teka": "publish"}
        self.teka_name = ""
        self.expanded = False
        self.editing = ""             # key of the row being typed into
        self.buffer = ""
        self.chip = {"intake": 0, "artifact": 0}
        self.inbox = queue.Queue(maxsize=1)
        self.w, self.h = 80, 24
        self.note = ""                # one-shot line under the rows

    # --- rows per screen ---

    def rows(self) -> list:
        if self.screen == "new":
            return self._new_rows()
        if self.screen == "teka":
            return self._teka_rows()
        return self._home_rows()

    def _home_rows(self) -> list:
        rows = [
            Row("new", "New teka", "action", desc="scaffold one from the spine + modules"),
            Row("overview", "Overview", "action", desc="intake, backup age and mail label, per teka"),
            Row("brief", "Brief", "action", desc="one merged list of what needs you today"),
            Row("equip", "Equip all", "action", desc="re-sync the spine skills into every teka"),
            Row("root", "Backup root", "action",
                desc=home_rel(self.env.root) if self.env.root else "not set yet"),
            Row("home", "Teka home", "action",
                desc=home_rel(self.env.home) if self.env.home else "not set yet (~/personal)"),
        ]
        missing = self.env.homeless()
        if missing:
            rows.append(Row("restore_all", "Restore all", "action",
                            desc=f"{len(missing)} registered teka"
                                 f"{'' if len(missing) == 1 else 's'} with no local copy here"))
        for t in self.env.tekas:
            rows.append(Row(f"teka:{t.name}", t.name, "action", desc=self._teka_line(t)))
        return rows

    def _teka_line(self, t: Teka) -> str:
        if t.archived:
            return "archived"
        if not self.env.loaded:
            return "…"
        if t.exists is False:
            return "no local copy"
        bits = [f"intake {t.intake}" if t.intake else "intake clear",
                f"backup {t.backup}" if t.backup else "never backed up"]
        if t.imap_folder:
            bits.append(t.imap_folder)
        return " · ".join(bits)

    def _teka_rows(self) -> list:
        t = self.env.teka(self.teka_name)
        if t is None:
            return [Row("back", "Back", "action", desc="this teka is no longer registered")]
        gone = "" if t.exists is not False else "no local copy — restore it first"
        rows = [
            Row("publish", "Publish", "action", off=gone,
                desc="project this teka's open items into the Osavul agenda spool"),
            Row("drain", "Drain", "action", off=gone,
                desc="apply Osavul's completion signals back into the catalog"),
            Row("equip", "Equip", "action", off=gone,
                desc="re-sync the spine skills and instruction files"),
        ]
        # Restore is what an absent teka needs, archived or not — it creates the
        # folder, pulls from Drive and refreshes the spine. Listing it before
        # the rest means an absent teka opens on the one thing worth doing.
        if t.archived or t.exists is False:
            rows.insert(0, Row("restore", "Restore", "action",
                               desc="pull the working copy from Drive into a usable state"
                                    + (" and revive it" if t.archived else "")))
        if not t.archived:
            rows.append(Row("archive", "Archive", "action",
                            desc="final backup, verify, then retire it from the sync cycle"))
        rows.append(Row("back", "Back", "action", desc="the teka list"))
        return rows

    def _new_rows(self) -> list:
        c = self.c
        rows = [
            Row("name", "Name", "text", cur=c.name, empty="(required)"),
            Row("domain", "Domain", opts=[(d, d) for d in DOMAINS], cur=c.domain),
            Row("lifecycle", "Lifecycle", opts=[(l, l) for l in LIFECYCLES], cur=c.lifecycle),
            Row("summary", "Summary", "text", cur=c.summary, empty="(one line, optional)"),
            Row("intake", "Intake", "chips", opts=[(v, v) for v in INTAKE], on=c.intake),
            Row("artifact", "Artifacts", "chips", opts=[(v, v) for v in ARTIFACTS], on=c.artifact),
        ]
        if not self.expanded:
            return rows + [Row("more", "More", "action", desc=self._more_summary())]
        more = [
            Row("imap_folder", "IMAP folder", "text", cur=c.imap_folder, empty="(set it later)",
                off="" if "email" in c.intake else "email intake is off"),
            Row("chapter_noun", "Chapter noun", "text", cur=c.chapter_noun,
                off="" if "chapters" in c.artifact else "the chapters module is off"),
            Row("path", "Working dir", "text", cur=c.path, empty=self._default_path()),
            Row("register", "Register", opts=[("yes", "yes"), ("no", "no")],
                cur="yes" if c.register else "no"),
            Row("dry_run", "Dry run", opts=[("no", "no"), ("yes", "yes")],
                cur="yes" if c.dry_run else "no"),
        ]
        return rows + more

    def _default_path(self) -> str:
        """Where `lifeproj new` would put it: <teka home>/<name>, else ~/personal."""
        home = home_rel(self.env.home) if self.env.home else "~/personal"
        return f"{home}/{self.c.name}" if self.c.name else f"{home}/<name>"

    def _more_summary(self) -> str:
        c, on = self.c, []
        if c.imap_folder and "email" in c.intake:
            on.append(c.imap_folder)
        if c.chapter_noun != "chapter" and "chapters" in c.artifact:
            on.append(c.chapter_noun + "s")
        if c.path:
            on.append(c.path)
        if not c.register:
            on.append("no registry entry")
        if c.dry_run:
            on.append("dry run")
        return " · ".join(on) if on else "IMAP folder, chapter noun, working dir, registry, dry run"

    # --- hints ---

    def hint(self, row: Optional[Row]) -> str:
        if row is None:
            return ""
        if row.off:
            return ""
        if self.screen == "home":
            return self._home_hint(row)
        if self.screen == "teka":
            t = self.env.teka(self.teka_name)
            if row.key == "restore" and t is not None and not t.archived:
                return ("Registered, but nothing is on this machine. Restore creates the"
                        " folder, pulls it from Drive and refreshes the spine skills.")
            return row.desc[0].upper() + row.desc[1:] + "."
        return self._new_hint(row)

    def _home_hint(self, row: Row) -> str:
        if row.key.startswith("teka:"):
            t = self.env.teka(row.key[5:])
            if t is None:
                return ""
            where = home_rel(t.working_dir)
            if t.archived:
                return f"Archived — the ciphertext is still in {home_rel(t.encrypted_dir)}. Enter offers to restore it."
            if t.exists is False:
                return f"Registered at {where}, but nothing is there. Enter offers what can still be run."
            return f"{where}. Enter opens what you can run on it."
        return {
            "new": "Name it, pick the modules, and Enter stamps the teka: spine,"
                   " module folders, skills, and a cmirror entry so it gets backed up.",
            "overview": "Read-only: what each teka has waiting in intake/ and how old"
                        " its last encrypted backup is.",
            "brief": "Reads the published agenda slices — what is open and due across"
                     " every teka, merged into one list.",
            "equip": "Idempotent: copies the current spine skills into every registered"
                     " teka without overwriting anything you customised.",
            "home": ("Tekas live under " + home_rel(self.env.home) + "; a new one lands"
                     " there. Enter reports each teka's working_dir against it."
                     if self.env.home else
                     "No teka home set — new tekas go under ~/personal. Set one once:"
                     " lifeproj home <path>."),
            "restore_all": ("Creates each missing folder, pulls it from Drive and"
                            " refreshes the spine skills. Coming from another machine,"
                            " run it with --old-home <that machine's folder> so its paths"
                            " get rewritten."),
            "root": ("Backups land under " + home_rel(self.env.root) + "/<name>."
                     if self.env.root else
                     "No base folder for backups yet — new tekas fall back to the legacy"
                     " path. Set it once: lifeproj root <path>."),
        }.get(row.key, "")

    def _new_hint(self, row: Row) -> str:
        c = self.c
        if row.kind == "chips":
            value = row.opts[self.chip.get(row.key, 0)][0]
            module = MODULES[CHIP_MODULE[value]]
            state = "on" if value in row.on else "off"
            extra = ""
            if value == "email":
                extra = " Needs an IMAP label — set it under More."
            elif value == "chapters":
                extra = f" One {c.chapter_noun} per subfolder; more than one may be active."
            return f"{value} ({state}) — {module.summary}.{extra}"
        if row.key == "name":
            if not c.name:
                return "The folder name and the registry key. Everything else defaults from it."
            if not valid_name(c.name):
                return "A plain folder name, not a path — it is joined onto the teka home."
            return (f"Working dir {self._default_path() if not c.path else c.path}; backed up to "
                    + (home_rel(self.env.root / c.name) if self.env.root else "the legacy gd-sync path")
                    + ".")
        if row.key == "domain":
            return domain_hint(c.domain)
        if row.key == "lifecycle":
            return ("Runs indefinitely — the catalog is the current state, not a project plan."
                    if c.lifecycle == "ongoing" else
                    "Has an end: it gets archived when it closes. Finite episodes *inside*"
                    " an ongoing teka are the chapters module instead.")
        if row.key == "summary":
            return ("One line about what the teka is for; it heads CLAUDE.md. Left empty,"
                    " the scaffold writes a placeholder for you to fill in.")
        if row.key == "more":
            return "m or space shows them."
        if row.key == "imap_folder":
            return "The IMAP label imap-extract reads into intake/mail/, e.g. Personal/Mila."
        if row.key == "chapter_noun":
            return f"What one chapter is called here — tenancy, case, season. Reads as: chapters/<{c.chapter_noun}>/."
        if row.key == "path":
            return f"Where the plaintext teka lives. Empty means {self._default_path()}."
        if row.key == "register":
            return ("Adds a [projects.<name>] entry to cmirror's config, so it gets backed"
                    " up nightly." if c.register else
                    "No cmirror entry: nothing will back this teka up. --no-register.")
        if row.key == "dry_run":
            return ("Prints the plan and writes nothing." if c.dry_run
                    else "Creates the teka for real.")
        return ""

    # --- what Enter runs ---

    def command(self) -> Optional[list]:
        """The argv the focused row stands for, or None when Enter only navigates."""
        row = self.current()
        if row is None or row.off:
            return None
        if self.screen == "new":
            return new_args(self.c) if valid_name(self.c.name) else None
        if self.screen == "teka":
            t = self.env.teka(self.teka_name)
            return teka_args(row.key, t) if t else None
        if row.key in ("overview", "brief", "equip", "root", "home"):
            return [row.key]
        if row.key == "restore_all":
            return ["restore", "--all"]
        return None

    # --- keys ---

    def current(self) -> Optional[Row]:
        rows = self.rows()
        for row in rows:
            if row.key == self.focus.get(self.screen):
                return row
        return rows[0] if rows else None

    def _move(self, delta: int) -> None:
        rows = self.rows()
        at = next((i for i, r in enumerate(rows) if r.key == self.focus.get(self.screen)), 0)
        i = at + delta
        while 0 <= i < len(rows):
            if not rows[i].off:
                self.focus[self.screen] = rows[i].key
                return
            i += delta

    def _cycle(self, delta: int) -> None:
        row = self.current()
        if row is None or row.off:
            return
        if row.kind == "chips":
            i = self.chip.get(row.key, 0) + delta
            self.chip[row.key] = max(0, min(i, len(row.opts) - 1))
            return
        if row.kind != "select":
            return
        values = [v for v, _ in row.opts]
        i = values.index(row.cur) if row.cur in values else 0
        self.set(row.key, values[max(0, min(i + delta, len(values) - 1))])

    def set(self, key: str, value: str) -> None:
        c = self.c
        if key in ("name", "summary", "path", "imap_folder", "chapter_noun"):
            setattr(c, key, value)
        elif key == "domain":
            c.domain = value
        elif key == "lifecycle":
            c.lifecycle = value
        elif key == "register":
            c.register = value == "yes"
        elif key == "dry_run":
            c.dry_run = value == "yes"

    def toggle(self, row: Row) -> None:
        value = row.opts[self.chip.get(row.key, 0)][0]
        target = self.c.intake if row.key == "intake" else self.c.artifact
        if value in target:
            target.remove(value)
        else:
            target.append(value)

    def _edit(self, row: Row) -> None:
        self.editing, self.buffer = row.key, row.cur

    def _commit(self) -> None:
        self.set(self.editing, self.buffer.strip())
        self.editing, self.buffer = "", ""
        self._move(1)

    def handle(self, key: Key) -> Optional[Done]:
        if self.editing:
            return self._handle_editing(key)
        self.note = ""
        row = self.current()
        if key.code == tui.KEY_UP:
            self._move(-1)
        elif key.code == tui.KEY_DOWN:
            self._move(1)
        elif key.code == tui.KEY_LEFT:
            self._cycle(-1)
        elif key.code == tui.KEY_RIGHT:
            self._cycle(1)
        elif key.code == tui.KEY_ENTER:
            return self.activate()
        elif key.code == tui.KEY_QUIT:
            return Done()
        elif key.code == tui.KEY_ESC:
            return self.back()
        elif key.code == tui.KEY_TAB and self.screen == "new":
            self._toggle_more()
        elif key.char == " " and row is not None and not row.off:
            if row.kind == "chips":
                self.toggle(row)
            elif row.kind == "text":
                self._edit(row)
            elif row.key == "more":
                self._toggle_more()
            else:
                self._cycle(1)
        elif key.char == "q":
            return Done()
        elif key.char == "?":
            return Done(["--help"])
        elif key.char == "n" and self.screen == "home":
            self.screen = "new"
        elif key.char == "m" and self.screen == "new":
            self._toggle_more()
        elif key.char in ("j", "k") and self.screen != "new":
            self._move(1 if key.char == "j" else -1)
        return None

    def _handle_editing(self, key: Key) -> Optional[Done]:
        if key.code == tui.KEY_ENTER:
            self._commit()
        elif key.code == tui.KEY_ESC:
            self.editing, self.buffer = "", ""
        elif key.code == tui.KEY_BACKSPACE:
            self.buffer = self.buffer[:-1]
        elif key.code == tui.KEY_CLEAR:
            self.buffer = ""
        elif key.code == tui.KEY_QUIT:
            return Done()
        elif key.char and key.char >= " ":
            self.buffer += key.char
        return None

    def activate(self) -> Optional[Done]:
        row = self.current()
        if row is None or row.off:
            return None
        if self.screen == "home":
            if row.key == "new":
                self.screen = "new"
                return None
            if row.key.startswith("teka:"):
                self.teka_name = row.key[5:]
                self.screen = "teka"
                # A teka with no local copy cannot publish; open on what it can do.
                self.focus["teka"] = next((r.key for r in self._teka_rows() if not r.off),
                                          "back")
                return None
        if row.key == "back":
            return self.back()
        if row.key == "more":
            self._toggle_more()
            return None
        if self.screen == "new" and not valid_name(self.c.name):
            self.focus["new"] = "name"
            self._edit(self._new_rows()[0])
            self.note = ("Give it a name first." if not self.c.name else
                         "A teka name is a plain folder name — no slashes, no path.")
            return None
        args = self.command()
        return Done(args) if args else None

    def back(self) -> Optional[Done]:
        if self.screen == "home":
            return Done()
        self.screen = "home"
        return None

    def _toggle_more(self) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            self.focus["new"] = next((r.key for r in self._new_rows()[6:] if not r.off), "name")
        elif self.focus["new"] not in [r.key for r in self._new_rows()]:
            self.focus["new"] = "more"

    # --- background detail ---

    def start_loading(self) -> None:
        def work():
            try:
                self.inbox.put(enrich(self.env))
            except Exception:                       # never take the menu down
                self.env.loaded = True
        threading.Thread(target=work, daemon=True).start()

    def tick(self) -> bool:
        try:
            self.env = self.inbox.get_nowait()
        except queue.Empty:
            return False
        return True

    # --- drawing ---

    def render(self, w: int, h: int) -> list:
        self.w, self.h = w, h
        out = [self._header(), []]
        focused, tekas_seen = None, False
        for row in self.rows():
            if self.screen == "new" and row.key in ("imap_folder", "more"):
                out.append([])
            if self.screen == "home" and row.key.startswith("teka:") and not tekas_seen:
                tekas_seen = True
                out += [[], [Seg("   " + tui.pad("TEKA", 14), DIM),
                             Seg(" what is waiting, and how old the backup is", DIM)]]
            if row.key == self.focus.get(self.screen):
                focused = row
            out.append(self._line(row, row is focused))
        if self.screen == "home" and not tekas_seen:
            out += [[], [Seg("   No tekas registered yet — New teka makes the first one.", DIM)]]
        out.append([])
        for line in tui.wrap(self.note or self.hint(focused), max(w - 6, 20)):
            out.append([Seg("   " + line)])
        out.append([])
        args = self.command()
        if args:
            out.append([Seg(" $ ", DIM), Seg(preview(args), GREEN)])
        return out

    def _header(self) -> list:
        if self.screen == "teka":
            t = self.env.teka(self.teka_name)
            where = home_rel(t.working_dir) if t else ""
            return [Seg(" " + self.teka_name, BOLD), Seg(" · " + where, DIM)]
        if self.screen == "new":
            return [Seg(" New teka", BOLD), Seg(" · " + self._default_path(), DIM)]
        live = [t for t in self.env.tekas if not t.archived]
        tail = f" · {len(live)} teka{'' if len(live) == 1 else 's'}"
        if not self.env.root:
            return [Seg(f" lifeproj {__version__}", BOLD), Seg(tail, DIM),
                    Seg("  ● no backup root set", YELLOW)]
        return [Seg(f" lifeproj {__version__}", BOLD), Seg(tail, DIM),
                Seg(" · backups → " + home_rel(self.env.root), DIM)]

    def _line(self, row: Row, focused: bool) -> list:
        mark = " › " if focused else "   "
        line = [Seg(mark, CYAN), Seg(tui.pad(row.label, 14), BOLD if focused else "")]
        if row.off:
            line[1] = Seg(tui.pad(row.label, 14), DIM)
            return line + [Seg(" " + row.off, DIM)]
        if row.kind == "action":
            return line + [Seg(" " + row.desc, DIM)]
        if row.kind == "text":
            if self.editing == row.key:
                return line + [Seg(" " + self.buffer), Seg(" ", REVERSE)]
            if row.cur:
                return line + [Seg(" " + row.cur, CYAN + BOLD)]
            return line + [Seg(" " + row.empty, DIM)]
        if row.kind == "chips":
            at = self.chip.get(row.key, 0)
            for i, (value, label) in enumerate(row.opts):
                on = value in row.on
                style = CYAN + BOLD if on else DIM
                if focused and i == at:
                    style = REVERSE
                line.append(Seg(f" {'●' if on else '○'} {label} ", style))
            return line
        for value, label in row.opts:
            if value == row.cur:
                line.append(Seg(f" {label} ", REVERSE if focused else CYAN + BOLD))
            else:
                line.append(Seg(f" {label} ", DIM))
        return line

    def footer(self) -> list:
        if self.editing:
            return [Seg(" Enter done · esc cancel · ctrl-u clear", DIM)]
        row = self.current()
        keys = ["Enter " + ("create" if self.screen == "new" else
                            "run" if self.screen == "teka" else "open"), "↑↓ move"]
        if row is not None and not row.off:
            if row.kind == "select":
                keys.append("←→ choose")
            elif row.kind == "chips":
                keys.append("←→ move · space toggle")
            elif row.kind == "text":
                keys.append("space edit")
        if self.screen == "new":
            keys.append("m more")
        elif self.screen == "home":
            keys.append("n new teka")
        keys.append("esc " + ("quit" if self.screen == "home" else "back"))
        return [Seg(" " + " · ".join(keys), DIM)]


def run(config: Optional[Path] = None) -> Optional[list]:
    """Open the menu; return the argv it composed, or None if it was closed.

    Raises OSError if the terminal cannot be driven after all — the caller
    falls back to the usage it would have printed without a menu.
    """
    menu = Menu(environment(config), load_choice())
    menu.start_loading()
    done = tui.run(menu)
    if done is None or done.args is None:
        return None
    if done.args and done.args[0] == "new":
        save_choice(menu.c)
    return done.args
