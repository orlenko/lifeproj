"""`lifeproj new` — stamp a teka from the spine + opt-in modules."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lifeproj import intake, registry, templates
from lifeproj.modules import OVERLAYS, Module, resolve


@dataclass
class Plan:
    name: str
    working_dir: Path
    encrypted_dir: Path
    imap_folder: Optional[str]
    dirs: list = field(default_factory=list)
    files: dict = field(default_factory=dict)        # relpath -> contents
    register: bool = True
    notes: list = field(default_factory=list)


def build(name: str, working_dir: Path, encrypted_dir: Path, *, domain: str,
          lifecycle: str, summary: str, modules: list, created: str,
          imap_folder: Optional[str] = None, chapter_noun: str = "chapter",
          register: bool = True) -> Plan:
    mods: list[Module] = resolve(modules)
    needs_imap = any(m.needs_imap for m in mods)

    intake_label = ", ".join(m.name for m in mods if "intake" in m.name or m.needs_imap) or "manual"
    artifact_label = ", ".join(
        m.name for m in mods if m.name in {"timeline", "ledger", "chapters", "entities"}
    ) or "catalog"

    # --- CLAUDE.md ---
    claude = templates.render(
        templates.CLAUDE_HEADER, NAME=name, DOMAIN=domain, LIFECYCLE=lifecycle,
        CREATED=created, INTAKE=intake_label, ARTIFACT=artifact_label, SUMMARY=summary,
    )
    repo_rows = []
    for m in mods:
        section = templates.render(m.claude_section, CHAPTER_NOUN=chapter_noun)
        if section.strip():
            claude += "\n" + section
        for path, desc in m.repo_rows:
            repo_rows.append("| `{}` | {} |".format(
                templates.render(path, CHAPTER_NOUN=chapter_noun),
                templates.render(desc, CHAPTER_NOUN=chapter_noun),
            ))
    overlay = OVERLAYS.get(domain)
    if overlay:
        claude += "\n" + overlay
    claude += "\n" + templates.render(
        templates.CLAUDE_FOOTER, REPO_MAP_ROWS="\n".join(repo_rows))

    # --- catalog.json (spine + module arrays) ---
    catalog = {
        "meta": {
            "schema_version": 2,
            "name": name,
            "domain": domain,
            "lifecycle": lifecycle,
            "created": created,
            "next_doc_id": 1,
            "next_item_id": 1,
            "profile": {},
        },
        "documents": [],
        "open_items": [],
        "processing_log": [],
    }
    for m in mods:
        for arr in m.catalog_arrays:
            catalog.setdefault(arr, [])

    files = {
        "CLAUDE.md": claude,
        "README.md": templates.render(
            templates.README_TMPL, NAME=name, SUMMARY=summary, DOMAIN=domain,
            LIFECYCLE=lifecycle, CREATED=created, ENCRYPTED_DIR=str(encrypted_dir)),
        "DASHBOARD.md": templates.render(templates.DASHBOARD_TMPL, NAME=name),
        "catalog.json": json.dumps(catalog, indent=2) + "\n",
        "catalog_check.py": templates.CATALOG_CHECK,
        # Spine skill: every teka drafts outgoing text through the humanize
        # skill (copied in verbatim — thick teka, thin centre).
        ".claude/skills/humanize/SKILL.md": templates.data("skills/humanize/SKILL.md"),
    }
    dirs = ["intake", "scripts"]
    for m in mods:
        dirs.extend(m.dirs)
        for relpath, contents in m.files.items():
            files[relpath] = templates.render(contents, CHAPTER_NOUN=chapter_noun)

    plan = Plan(name=name, working_dir=working_dir, encrypted_dir=encrypted_dir,
                imap_folder=imap_folder if needs_imap else None,
                dirs=sorted(set(dirs)), files=files, register=register)

    if needs_imap and not imap_folder:
        plan.notes.append("email-intake module is on but no --imap-folder given; "
                          "intake/mail/.env will use placeholders.")
    return plan


def apply(plan: Plan, *, shared_env: Optional[Path] = None,
          config_path: Optional[Path] = None) -> dict:
    wd = plan.working_dir
    wd.mkdir(parents=True, exist_ok=True)
    for d in plan.dirs:
        (wd / d).mkdir(parents=True, exist_ok=True)
    for relpath, contents in plan.files.items():
        target = wd / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
    (wd / "catalog_check.py").chmod(0o755)

    result = {"working_dir": str(wd), "files": sorted(plan.files), "registered": False,
              "env": None, "notes": list(plan.notes)}

    if plan.imap_folder is not None:
        env_path = intake.write(wd, plan.imap_folder, shared=shared_env)
        result["env"] = str(env_path)

    if plan.register:
        doc = registry.load(config_path)
        try:
            registry.add(doc, plan.name, str(wd), str(plan.encrypted_dir),
                         imap_folder=plan.imap_folder)
            registry.save(doc, config_path)
            result["registered"] = True
        except ValueError as exc:
            result["notes"].append(f"not registered: {exc}")
    return result
