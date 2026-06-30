"""Opt-in modules — the flexibility mechanism.

A teka is a thin spine (CLAUDE.md + intake/ + catalog.json + checker) plus the
modules it turns on. Modules compose; nobody pays for what they don't use; adding
a capability later is just switching one on and re-stamping or copying its pieces.

Each module contributes some of: directories, files, a CLAUDE.md section, repo-map
rows, extra ``catalog.json`` arrays, and whether it needs an IMAP folder.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Module:
    name: str
    summary: str
    dirs: list = field(default_factory=list)
    files: dict = field(default_factory=dict)           # relpath -> contents
    claude_section: str = ""
    repo_rows: list = field(default_factory=list)        # (path, description)
    catalog_arrays: list = field(default_factory=list)   # extra top-level [] arrays
    needs_imap: bool = False


MODULES: dict[str, Module] = {
    "email-intake": Module(
        name="email-intake",
        summary="IMAP label → intake/mail → correspondence/<thread>/",
        dirs=["intake/mail", "scripts/mail", "correspondence"],
        needs_imap=True,
        repo_rows=[
            ("scripts/mail/", "imap-extract config + sync state (`.env`, `state.json`); persistent — run it from here."),
            ("intake/mail/", "imap-extract drops one .md per new email here; drained on filing — safe to wipe & recreate."),
            ("correspondence/", "Filed email/letters in per-topic `correspondence/<thread>/` subfolders."),
        ],
        claude_section="""\
## Module: email-intake

New mail for this teka arrives via **imap-extract** (homebrew tap) reading one
IMAP label into `intake/mail/` as dated `.md` files (frontmatter + body, with a
sibling `… attachments/` dir). Config and sync state live in `scripts/mail/`
(`.env` + `state.json`, local secrets) — deliberately *outside* `intake/`, so
the drain folder stays disposable.

Pull once: `cd scripts/mail && imap-extract --once` (it reads `./.env`, writes its
`state.json` here, and drops mail into `intake/mail/` via `TARGET_DIR`). File during
the digest ritual into `correspondence/<thread>/` as `YYYY-MM-DD-HHMM_sender.md`;
route attachments to their category folder, not into correspondence. Catalog an
email *thread* as one record; a standalone document of record gets its own.

`intake/mail/` holds only un-filed items; it can be wiped and recreated freely.
Never keep anything of record there.
""",
    ),
    "docs-intake": Module(
        name="docs-intake",
        summary="manual document drop + OCR/convert pipeline",
        dirs=["intake"],
        repo_rows=[
            ("intake/_converted/", "Text extraction of dropped PDFs/images (regenerable, safe to delete)."),
        ],
        claude_section="""\
## Module: docs-intake

Drop scans/PDFs/photos into `intake/`. Normalise to text with the tap's convert
tool (textutil / pdftotext / tesseract / sips) into `intake/_converted/` so you
can read in one pass and dodge the PDF page-limit wall. File the originals into
their category folder during the digest ritual; never read-and-leave in intake/.
""",
    ),
    "github-source": Module(
        name="github-source",
        summary="pull issues/commits/deploys from a referenced repo (e.g. dogfooding)",
        dirs=["sources"],
        files={
            "sources/github.toml": """\
# What this teka watches in an external GitHub repo. lifeproj does not store the
# app's code — only pointers and pulled metadata.
repo = "owner/name"            # e.g. orlenko/naha
pull = ["issues", "commits"]   # what to mirror into sources/
since = ""                     # ISO date; blank = first run baselines
"""
        },
        repo_rows=[
            ("sources/", "Pulled metadata (issues/commits) from the referenced repo; observations link back to it."),
        ],
        claude_section="""\
## Module: github-source

This teka observes an external repo (see `sources/github.toml`) — typically to
dogfood your own app. Pull issues/commits into `sources/`, turn observations into
`catalog.json` items, and when something is worth acting on, *draft* an issue for
the app's tracker (Vlad files it). The app's code is NOT part of this teka.
""",
    ),
    "timeline": Module(
        name="timeline",
        summary="an explicit dated chronology (deadlines, events)",
        files={
            "timeline.md": """\
# Timeline

_Dated events for this teka. Add entries newest-last. Surface upcoming deadlines
in DASHBOARD.md._

| Date | Event | Source | Notes |
| ---- | ----- | ------ | ----- |
"""
        },
        repo_rows=[("timeline.md", "Explicit chronology + deadlines (the one place history is kept on purpose).")],
        claude_section="""\
## Module: timeline

Keep `timeline.md` as the explicit chronology — service dates, notices, hearings,
deadlines. Any hard deadline must also surface at the top of `DASHBOARD.md` and be
re-checked when asked. Compute deadlines from a cited rule + an anchor date; never
assert a deadline from memory.
""",
    ),
    "ledger": Module(
        name="ledger",
        summary="typed transactions that sum (rent, fees, expenses)",
        dirs=["ledger"],
        files={
            "ledger/README.md": "# Ledger\n\nTransactions that sum to current balances. Keep the running total in DASHBOARD.md.\n"
        },
        repo_rows=[("ledger/", "Typed transactions (rent/fees/expenses); balances roll up into DASHBOARD.md.")],
        claude_section="""\
## Module: ledger

Track money as typed transactions in `ledger/` (date, party, amount, kind). The
current balance is *current truth* — keep it in `DASHBOARD.md`, not derived ad hoc.
""",
    ),
    "chapters": Module(
        name="chapters",
        summary="finite episodes inside an ongoing teka (e.g. tenancies)",
        dirs=["chapters", "chapters/_past"],
        repo_rows=[
            ("chapters/", "One subfolder per {{CHAPTER_NOUN}}; exactly one is active."),
            ("chapters/_past/", "Closed {{CHAPTER_NOUN}}s, retained as record (deposit disputes, references)."),
        ],
        claude_section="""\
## Module: chapters ({{CHAPTER_NOUN}})

This teka is *ongoing* but holds *finite* episodes. Each {{CHAPTER_NOUN}} is a
subfolder under `chapters/` with its own documents, correspondence, and (if used)
ledger. Exactly one is the **current** {{CHAPTER_NOUN}} — its key facts live in
DASHBOARD.md as current truth. On close (e.g. move-out): finalise that chapter's
ledger and records, move it to `chapters/_past/`, and open a fresh one. Archiving
the *whole* teka is a different, heavier action (`lifeproj archive`).
""",
    ),
    "entities": Module(
        name="entities",
        summary="a table of comparable records you track/compare (candidates, units, vendors)",
        dirs=["entities"],
        catalog_arrays=["entities"],
        repo_rows=[("entities/", "One subfolder per tracked entity; comparable attributes live in catalog.entities[].")],
        claude_section="""\
## Module: entities

Some tekas track a *set of comparable things* (rental candidates, units, vendor
bids) rather than a stream of correspondence. Each gets a row in
`catalog.json` → `entities[]` (id + comparable attributes + a lifecycle `status`)
and a subfolder under `entities/`. DASHBOARD.md should render them as a comparison
table. Never delete a rejected entity — move it aside with the reason recorded, so
it isn't re-evaluated.
""",
    ),
    "osavul": Module(
        name="osavul",
        summary="publish an agenda slice to the cross-teka Osavul spool each digest",
        claude_section="""\
## Module: osavul (cross-teka agenda publishing)

This teka publishes a standard **agenda slice** so the Osavul chief-of-staff teka
can roll up outstanding work across every teka — without any teka reading another's
files. The rendezvous is a shared **spool** in the sandbox grant set:

```
~/.local/share/osavul/
  inbox/   <teka>.agenda.json   this teka WRITES its slice; Osavul READS all
  outbox/  <teka>.intake.json   Osavul WRITES routed items; this teka drains (v2)
  state/                        Osavul's own merged output
```

**Publish last, every digest.** As the final step of the digest ritual — after
`open_items[]` is reconciled and `DASHBOARD.md` regenerated — run:

```
lifeproj publish
```

It projects `open_items[]` into the agenda-slice schema (see *Open items* above,
and lifeproj `docs/DESIGN.md`) and writes `inbox/<teka>.agenda.json` atomically.
If the spool isn't provisioned yet it no-ops with a one-line hint — it never
crashes the digest.

**No cmirror key needed.** The spool is *self-registering*: a teka enters Osavul's
world the first time it publishes. Do not add a registry entry for this.

*(v2)* `lifeproj drain` will file items Osavul routes back via `outbox/` into this
teka's `intake/`. It exists as a documented stub today.
""",
    ),
}

# Domain overlays: orthogonal guardrails layered on top of the skeleton.
OVERLAYS: dict[str, str] = {
    "legal": """\
## Overlay: legal

Not legal advice — organise, summarise, transcribe, and compute *stated* deadlines
only; defer rights/strategy to counsel. Treat evidence as immutable. Transcribe
verbatim ([sic]/[illegible]); verify against originals. Privilege caution:
AI-generated analysis may be discoverable — keep candid strategy out of synced
files. Guard personal data of all parties (and any minors).
""",
    "tenancy": """\
## Overlay: tenancy

Cite the governing residential-tenancy law/regulation for any notice period,
rent-increase limit, or deposit rule — never assert them from memory. Notices have
hard service-and-timing requirements; compute from the rule + the served date and
surface the deadline in DASHBOARD.md. Keep tenant personal data discreet and local.
""",
    "condo": """\
## Overlay: condo / strata

Cite the governing strata/condo statute, regulation, and registered bylaw section
for any threshold, vote, fee, or deadline — never from memory. If a dispute is
live, apply the legal overlay's privilege caution to candid strategy.
""",
    "product": """\
## Overlay: product (dogfooding)

The aim is to improve the app by living in it. Log friction and ideas as catalog
items; convert the worthwhile ones into drafted issues for Vlad to file. Keep your
own usage data local; share only the distilled, non-sensitive findings.
""",
}


def resolve(names: list[str]) -> list[Module]:
    out = []
    for n in names:
        if n not in MODULES:
            raise KeyError(f"unknown module {n!r}; known: {', '.join(sorted(MODULES))}")
        out.append(MODULES[n])
    return out
