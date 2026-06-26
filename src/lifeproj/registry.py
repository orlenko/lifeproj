"""The teka registry IS cmirror's config.toml.

cmirror reads only ``[projects.<name>]`` tables, and it *silently ignores unknown
keys* inside them (verified in cmirror's config loader). lifeproj exploits both
facts:

* a live teka is a ``[projects.<name>]`` table — cmirror backs it up nightly;
* an archived teka is moved to ``[archived.<name>]`` — cmirror stops touching it,
  but lifeproj still sees it (it reads both sections), so the record survives;
* the extra ``imap_folder`` key rides along inside the project table — cmirror
  ignores it, the intake shim reads it.

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
    if path.exists():
        return tomlkit.parse(path.read_text())
    doc = tomlkit.parse(_NEW_CONFIG_HEADER)
    return doc


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
