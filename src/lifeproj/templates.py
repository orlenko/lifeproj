"""Embedded teka templates.

Templates use ``{{TOKEN}}`` placeholders rendered by :func:`render` (a plain
string replace, so literal ``{`` / ``}`` in file bodies are safe). Keeping the
templates as Python constants makes the tool dependency-free at runtime and easy
to read — a teka is meant to be edited after it's stamped, not driven by a
hidden template engine.
"""

from __future__ import annotations


def render(text: str, **tokens: str) -> str:
    for key, value in tokens.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


CLAUDE_HEADER = """\
# {{NAME}}

> Operating manual for this teka. Loaded every Claude Code session — read it
> fully before acting. A *teka* is a local, encrypted, Claude-maintained
> life-admin project (see lifeproj/docs/DESIGN.md).

- **Domain:** {{DOMAIN}}
- **Lifecycle:** {{LIFECYCLE}}  (ongoing = no end; finite = completes on a deliverable/decision)
- **Created:** {{CREATED}}
- **Intake:** {{INTAKE}}
- **Artifact(s):** {{ARTIFACT}}

## What this teka is

{{SUMMARY}}

## Working rules (the spine, identical across tekas)

- **Current truth first.** The job is to keep `catalog.json` and `DASHBOARD.md`
  reflecting *what is true now*. We do not track change-history; we track the
  present state (+ an explicit `timeline.md` only where a module adds one).
- **The digest ritual** (run it whenever new material lands): drain `intake/` →
  for each item read → classify → rename to `YYYY-MM-DD_slug` → move into the
  right folder → record it in `catalog.json` → append a `processing_log[]` entry
  → regenerate `DASHBOARD.md` → leave `intake/` empty. Never delete originals.
- **Monitors flag, humans act.** Intake/watchers only surface new material. Never
  send a message, sign, pay, or commit anything outbound without Vlad's explicit
  approval. Drafts wait in place for review.
- **Privacy posture.** Everything stays local. The only thing that leaves this
  machine is the *encrypted* cmirror backup. Do not paste teka contents into web
  tools or external services.
- **Validate state.** Run `python3 catalog_check.py` after editing `catalog.json`.
"""

CLAUDE_FOOTER = """\
## Repository map

| Path | What lives here |
| ---- | --------------- |
| `CLAUDE.md` | This operating manual. |
| `README.md` | Human "start here" overview. |
| `DASHBOARD.md` | At-a-glance current truth, regenerated from `catalog.json`. |
| `catalog.json` | Structured single source of truth (documents / open items / log). |
| `catalog_check.py` | Validator for `catalog.json`. |
| `intake/` | Transient dropzone — drained after filing (presence == unprocessed). |
{{REPO_MAP_ROWS}}

## Notes

- Bespoke scripts for *this* teka live in `scripts/`. Generic, reusable tools
  (imap-extract, OCR/convert, eml→md) come from the homebrew tap and are called,
  not copied.
- This file is the source of truth for *how* to work this teka; add a row above
  whenever you add a folder.
"""

README_TMPL = """\
# {{NAME}}

{{SUMMARY}}

**Start here:** open this folder in Claude Code — `CLAUDE.md` is the operating
manual. `DASHBOARD.md` is the current-state view.

- Domain: {{DOMAIN}} · Lifecycle: {{LIFECYCLE}} · Created: {{CREATED}}
- Backup: encrypted via cmirror → `{{ENCRYPTED_DIR}}` (only ciphertext leaves the machine).
"""

DASHBOARD_TMPL = """\
# {{NAME}} — dashboard

_Regenerated from `catalog.json`. This is **current truth**, not history._

_Last updated: (set on first digest)_

## At a glance

- Status: newly scaffolded.

## Open items

_None yet._

## Deadlines

_None yet._

## Where things live

See `CLAUDE.md` → Repository map.
"""

TEKA_GITIGNORE = """\
# Secrets and machine-local cruft — never commit a teka anyway, but just in case.
.env
**/.env
.DS_Store
**/.DS_Store
intake/_converted/
**/state.json
*.tmp
"""

# A small, dependency-free validator copied INTO each teka (thick teka, thin
# centre). Validates the core spine and any extra ``*[]`` arrays of objects with
# an ``id``, so module-added arrays (entities, tenancies, …) are checked too.
CATALOG_CHECK = r'''#!/usr/bin/env python3
"""Validate this teka's catalog.json. Exit non-zero on any hard error."""
import json
import sys
from pathlib import Path

CORE_ARRAYS = ("documents", "open_items", "processing_log")


def main() -> int:
    path = Path(__file__).with_name("catalog.json")
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        print("catalog.json not found", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"catalog.json is not valid JSON: {exc}", file=sys.stderr)
        return 2

    errors = []
    meta = data.get("meta")
    if not isinstance(meta, dict) or "schema_version" not in meta:
        errors.append("meta.schema_version missing")

    counts = {}
    for key, value in data.items():
        if not isinstance(value, list) or not value:
            continue
        if not all(isinstance(item, dict) for item in value):
            continue
        ids = [item["id"] for item in value if "id" in item]
        if ids:
            dupes = {i for i in ids if ids.count(i) > 1}
            if dupes:
                errors.append(f"{key}[]: duplicate id(s): {sorted(dupes)}")
        counts[key] = len(value)

    for key in CORE_ARRAYS:
        data.setdefault(key, [])

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1

    summary = ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "empty"
    print(f"catalog OK: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
