"""`lifeproj overview` — the one cross-teka view that genuinely helps.

Read-only. For each active teka: does the working dir exist, how many items are
waiting in intake/, and how old is the last backup (mtime of the encrypted
manifest.age). Archived tekas are listed compactly. Nothing here mutates state.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from lifeproj import registry


def _intake_count(working_dir: Path) -> Optional[int]:
    inbox = working_dir / "intake"
    if not inbox.exists():
        return None
    n = 0
    for p in inbox.rglob("*"):
        if p.is_file() and p.name not in (".DS_Store", ".env", "state.json"):
            n += 1
    return n


def _backup_age(encrypted_dir: Path) -> Optional[str]:
    manifest = encrypted_dir / "manifest.age"
    if not manifest.exists():
        return None
    age = time.time() - manifest.stat().st_mtime
    days = age / 86400
    if days >= 1:
        return f"{days:.0f}d ago"
    hours = age / 3600
    if hours >= 1:
        return f"{hours:.0f}h ago"
    return f"{age/60:.0f}m ago"


def collect(config_path: Optional[Path] = None) -> dict:
    doc = registry.load(config_path)
    active = []
    for name, table in registry.projects(doc).items():
        wd = Path(str(table.get("working_dir", ""))).expanduser()
        ed = Path(str(table.get("encrypted_dir", ""))).expanduser()
        active.append({
            "name": name,
            "exists": wd.exists(),
            "intake": _intake_count(wd) if wd.exists() else None,
            "backup": _backup_age(ed),
            "imap_folder": str(table.get("imap_folder", "")) or None,
        })
    archived = sorted(registry.archived(doc).keys())
    return {"active": active, "archived": archived}


def render(data: dict) -> str:
    lines = []
    active = data["active"]
    if not active:
        lines.append("No active tekas registered.")
    else:
        lines.append(f"{'TEKA':<20} {'INTAKE':>7}  {'BACKUP':>10}  {'MAIL':<16}")
        lines.append("-" * 58)
        for t in active:
            intake = "?" if t["intake"] is None else str(t["intake"])
            if not t["exists"]:
                intake = "—"
            backup = t["backup"] or "never"
            mail = t["imap_folder"] or ""
            flag = "" if t["exists"] else "  (no local copy)"
            lines.append(f"{t['name']:<20} {intake:>7}  {backup:>10}  {mail:<16}{flag}")
    if data["archived"]:
        lines.append("")
        lines.append("Archived: " + ", ".join(data["archived"]))
    return "\n".join(lines)
