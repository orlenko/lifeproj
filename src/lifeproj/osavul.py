"""Osavul integration — project a teka's open_items[] into the cross-teka spool.

A teka cannot read another teka's folder (each runs in its own sandbox). Osavul,
the chief-of-staff teka, rolls up outstanding work across every teka by reading a
neutral **spool** that is in every session's grant set:

    ~/.local/share/osavul/
      inbox/   <teka>.agenda.json   each teka WRITES its slice; Osavul READS all
      outbox/  <teka>.intake.json   Osavul WRITES routed items; teka drains (v2)
      state/                        Osavul's own merged output

This module owns the publish/drain **mechanism**. It is single-sourced here (not
copied into each teka like ``catalog_check.py``) precisely because the agenda
slice is a shared interface that must stay byte-identical across every teka. It
publishes *one* teka's own slice; the cross-teka roll-up is Osavul's job, not
lifeproj's.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

# The agenda-slice contract (mirrors docs/DESIGN.md and the catalog_check.py
# template — keep the three in sync).
STATUSES = ("open", "waiting", "blocked", "done")
PRIORITIES = ("high", "normal", "low")
# Fields projected from each open_item into a slice item, in canonical order.
ITEM_FIELDS = ("id", "title", "status", "priority", "due", "no_deadline",
               "tags", "waiting_on", "link")


def spool_root() -> Path:
    """Resolve the Osavul spool directory.

    ``OSAVUL_SPOOL`` overrides everything (tests, alternative layouts); otherwise
    the XDG data dir, defaulting to ``~/.local/share/osavul``.
    """
    env = os.environ.get("OSAVUL_SPOOL")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "osavul"


def _grant_hint(root: Path) -> str:
    return (f"osavul spool not provisioned at {root} — skipping publish (not an error). "
            f"To enable: grant {root} in the sandbox profile and create "
            f"{root}/{{inbox,outbox,state}} (Phase 0).")


def validate_open_items(items, processing_log=()) -> list:
    """Return a list of human-readable errors for a teka's ``open_items[]``.

    Same rules as the copied-in ``catalog_check.py``; used here so ``publish``
    refuses to emit an invalid slice into the shared spool.
    """
    errors: list = []
    seen: set = set()
    closed = {e["id"] for e in processing_log
              if isinstance(e, dict) and "id" in e}
    for i, it in enumerate(items):
        where = f"open_items[{i}]"
        if not isinstance(it, dict):
            errors.append(f"{where}: not an object")
            continue
        iid = it.get("id")
        for field in ("id", "title", "status", "priority"):
            if not it.get(field):
                errors.append(f"{where}: missing required '{field}'")
        if iid:
            if iid in seen:
                errors.append(f"{where}: duplicate id {iid!r}")
            if iid in closed:
                errors.append(f"{where}: id {iid!r} reused from processing_log")
            seen.add(iid)
        if it.get("status") and it["status"] not in STATUSES:
            errors.append(f"{where}: bad status {it['status']!r} (use {'|'.join(STATUSES)})")
        if it.get("priority") and it["priority"] not in PRIORITIES:
            errors.append(f"{where}: bad priority {it['priority']!r} (use {'|'.join(PRIORITIES)})")
        has_due = it.get("due") not in (None, "")
        no_dl = it.get("no_deadline") is True
        if has_due and no_dl:
            errors.append(f"{where}: has both 'due' and no_deadline:true (use exactly one)")
        if not has_due and not no_dl:
            errors.append(f"{where}: needs a 'due' date or no_deadline:true (nothing silently dateless)")
        if has_due:
            try:
                date.fromisoformat(it["due"])
            except (ValueError, TypeError):
                errors.append(f"{where}: 'due' not an ISO date (YYYY-MM-DD): {it['due']!r}")
        if it.get("status") in ("waiting", "blocked") and not it.get("waiting_on"):
            errors.append(f"{where}: status {it.get('status')!r} requires 'waiting_on'")
        if "tags" in it and not isinstance(it["tags"], list):
            errors.append(f"{where}: 'tags' must be a list")
        if "redact" in it and not isinstance(it["redact"], bool):
            errors.append(f"{where}: 'redact' must be true/false")
        if "slice_title" in it and not (isinstance(it["slice_title"], str) and it["slice_title"]):
            errors.append(f"{where}: 'slice_title' must be a non-empty string")
    return errors


def teka_name(catalog: dict, teka_dir: Path) -> str:
    meta = catalog.get("meta") or {}
    return meta.get("name") or teka_dir.name


def project_slice(catalog: dict, teka_dir: Path, *, now: Optional[str] = None) -> dict:
    """Project a teka's catalog into the canonical agenda slice."""
    meta = catalog.get("meta") or {}
    # Active chapters: meta.active_chapters is canonical (0/1/many), with a
    # fallback to meta.current_chapters for tekas mid-migration. active_chapter
    # (string|null) is kept for the single/back-compat case and auto-filled when
    # exactly one chapter is active.
    chapters = meta.get("active_chapters")
    if chapters is None:
        chapters = meta.get("current_chapters")
    if isinstance(chapters, str):
        chapters = [chapters]
    chapters = [c for c in (chapters or []) if c]
    active_chapter = meta.get("active_chapter")
    if active_chapter is None and len(chapters) == 1:
        active_chapter = chapters[0]
    teka = teka_name(catalog, teka_dir)
    items = []
    for it in catalog.get("open_items", []):
        # Teka-prefix the slice id so it is globally unique in Osavul's merged
        # view — idempotently, so already-prefixed catalog ids aren't doubled.
        raw_id = it.get("id")
        if raw_id and not str(raw_id).startswith(f"{teka}-"):
            slice_id = f"{teka}-{raw_id}"
        else:
            slice_id = raw_id
        # Redact at the slice boundary: the catalog keeps the natural full title;
        # slice_title (explicit) wins, else redact:true emits generic placeholders.
        # redact also covers waiting_on (free-text party names); tags pass through
        # unchanged so Osavul can still key on functional tags (e.g. needs-date).
        redacted = it.get("redact") is True
        if it.get("slice_title"):
            title = it["slice_title"]
        elif redacted:
            title = "[redacted]"
        else:
            title = it.get("title")
        items.append({
            "id": slice_id,
            "title": title,
            "status": it.get("status"),
            "priority": it.get("priority"),
            "due": it.get("due"),
            "no_deadline": bool(it.get("no_deadline", False)),
            "tags": it.get("tags", []),
            "waiting_on": "[party]" if redacted else it.get("waiting_on"),
            "link": it.get("link"),
        })
    return {
        "teka": teka,
        "lifecycle": meta.get("lifecycle"),
        "active_chapter": active_chapter,
        "active_chapters": chapters,
        "generated": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": items,
    }


def _load_catalog(teka_dir: Path):
    catalog_path = teka_dir / "catalog.json"
    if not catalog_path.exists():
        print(f"error: no catalog.json in {teka_dir} (run from inside a teka)",
              file=sys.stderr)
        return None
    try:
        return json.loads(catalog_path.read_text())
    except json.JSONDecodeError as exc:
        print(f"error: catalog.json is not valid JSON: {exc}", file=sys.stderr)
        return None


def publish(teka_dir: Optional[Path] = None, *, now: Optional[str] = None) -> int:
    """Write this teka's agenda slice to the spool. Returns a process exit code.

    No-ops cleanly (exit 0 + a one-line hint) if the spool isn't provisioned, so
    it is safe to run as the last step of every digest.
    """
    teka_dir = Path(teka_dir) if teka_dir else Path.cwd()
    catalog = _load_catalog(teka_dir)
    if catalog is None:
        return 2

    errors = validate_open_items(catalog.get("open_items", []),
                                 catalog.get("processing_log", []))
    if errors:
        print("error: open_items[] is invalid — fix it (see catalog_check.py) "
              "before publishing:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    root = spool_root()
    if not root.exists():
        print(_grant_hint(root))
        return 0

    slice_obj = project_slice(catalog, teka_dir, now=now)
    name = slice_obj["teka"]
    inbox = root / "inbox"
    try:
        inbox.mkdir(parents=True, exist_ok=True)
        target = inbox / f"{name}.agenda.json"
        tmp = inbox / f".{name}.agenda.json.tmp"
        tmp.write_text(json.dumps(slice_obj, indent=2) + "\n")
        os.replace(tmp, target)
    except OSError as exc:
        # Spool exists but we can't write — treat as not-granted, don't crash.
        print(f"{_grant_hint(root)} ({exc})")
        return 0

    print(f"published {len(slice_obj['items'])} open item(s) → {target}")
    return 0


def drain(teka_dir: Optional[Path] = None) -> int:
    """v2 stub: file items Osavul routed back via ``outbox/`` into ``intake/``.

    Documented and wired as a subcommand now; the filing step lands in v2. This
    never mutates anything yet.
    """
    teka_dir = Path(teka_dir) if teka_dir else Path.cwd()
    catalog = _load_catalog(teka_dir)
    if catalog is None:
        return 2
    name = teka_name(catalog, teka_dir)
    outbox_file = spool_root() / "outbox" / f"{name}.intake.json"

    print("`lifeproj drain` is a documented v2 stub — the filing step is not wired yet.")
    if outbox_file.exists():
        try:
            data = json.loads(outbox_file.read_text())
            n = len(data.get("items", []))
        except (json.JSONDecodeError, OSError):
            n = "?"
        print(f"would file {n} routed item(s) from {outbox_file} into {teka_dir}/intake/, "
              "then clear the outbox slot.")
    else:
        print(f"no outbox slice at {outbox_file}; nothing to drain.")
    print("Contract: see lifeproj docs/DESIGN.md → 'Osavul integration' (outbox schema).")
    return 0
