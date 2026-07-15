"""`lifeproj equip` — sync spine skills into existing tekas.

`lifeproj new` stamps spine skills into every fresh teka; this is the retrofit
path for tekas scaffolded before a skill existed (or to pick up a newer
version of one). Registry-driven like `drain --all`, resilient the same way:
one teka's failure is logged and the fleet continues.

A teka may have deliberately customized its copy of a skill, so an existing
file that differs from the packaged version is *kept* by default and reported;
``--force`` overwrites it. `CLAUDE.md` is a living document, so it gets the
lightest possible touch: when its manual still carries the standard
"## Working rules" section and doesn't mention the skill, the working-rule
bullet is appended to that section; a manual customized beyond that anchor is
left alone and the bullet is printed for a human (or the teka's own session)
to paste.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from lifeproj import registry, templates

# relpath inside the teka -> relpath under src/lifeproj/data/
SPINE_SKILLS = {
    ".claude/skills/humanize/SKILL.md": "skills/humanize/SKILL.md",
}

CLAUDE_RULE_HINT = """\
- **Drafts sound human.** Write every outgoing draft (email, letter, document)
  with the `humanize` skill (`.claude/skills/humanize/`): no AI tells — em-dash
  tics, "not X, but Y", rule-of-three, mechanical boldface. Match Vlad's own
  voice from prior outgoing mail in `correspondence/` where it exists."""


def _add_claude_rule(claude: Path, *, dry_run: bool) -> Optional[str]:
    """Append the drafting rule to CLAUDE.md's working-rules section. Returns
    the action taken, or None when the standard heading is gone and the bullet
    must be pasted by hand."""
    lines = claude.read_text().splitlines()
    start = next((i for i, line in enumerate(lines)
                  if line.startswith("## Working rules")), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("## ")), len(lines))
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    lines[end:end] = CLAUDE_RULE_HINT.splitlines()
    if not dry_run:
        claude.write_text("\n".join(lines) + "\n")
    return "drafting rule added to working rules"


def equip_teka(wd: Path, *, force: bool = False, dry_run: bool = False) -> dict:
    """Sync spine skills into one teka dir. Returns a result entry."""
    entry = {"teka": wd.name, "dir": str(wd), "status": "ok",
             "actions": [], "claude_hint": False, "error": None}
    if not wd.is_dir():
        entry["status"], entry["error"] = "skipped", "working_dir missing locally"
        return entry
    if not (wd / "catalog.json").exists():
        entry["status"], entry["error"] = "skipped", "no catalog.json (not a teka dir)"
        return entry

    for relpath, datapath in SPINE_SKILLS.items():
        wanted = templates.data(datapath)
        target = wd / relpath
        if not target.exists():
            action = "installed"
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(wanted)
        elif target.read_text() == wanted:
            action = "current"
        elif force:
            action = "updated"
            if not dry_run:
                target.write_text(wanted)
        else:
            action = "differs (kept; --force overwrites)"
        entry["actions"].append((relpath, action))

    claude = wd / "CLAUDE.md"
    if claude.exists() and ".claude/skills/humanize" not in claude.read_text():
        action = _add_claude_rule(claude, dry_run=dry_run)
        if action:
            entry["actions"].append(("CLAUDE.md", action))
        else:
            entry["claude_hint"] = True
    return entry


def equip_all(config_path: Optional[Path] = None, *, names: Optional[list] = None,
              force: bool = False, dry_run: bool = False) -> int:
    """Equip every registered active teka (or just ``names``). Exit code 1 if
    any teka errored or a requested name is unknown; skips are not errors."""
    doc = registry.load(config_path)
    fleet = registry.projects(doc)
    if names:
        unknown = [n for n in names if n not in fleet]
        for n in unknown:
            print(f"error: teka {n!r} not registered under [projects.*]")
        fleet = {n: t for n, t in fleet.items() if n in (names or [])}
        if unknown:
            return 1

    prefix = "[dry-run] " if dry_run else ""
    rc, hint_needed = 0, []
    for name, table in fleet.items():
        wd_raw = table.get("working_dir") if hasattr(table, "get") else None
        if not wd_raw:
            print(f"{name}: error — no working_dir in registry")
            rc = 1
            continue
        entry = equip_teka(Path(str(wd_raw)).expanduser(), force=force, dry_run=dry_run)
        entry["teka"] = name
        if entry["status"] == "skipped":
            print(f"{prefix}{name}: skipped — {entry['error']}")
            continue
        summary = "; ".join(f"{rel}: {act}" for rel, act in entry["actions"])
        print(f"{prefix}{name}: {summary}")
        if entry["claude_hint"]:
            hint_needed.append(name)

    if hint_needed:
        print(f"\nCLAUDE.md in {', '.join(hint_needed)} has no standard working-rules"
              " section to extend. Paste this bullet where it fits:\n")
        print(CLAUDE_RULE_HINT)
    return rc
