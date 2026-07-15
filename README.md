# lifeproj

A thin orchestrator for **tekas** — local, encrypted, Claude-maintained life-admin
projects (a legal matter, a tax year, a rental property, a condo board, dogfooding
your own app).

> *teka* (тека / θήκη / -thèque): a curated folder of material on one subject.
> Each teka is a plain local folder; `~/personal` is the cabinet of them.

lifeproj does **only** the cross-cutting plumbing — scaffold a teka, register it
for backup, archive/revive it, and show a read-only overview. The heavy lifting
stays where it belongs: encrypted backup in cmirror, email intake in
[`imap-extract`](https://github.com/orlenko/homebrew-tap), and each teka's own
bespoke logic inside the teka. **The tool is thin on purpose.**

## The shape

Three layers, deliberately separate:

| Layer | What it is | Where it lives |
| --- | --- | --- |
| **Living content** | A teka — plaintext, the source of truth | a local folder, on this machine only |
| **Durability + portability** | The encrypted mirror (only ciphertext leaves) | cmirror → `gd-sync/<name>` → Google Drive |
| **The kit** | This scaffolder + the conventions | this git repo (no secrets) |

GitHub never holds a teka's confidential content. A teka rides off-machine **only**
as age-encrypted blobs. (For a dogfooding teka, GitHub appears a third way — as an
external *source* the teka reads, e.g. an app's issue tracker — never as its home.)

See **[docs/DESIGN.md](docs/DESIGN.md)** for the full model.

## Install

```sh
uv tool install git+https://github.com/orlenko/lifeproj
# or, from a clone:
uv tool install .
```

## Quickstart

```sh
# Scaffold a property teka: email + document intake, a rent ledger, and tenancies
# as finite "chapters" inside an ongoing project.
lifeproj new tenants-123main \
  --domain tenancy \
  --intake email,docs --artifact ledger,chapters --chapter-noun tenancy \
  --imap-folder Labels/Tenants-123Main \
  --summary "Tenancy admin for 123 Main St."

# See every teka at a glance: queued intake, last-backup age, mail label.
lifeproj overview

# Retire a finished teka from the nightly sync (keeps the encrypted Drive backup,
# frees local disk). Reverse with `restore`.
lifeproj archive tax-2025 --purge-local
lifeproj restore tax-2025
```

`lifeproj new` stamps the folder, renders `CLAUDE.md` + a validated `catalog.json`
+ the chosen modules, registers a `[projects.<name>]` block in cmirror's config,
and renders `scripts/mail/.env` from your shared IMAP secrets + the one varying
label. Then you open the folder in Claude Code and work it.

## Modules (opt-in)

A teka is a thin spine (`CLAUDE.md` + `intake/` + `catalog.json` + `catalog_check.py`
+ the `humanize` skill in `.claude/skills/`, so outgoing drafts don't read as
AI-generated) plus the modules it turns on:

| Module | Turns on |
| --- | --- |
| `email-intake` | imap-extract label → `intake/mail/` → `correspondence/<thread>/` |
| `docs-intake` | manual drop + OCR/convert pipeline |
| `github-source` | pull issues/commits from a referenced repo (dogfooding) |
| `timeline` | an explicit dated chronology + deadlines |
| `ledger` | typed transactions that sum (rent, fees) |
| `chapters` | finite episodes inside an ongoing teka (e.g. tenancies) |
| `entities` | a table of comparable records you track/compare |
| `osavul` | publish an agenda slice to the cross-teka [Osavul](docs/DESIGN.md#10-osavul-integration-cross-teka-roll-up) spool each digest |

Domain overlays (`legal`, `tenancy`, `condo`, `product`) add the right guardrails
on top — privilege caution, governing-law citations, etc.

## Cross-teka roll-up (Osavul)

Every teka keeps a strict, current `open_items[]` task list (enforced by
`catalog_check.py`). A teka with the `osavul` module runs `lifeproj publish` as the
last step of each digest, projecting that list into a standard **agenda slice** on a
shared spool so a chief-of-staff teka can answer "what needs me today, *everywhere*?"
— without any teka reading another's files. `lifeproj drain` (v2 stub) is the return
channel. The contract lives in **[docs/DESIGN.md](docs/DESIGN.md#10-osavul-integration-cross-teka-roll-up)**.

## Privacy posture

Everything runs in **local** Claude Code sessions. The only thing that ever leaves
this machine is the **encrypted** cmirror backup. lifeproj never writes a key or
passphrase — the age identity stays in cmirror's own config, outside every teka.

## Status

v0.4 — `new`, `overview`, `archive`, `restore`, `publish` work and `drain` is a
documented stub; covered by tests. Generic intake/convert tools live in the
homebrew tap and are called, not vendored here.

MIT licensed.
