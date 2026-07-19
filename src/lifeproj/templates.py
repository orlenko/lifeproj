"""Embedded teka templates.

Templates use ``{{TOKEN}}`` placeholders rendered by :func:`render` (a plain
string replace, so literal ``{`` / ``}`` in file bodies are safe). Keeping the
templates as Python constants makes the tool dependency-free at runtime and easy
to read — a teka is meant to be edited after it's stamped, not driven by a
hidden template engine.
"""

from __future__ import annotations

from importlib import resources


def render(text: str, **tokens: str) -> str:
    for key, value in tokens.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def data(relpath: str) -> str:
    """Read a packaged data file (``src/lifeproj/data/``), copied verbatim into
    tekas — no ``{{TOKEN}}`` rendering, so bodies may contain anything."""
    node = resources.files("lifeproj").joinpath("data")
    for part in relpath.split("/"):
        node = node.joinpath(part)
    return node.read_text()


AGENTS_BRIDGE = """\
# Codex instructions

`CLAUDE.md` is this teka's shared operating manual. Read it completely before
acting and follow it as repository instructions. The filename remains
Claude-specific so existing tekas and Claude Code sessions keep working; its
rules apply equally in Codex.

- In Codex, use repo skills from `.agents/skills/`. Claude Code carries the same
  skills in `.claude/skills/`.
- Keep teka-specific operating guidance in `CLAUDE.md`; keep this file as the
  stable Codex bridge so the two agents cannot acquire divergent manuals.
"""


CLAUDE_HEADER = """\
# {{NAME}}

> Shared operating manual for this teka. Claude Code loads it directly; Codex
> is directed to it by `AGENTS.md`. Read it fully before acting. A *teka* is a
> local, agent-maintained life-admin project with encrypted backups (see
> lifeproj/docs/DESIGN.md).

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
- **The digest ritual** (run it whenever new material lands): `lifeproj drain`
  (apply Osavul closures, see below) → drain `intake/` → for each item read →
  classify → rename to `YYYY-MM-DD_slug` → move into the right folder → record
  it in `catalog.json` → append a `processing_log[]` entry → **reconcile
  `open_items[]`** (see below) → regenerate `DASHBOARD.md` → leave `intake/`
  empty → `lifeproj publish` (agenda slice, see below). Never delete originals.
- **Monitors flag, humans act.** Intake/watchers only surface new material. Never
  send a message, sign, pay, or commit anything outbound without Vlad's explicit
  approval. Drafts wait in place for review.
- **Drafts sound human.** Write every outgoing draft (email, letter, document)
  with the `humanize` skill (`.agents/skills/humanize/` in Codex,
  `.claude/skills/humanize/` in Claude Code): no AI tells — em-dash tics,
  "not X, but Y", rule-of-three, mechanical boldface. Match Vlad's own voice
  from prior outgoing mail in `correspondence/` where it exists.
- **Privacy posture.** Teka files stay local; off-machine durability is the
  *encrypted* cmirror backup. Do not paste teka contents into web tools or
  unrelated external services.
- **Validate state.** Run `python3 catalog_check.py` after editing `catalog.json`.

## Open items — the task schema (kept current, every digest)

`open_items[]` is this teka's live to-do list and the basis of any cross-teka
roll-up. Each item is an object:

- `id` — stable, teka-prefixed, **never reused** (e.g. `{{NAME}}-2026-001`)
- `title` — one line
- `status` — `open | waiting | blocked | done`
- `priority` — `high | normal | low`
- `due` *(ISO date `YYYY-MM-DD`)* **XOR** `no_deadline: true` — exactly one, so
  nothing is ever silently dateless
- `waiting_on` — free text, **required** when status is `waiting` or `blocked`
- `tags` *(optional list)* · `link` *(optional, relative path within this teka)*

**Reconcile every digest** (right after filing intake): confirm each `status`
still reflects reality; give every item a real `due` or an explicit
`no_deadline`; record completed work in append-only `processing_log[]` and drop
it from `open_items[]` once it has shown as `done` once. Then regenerate
`DASHBOARD.md` (Overdue · Due soon ≤7d · No deadline · everything else) and run
`python3 catalog_check.py` — it enforces this schema.
"""

# Spine section: the Osavul publishing contract. Every teka carries it from
# birth so no teka improvises a transport (the failure mode this prevents: a
# fresh teka trying to hand its open items to Osavul over the a2a relay).
# Also inserted into legacy manuals by `lifeproj equip`.
CLAUDE_OSAVUL = """\
## Publishing to Osavul (cross-teka agenda)

Every teka publishes a standard **agenda slice** so Osavul, the chief-of-staff
teka, can roll up outstanding work across the fleet — without any teka reading
another's files. The transport is the shared **spool**, and only the spool: the
a2a relay carries *asks* ("confirm the wire before Monday"), never the standing
list.

```
~/.local/share/osavul/            (override: $OSAVUL_SPOOL)
  inbox/   <teka>.agenda.json     this teka WRITES its slice; Osavul READS all
  outbox/  <teka>.intake.json     Osavul WRITES completions; this teka drains
```

- **Publish last, every digest.** After `open_items[]` is reconciled and
  `DASHBOARD.md` regenerated, run `lifeproj publish`. It projects `open_items[]`
  into the frozen agenda-slice schema (the *Open items* schema above; contract
  reference: lifeproj `docs/DESIGN.md` §10) and writes `inbox/<teka>.agenda.json`
  atomically. Re-publish whenever `open_items[]` changes.
- **Self-registering.** The slice file appearing in `inbox/` IS the
  registration — no announcement, no registry entry.
- **Ungranted spool = quiet no-op.** If this session's sandbox doesn't grant the
  spool, `lifeproj publish` prints a one-line hint and exits 0; it never breaks
  the digest. Ask Vlad to add the `~/.local/share/osavul` grant to the session
  profile.
- **Drain first.** Near the start of each digest, run `lifeproj drain`: it
  applies completions Osavul wrote to `outbox/<teka>.intake.json` (items checked
  off upstream, e.g. in Google Tasks) by moving those `open_items[]` to
  `processing_log[]` and ACKing the outbox. Reconcile and publish *after*, so
  the republished slice reflects the closures.
- **Discretion is built in; silence is legal.** A sensitive item can ship a
  sanitized `slice_title`, or `redact: true` for a generic title with
  `waiting_on` masked. A teka may also legitimately never publish. Both are by
  design, not errors.
"""

CLAUDE_FOOTER = """\
## Repository map

| Path | What lives here |
| ---- | --------------- |
| `CLAUDE.md` | Shared operating manual (loaded directly by Claude Code). |
| `AGENTS.md` | Codex bridge to the shared operating manual. |
| `README.md` | Human "start here" overview. |
| `DASHBOARD.md` | At-a-glance current truth, regenerated from `catalog.json`. |
| `catalog.json` | Structured single source of truth (documents / open items / log). |
| `catalog_check.py` | Validator for `catalog.json`. |
| `.agents/skills/` | Codex copies of teka skills (`humanize` — outgoing drafts avoid AI tells). |
| `.claude/skills/` | Claude Code copies of the same teka skills. |
| `intake/` | Transient dropzone — drained after filing (presence == unprocessed). |
{{REPO_MAP_ROWS}}

## Notes

- Bespoke scripts for *this* teka live in `scripts/`. Generic, reusable tools
  (imap-extract, OCR/convert, eml→md) come from the homebrew tap and are called,
  not copied.
- `CLAUDE.md` is the shared source of truth for *how* to work this teka;
  `AGENTS.md` deliberately stays a small bridge. Add a row above whenever you
  add a folder.
"""

README_TMPL = """\
# {{NAME}}

{{SUMMARY}}

**Start here:** open this folder in Codex or Claude Code. `CLAUDE.md` is the
shared operating manual (`AGENTS.md` directs Codex to it); `DASHBOARD.md` is the
current-state view.

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

_Regenerate from `open_items[]` each digest: the three buckets first, then the rest._

### ⏰ Overdue

_None._

### 📅 Due soon (≤7 days)

_None._

### 🗓 No deadline

_None._

### Everything else

_None yet._

## Where things live

See `CLAUDE.md` → Repository map (`AGENTS.md` directs Codex to the manual).
"""

# A small, dependency-free validator copied INTO each teka (thick teka, thin
# centre). Validates the core spine and any extra ``*[]`` arrays of objects with
# an ``id``, so module-added arrays (entities, tenancies, …) are checked too.
CATALOG_CHECK = r'''#!/usr/bin/env python3
"""Validate this teka's catalog.json. Exit non-zero on any hard error.

schema_version >= 2 additionally enforces the strict open_items[] task schema
(the Osavul agenda contract). schema_version 1 validates under the legacy rules,
so an un-migrated teka keeps passing until it is migrated.
"""
import json
import sys
from datetime import date
from pathlib import Path

CORE_ARRAYS = ("documents", "open_items", "processing_log")
STATUSES = ("open", "waiting", "blocked", "done")
PRIORITIES = ("high", "normal", "low")


def check_open_items(items, processing_log):
    """Strict task schema — keep in sync with lifeproj's osavul.validate_open_items."""
    errors = []
    seen = set()
    closed = {e["id"] for e in processing_log if isinstance(e, dict) and "id" in e}
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
    version = 0
    if not isinstance(meta, dict) or "schema_version" not in meta:
        errors.append("meta.schema_version missing")
    else:
        version = meta.get("schema_version", 0)

    counts = {}
    for key, value in data.items():
        if not isinstance(value, list) or not value:
            continue
        if not all(isinstance(item, dict) for item in value):
            continue
        # open_items dupes are reported precisely by the strict check below.
        if not (key == "open_items" and isinstance(version, int) and version >= 2):
            ids = [item["id"] for item in value if "id" in item]
            dupes = {i for i in ids if ids.count(i) > 1}
            if dupes:
                errors.append(f"{key}[]: duplicate id(s): {sorted(dupes)}")
        counts[key] = len(value)

    for key in CORE_ARRAYS:
        data.setdefault(key, [])

    if isinstance(version, int) and version >= 2:
        errors.extend(check_open_items(data.get("open_items", []),
                                       data.get("processing_log", [])))
    else:
        print("note: schema_version < 2 — strict open_items checks skipped "
              "(legacy teka; see lifeproj docs/DESIGN.md to migrate).", file=sys.stderr)

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
