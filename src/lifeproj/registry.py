"""The teka registry IS cmirror's config.toml.

cmirror reads only ``[projects.<name>]`` tables, and it *silently ignores unknown
keys* inside them (verified in cmirror's config loader). lifeproj exploits both
facts:

* a live teka is a ``[projects.<name>]`` table — cmirror backs it up nightly;
* an archived teka is moved to ``[archived.<name>]`` — cmirror stops touching it,
  but lifeproj still sees it (it reads both sections), so the record survives;
* the extra ``imap_folder`` key rides along inside the project table — cmirror
  ignores it, the intake shim reads it;
* lifeproj's own settings ride in a ``[lifeproj]`` table cmirror ignores the same
  way it ignores ``[archived]``. Today that's ``encrypted_root`` — the base
  folder under which new tekas' ``encrypted_dir`` defaults to ``<root>/<name>``,
  so backup targets are never micromanaged per teka (set once via
  ``lifeproj root``).

No new config file is invented, and nothing here ever writes a key or passphrase:
the age identity stays in cmirror's own ``identity_file``, outside every teka.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import tomlkit
from tomlkit import TOMLDocument

ACTIVE = "projects"
ARCHIVED = "archived"
LIFEPROJ = "lifeproj"

_NEW_CONFIG_HEADER = (
    "# cmirror configuration — also the lifeproj teka registry.\n"
    "# PATHS only, never a key or passphrase. Generate the age identity with\n"
    "#   cmirror genkey\n"
    "# Active tekas live under [projects.<name>]; archived ones under\n"
    "# [archived.<name>] (cmirror ignores those, lifeproj still tracks them).\n"
)


def config_path() -> Path:
    """Locate the cmirror config: $CMIRROR_CONFIG, else the default path."""
    env = os.environ.get("CMIRROR_CONFIG")
    if env:
        return Path(env).expanduser()
    return Path("~/.config/cmirror/config.toml").expanduser()


def load(path: Optional[Path] = None) -> TOMLDocument:
    path = path or config_path()
    try:
        return tomlkit.parse(path.read_text())
    except FileNotFoundError:
        return tomlkit.parse(_NEW_CONFIG_HEADER)


def save(doc: TOMLDocument, path: Optional[Path] = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc))
    return path


def _section(doc: TOMLDocument, key: str):
    return doc.get(key)


def projects(doc: TOMLDocument) -> dict:
    sec = _section(doc, ACTIVE)
    return dict(sec) if sec else {}


def archived(doc: TOMLDocument) -> dict:
    sec = _section(doc, ARCHIVED)
    return dict(sec) if sec else {}


def encrypted_root(doc: TOMLDocument) -> Optional[Path]:
    """The configured base folder for encrypted backups, or None.

    ``[lifeproj].encrypted_root`` in cmirror's config; new tekas default their
    ``encrypted_dir`` to ``<root>/<name>``.
    """
    sec = _section(doc, LIFEPROJ)
    raw = sec.get("encrypted_root") if sec else None
    return Path(str(raw)).expanduser() if raw else None


def set_encrypted_root(doc: TOMLDocument, path: Path) -> None:
    if LIFEPROJ not in doc:
        doc[LIFEPROJ] = tomlkit.table()
    doc[LIFEPROJ]["encrypted_root"] = str(path)


def rehome_missing(doc: TOMLDocument, root: Path) -> list:
    """Repoint active tekas whose ``encrypted_dir`` is absent on disk to
    ``<root>/<name>``. An ``encrypted_dir`` that exists holds real ciphertext
    and is never touched (moving data is cmirror's business, done by hand).
    Mutates ``doc``; returns ``[(name, old, new), ...]`` for what changed.
    """
    moved = []
    sec = _section(doc, ACTIVE) or {}
    for name in sec:
        table = sec[name]
        old = table.get("encrypted_dir")
        new = str(root / name)
        if old and Path(str(old)).expanduser().exists():
            continue
        if old is not None and str(old) == new:
            continue
        table["encrypted_dir"] = new
        moved.append((name, str(old) if old is not None else None, new))
    return moved


def find(doc: TOMLDocument, name: str):
    """Return (section_key, table) for ``name`` in either section, or (None, None)."""
    for key in (ACTIVE, ARCHIVED):
        sec = _section(doc, key)
        if sec is not None and name in sec:
            return key, sec[name]
    return None, None


def add(doc: TOMLDocument, name: str, working_dir: str, encrypted_dir: str,
        imap_folder: Optional[str] = None) -> None:
    section, _ = find(doc, name)
    if section is not None:
        raise ValueError(f"teka {name!r} already registered under [{section}.{name}]")
    if ACTIVE not in doc:
        doc[ACTIVE] = tomlkit.table(is_super_table=True)
    table = tomlkit.table()
    table["working_dir"] = working_dir
    table["encrypted_dir"] = encrypted_dir
    if imap_folder:
        table["imap_folder"] = imap_folder
    doc[ACTIVE][name] = table


def _move(doc: TOMLDocument, name: str, src: str, dst: str) -> None:
    src_sec = _section(doc, src)
    if src_sec is None or name not in src_sec:
        raise KeyError(f"teka {name!r} not found under [{src}.*]")
    table = src_sec[name]
    if dst not in doc:
        doc[dst] = tomlkit.table(is_super_table=True)
    doc[dst][name] = table
    del src_sec[name]


def archive(doc: TOMLDocument, name: str) -> None:
    """Move projects.<name> -> archived.<name> (cmirror stops backing it up)."""
    _move(doc, name, ACTIVE, ARCHIVED)


def restore(doc: TOMLDocument, name: str) -> None:
    """Move archived.<name> -> projects.<name> (cmirror resumes backing it up)."""
    _move(doc, name, ARCHIVED, ACTIVE)
