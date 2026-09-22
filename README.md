# lifeproj

A thin orchestrator for **tekas** — local, agent-maintained life-admin projects
with encrypted backups (a legal matter, a tax year, a rental property, a condo
board, dogfooding your own app). Codex and Claude Code are both first-class.

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
| **Durability + portability** | The encrypted mirror (only ciphertext leaves) | cmirror → `<root>/<name>` (see `lifeproj root`) → Google Drive |
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

## The starter

Run `lifeproj` with no arguments on a terminal and it opens on your tekas:

```
 lifeproj 0.12.0 · 3 tekas · backups → ~/GoogleDrive/teka-backups

 › New teka       scaffold one from the spine + modules
   Overview       intake, backup age and mail label, per teka
   Brief          one merged list of what needs you today
   Equip all      re-sync the spine skills into every teka
   Backup root    ~/GoogleDrive/teka-backups
   Teka home      ~/tekas
   Restore all    2 registered tekas with no local copy here

   TEKA           what is waiting, and how old the backup is
   tenants-123main  intake 4 · backup 9h ago · Personal/123Main
   taxes-2025       intake clear · backup 2d ago
   borey            archived

   Name it, pick the modules, and Enter stamps the teka: spine, module
   folders, skills, and a cmirror entry so it gets backed up.

 Enter open · ↑↓ move · n new teka · esc quit
```

Enter on a teka gives what you can run on it (publish, drain, equip, archive or
restore); **New teka** opens a form where each module row carries its own
one-line summary, so you pick modules by what they do rather than by name. A
teka the registry knows but this machine has no copy of opens on **Restore**,
and **Restore all** appears while any is in that state — which is what a new
machine looks like.

Every screen composes **one ordinary `lifeproj` command**, shows it as it
changes, and on Enter runs exactly that:

```
 $ lifeproj new tenants-123main --domain tenancy --intake email,docs --artifact ledger,chapters
```

So the menu teaches the CLI instead of hiding it, and it can start nothing the
command line cannot. Keys: `↑↓` move, `←→` choose, `space` toggles a module or
edits a text row, `m` folds out the rest (IMAP label, chapter noun, working dir,
registry, dry run), `esc` backs out, `q` quits. What kind of teka you tend to
make is remembered; the name never is. Off a terminal — a pipe, a hook, a script
— bare `lifeproj` still just prints its usage.

## Quickstart

```sh
# Once: set the base folder for encrypted backups (a synced Google Drive dir).
# Every new teka's encrypted_dir defaults to <root>/<name> — no per-teka paths.
lifeproj root ~/GoogleDrive/teka-backups

# Once: set the local folder tekas live in (default ~/personal when unset).
lifeproj home ~/tekas

# Scaffold a property teka: email + document intake, a rent ledger, and tenancies
# as finite "chapters" inside an ongoing project.
lifeproj new tenants-123main \
  --domain tenancy \
  --intake email,docs --artifact ledger,chapters --chapter-noun tenancy \
  --imap-folder Labels/Tenants-123Main \
  --summary "Tenancy admin for 123 Main St."

# See every teka at a glance: queued intake, last-backup age, mail label.
lifeproj overview

# The Monday-morning question, once, from anywhere: what needs me today across
# every teka? Reads the published agenda slices; never enters a teka.
lifeproj brief --days 7

# Retire a finished teka from the nightly sync (keeps the encrypted Drive backup,
# frees local disk). Reverse with `restore`.
lifeproj archive tax-2025 --purge-local
lifeproj restore tax-2025

# Retrofit Codex guidance + both agents' spine skills into existing tekas.
# Idempotent; keeps customized skills unless --force and never replaces manuals.
lifeproj equip

# If the backup location moved: check every teka's encrypted_dir against the
# root, and repoint the ones whose dir no longer exists on disk.
lifeproj root --rehome

# New machine or new home folder: repoint every teka's working_dir that isn't on
# disk here to <home>/<name>, then `cmirror pull --all` fills them in.
lifeproj home ~/tekas --rehome

# Then bring every missing teka into a working state: create the folder, pull
# from Drive, refresh spine skills, and rewrite the old machine's paths in code
# and config (prose is reported, not rewritten).
lifeproj restore --all --old-home /Users/old/personal
```

`lifeproj new` stamps the folder, renders a shared `CLAUDE.md` operating manual,
a Codex `AGENTS.md` bridge, a validated `catalog.json`, and the chosen modules.
It registers a `[projects.<name>]` block in cmirror's config and renders
`scripts/mail/.env` from your shared IMAP secrets + the one varying label. Then
you open the folder in Codex or Claude Code and work it.

## Modules (opt-in)

A teka is a thin spine (`AGENTS.md` + `CLAUDE.md` + `intake/` + `catalog.json` +
`catalog_check.py` + the `humanize` skill in both `.agents/skills/` and
`.claude/skills/`, so outgoing drafts don't read as AI-generated) plus the
modules it turns on. The operating manual remains single-sourced in `CLAUDE.md`;
`AGENTS.md` tells Codex to load it, so the two agents cannot drift apart.

| Module | Turns on |
| --- | --- |
| `email-intake` | imap-extract label → `intake/mail/` → `correspondence/<thread>/` |
| `docs-intake` | manual drop + OCR/convert pipeline |
| `github-source` | pull issues/commits from a referenced repo (dogfooding) |
| `timeline` | an explicit dated chronology + deadlines |
| `ledger` | typed transactions that sum (rent, fees) |
| `chapters` | finite episodes inside an ongoing teka (e.g. tenancies) |
| `entities` | a table of comparable records you track/compare |
| `osavul` | (compat no-op) [Osavul](docs/DESIGN.md#10-osavul-integration-cross-teka-roll-up) agenda publishing is spine since v0.8 — every teka carries it |

Domain overlays (`legal`, `tenancy`, `condo`, `product`) add the right guardrails
on top — privilege caution, governing-law citations, etc.

## Cross-teka roll-up (Osavul)

Every teka keeps a strict, current `open_items[]` task list (enforced by
`catalog_check.py`) and runs `lifeproj publish` as the last step of each digest,
projecting that list into a standard **agenda slice** on a shared spool so a
chief-of-staff teka can answer "what needs me today, *everywhere*?" — without any
teka reading another's files. The publishing contract is part of the spine manual,
so a teka knows the transport (the spool, never the a2a relay) from birth;
`lifeproj equip` retrofits it into older manuals. `lifeproj drain` is the return
channel for completion signals (the routed-capture channel is still a stub).

**`lifeproj brief`** is the reading end of the same contract: one merged list of
every teka's open items, bucketed by urgency, from any directory. It is a pure
reader — no teka is entered and no teka's scripts are run — and it flags what it
can't vouch for: slices older than a week, tekas that never published, and
completions still waiting to be drained. The contract lives in
**[docs/DESIGN.md](docs/DESIGN.md#10-osavul-integration-cross-teka-roll-up)**.

## Privacy posture

Everything runs in local Codex or Claude Code sessions. Outside content included
in the active model session, the only off-machine copy is the **encrypted**
cmirror backup. lifeproj never writes a key or passphrase — the age identity
stays in cmirror's own config, outside every teka.

## Status

v0.12 — bare `lifeproj` opens an interactive starter: your tekas, what can be
run on each, and a New-teka form that names what every module does. It composes
ordinary commands and runs them, so the CLI stays the only surface. v0.11 —
a configurable teka home (`lifeproj home`) beside the backup root, and
`lifeproj restore --all [--old-home]` to bring a whole cabinet onto a new
machine. Also: `lifeproj brief`, one cross-teka list of what needs you, read
from the published slices; every teka carries
the Osavul publishing contract from birth (and `equip` retrofits it); fresh and
existing tekas support Codex and Claude Code; `new`, `equip`, `overview`,
`brief`, `archive`, `restore`, `publish`, the starter, and completion draining
are covered by tests. Generic intake/convert tools live in the homebrew tap and are called,
not vendored here.

MIT licensed.
