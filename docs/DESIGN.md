# lifeproj design

The model behind tekas and the reasoning for the choices. This is the spec; the
code is thin enough to read after.

## 1. The pattern

Several folders under `~/personal` are long-running, correspondence- and
document-heavy threads of life-admin co-maintained with Codex or Claude Code: a
legal matter, a tax year, a strata/condo board, rental properties, dogfooding an
app. They are not N unrelated projects — they are **one system instantiated N
times**, and the instance is a **teka** (тека / θήκη / -thèque: a curated folder
of material on one subject). `~/personal` is the cabinet of tekas.

Each teka tangles two things that this framework pulls apart:

- **Invariant plumbing & convention** — intake, backup, the state-keeping ritual,
  the directory spine. Identical everywhere. *Tooled.*
- **Per-teka content & policy** — the parties, facts, deadlines, tone, bespoke
  logic. Different everywhere. *Freeform Markdown + per-teka scripts.*

## 2. The substrate: git repo *or* encrypted blob? Both — different layers

A common confusion. The answer is layered:

- **A teka's living content = a plain local folder.** Plaintext, the source of
  truth, on this machine only.
- **Durability + portability + the "seed from Drive" = cmirror's encrypted
  mirror.** cmirror encrypts the folder to `gd-sync/<name>` (content-addressed age
  blobs + an encrypted manifest); Google Drive for Desktop ships those offsite.
  Only ciphertext ever leaves the machine.
- **The thing that *starts* a teka = a git repo — but it is the *kit* (this repo),
  not the teka.** You don't clone it as a project; you run it to stamp one out.

**GitHub never holds a teka's confidential content.** A private repo is still
plaintext on someone else's server — that breaks the privacy posture *and*
duplicates what cmirror already does better (encrypted **and** versioned, via its
keep-forever `_archive/`). So there is no per-teka GitHub remote, and **no local
git by default** — we track *current truth* (+ an explicit `timeline.md` where a
teka opts in), not change history.

Two distinct "seed" events people run together:

- **New teka** → seeded from the **kit template** (creation).
- **New machine** → seeded from **Drive** via `cmirror pull` (restore).

## 3. The spine + opt-in modules

Every teka has the same thin spine:

```
AGENTS.md          Codex bridge to the shared operating manual
CLAUDE.md          shared operating manual; Claude loads it directly
README.md          human "start here"
DASHBOARD.md       current truth, regenerated from catalog.json
catalog.json       structured single source of truth
catalog_check.py   validator (copied in — thick teka, thin centre)
.agents/skills/    Codex copies of spine skills
.claude/skills/    Claude Code copies of the same spine skills
intake/            transient dropzone, drained after filing
scripts/           bespoke per-teka automation
```

The operating manual is deliberately single-sourced in `CLAUDE.md` for
backward compatibility with existing tekas. Codex automatically loads
`AGENTS.md`, whose stable bridge tells it to read and follow the shared manual.
This keeps both agents first-class without maintaining two copies of evolving
teka policy.

The `humanize` skill (adapted from [blader/humanizer](https://github.com/blader/humanizer),
MIT) rides in every teka because every teka drafts outgoing text — emails,
letters, filings — and none of it should read as AI-generated. `CLAUDE.md`'s
working rules bind drafting to it, and it voice-matches Vlad's prior outgoing
mail in `correspondence/` when the teka has any. One packaged source is copied
to both `.agents/skills/` and `.claude/skills/`. Tekas stamped before either
agent asset existed are retrofitted with `lifeproj equip` (registry-driven like
`drain --all`; keeps customized skills unless `--force`). Equip installs a
missing `AGENTS.md` bridge but never overwrites living instruction files. It
gives `CLAUDE.md` the lightest possible touch: the drafting bullet is appended
to the standard working-rules section when that anchor survives, and printed
for manual pasting when the manual has been customized past recognition.

Everything else is an **opt-in module** (`email-intake`, `docs-intake`,
`github-source`, `timeline`, `ledger`, `chapters`, `entities`). Modules compose;
nobody pays for what they don't use; adding a capability later is switching one on.
A module contributes some of: directories, files, a shared-manual section,
repo-map rows, extra `catalog.json` arrays, and whether it needs an IMAP folder.

**Domain overlays** (`legal`, `tenancy`, `condo`, `product`) are orthogonal: they
layer guardrails (privilege caution, governing-law citations, dogfood posture) on
top of the skeleton without changing it.

### The state record is the heart

The proven, drift-resistant pattern (from the strata teka) is the standard:
`catalog.json` (`meta` + `documents[]` + `open_items[]` + append-only
`processing_log[]`) regenerating `DASHBOARD.md`, guarded by `catalog_check.py`. The
**digest ritual** is the heartbeat: drain `intake/` → read → classify → rename →
file → record in catalog → append to the log → regen dashboard → leave intake
empty. Because state is kept current, a session never re-reads the whole teka to
know where things stand. That is the main time-saver.

## 4. Two axes, not one "kind"

A teka's shape is better described by two independent axes than by a single domain
enum (a document-pile legal matter and an email-driven one share nothing but the
domain word):

- **Intake** (selects the plumbing): `email-thread` · `document-pile` · `marketplace/entity`.
- **Artifact** (selects the state schema): `timeline` · `ledger` · `catalog` · `candidate-table`.
- **+ a lifecycle bit**: `ongoing` (no end) vs `finite` (completes on a deliverable/decision).

These are independent: email intake pairs with both a timeline (legal) and a
catalog (strata). The modules above are the concrete realisation of the axes;
`--intake`/`--artifact` are sugar over `--module`.

### Chapters: finite episodes inside an ongoing teka

Lifecycle isn't binary at the teka level. A rental **property** is *ongoing*, but
each **tenancy** is a *finite* chapter inside it. The `chapters` module models this:
`chapters/<name>/` with exactly one active chapter (its key facts are current truth
in the dashboard) and `chapters/_past/` for closed ones, kept as record. Closing a
chapter (move-out) is light; archiving the whole teka is heavy (§7). Condo boards
can reuse chapters for per-dispute or per-term episodes.

## 5. The registry is cmirror's config — not a new `matter.toml`

cmirror's `~/.config/cmirror/config.toml` already enumerates every teka by name
with `working_dir` + `encrypted_dir`, and already drives backups across all
projects. It **is** the registry. lifeproj makes that canonical instead of
competing with it:

- A **live** teka is `[projects.<name>]`; an **archived** teka is `[archived.<name>]`.
  cmirror reads only `[projects.*]`, so archived tekas are skipped by backup yet
  still tracked by lifeproj (which reads both).
- The single varying intake value, `imap_folder`, rides **inside** the project
  table. cmirror ignores unknown keys; the intake shim reads it. (Verified against
  cmirror's config loader.)
- lifeproj's own settings ride in a `[lifeproj]` table, ignored by cmirror the
  same way `[archived]` is. Today: `encrypted_root` — the base folder new tekas
  back up under (`encrypted_dir` defaults to `<root>/<name>`) — and `teka_home`,
  the local folder new tekas live in (`working_dir` defaults to `<home>/<name>`,
  legacy `~/personal/<name>` when unset; `lifeproj home <path>`, with the same
  `--rehome` for working dirs missing on disk, archived tekas included so a
  later restore lands in the new home). Set it once with
  `lifeproj root <path>`; `lifeproj root --rehome` repoints tekas whose
  `encrypted_dir` vanished from disk (a dir that *exists* holds real ciphertext
  and is never auto-moved). This replaced the hardcoded `~/personal/gd-sync/`
  default after two tekas were scaffolded against a location that no longer
  existed and the failure only surfaced at `cmirror backup` time — `lifeproj new`
  now also warns at scaffold time when the target's parent is missing.
- **No keys, ever.** The example config is "paths only, never a key or passphrase";
  the age identity lives in cmirror's `identity_file`, outside every teka. A
  per-teka `matter.toml` with an inline `key="age:..."` — as an early draft
  proposed — was rejected: it both duplicates cmirror and violates that model.

cmirror stays **machine-wide**; `imap-extract` stays **per-directory** (different
tekas may use different IMAP accounts/servers). lifeproj respects that split rather
than unifying it.

## 6. The tooling split: tap ↔ lifeproj ↔ teka

Three tiers, by reusability. Litmus test: *would a stranger find it useful with no
knowledge of my tekas?*

- **Generic, publishable tools → homebrew tap** (the sidekick): `imap-extract`,
  the eml→md converter, the OCR/convert pipeline. `brew`-installable, versioned,
  domain-agnostic. Every teka *calls* these.
- **Orchestrator → lifeproj** (this repo): knows about *tekas* and the *registry* —
  `new`, `archive`, `restore`, `overview`, templates, conventions. It glues the tap
  tools + cmirror together; it does not reimplement them.
- **Bespoke logic → stays in the teka's `scripts/`**: irreducible per-teka code
  (a tuned OCR pipeline, a hand-built FX reconciliation, a subject-routing table).
  Generic *mechanism* may graduate to the tap and read a per-teka config; the
  config stays local.

### The starter is a view over the CLI (v0.12)

`lifeproj` with no arguments on a terminal opens a menu: the registered tekas,
what can be run on one, and a form for a new one. It is a *fourth* thing only in
appearance — every screen composes one ordinary command line, shows it as it
changes, and runs exactly that. Nothing is startable from the menu that is not
startable from the shell, so there is one surface to test, document and keep
honest, and the menu doubles as the discovery path for what the flags accept
(each module row carries that module's own summary — `--module` otherwise
requires knowing the name already). The remembered state is the *shape* of teka
you tend to make, never a teka's own details.

## 7. Lifecycle, end to end

1. **Create** — `lifeproj new <name> --intake … --artifact …` stamps the spine +
   modules, registers `[projects.<name>]`, renders `scripts/mail/.env`.
2. **Wire intake** — create the IMAP label; for email tekas run `imap-extract
   --once` (or on a schedule). For dogfooding, point `sources/github.toml` at the
   repo.
3. **Daily ops** — open the folder in Codex or Claude Code → read the shared
   `CLAUDE.md` manual (Codex is directed there by `AGENTS.md`) → run the digest
   ritual → draft outbound (you approve). `cmirror backup` runs nightly via
   launchd.
4. **Add things** — turn on a module or just add a folder/script/array + a row in
   the shared manual's repo-map. No central change unless it affects
   backup/intake.
5. **Archive** — `lifeproj archive <name>` runs a final `cmirror backup` +
   `verify`, moves the table to `[archived.*]` (backup stops), and with
   `--purge-local` deletes the local plaintext after verify. The encrypted blob
   stays in Drive; set `gd-sync/<name>` to Drive "online-only" to free the local
   ciphertext too. `lifeproj restore <name>` reverses it (`cmirror pull`).
6. **Move machines** — install the tools; **hand-carry the age identity** (the one
   true secret); restore `~/.config/cmirror/config.toml` + the shared IMAP secrets;
   on a machine with a different home or Drive path, `lifeproj home <path> --rehome`
   and `lifeproj root <path> --rehome` repoint the registry; `lifeproj restore
   --all --old-home <old teka home>` reconstitutes every teka from Drive
   ciphertext (mkdir + `cmirror pull` + `equip`), rewrites the old machine's
   absolute paths in code and config, and lists the ones left in prose;
   re-baseline the imap-extract cursors.

**Bootstrap chicken-and-egg:** the *only* thing you must move by hand is the age
identity. Everything else — config, secrets, all teka content — can itself sit as a
tiny cmirror-encrypted bootstrap blob in Drive, because once the identity is in
place you can decrypt it. One secret to guard; everything else self-restoring.

## 8. Privacy posture (firm)

Work happens in local Codex or Claude Code sessions, not cloud-hosted workspaces.
The accepted interactive exposure ceiling is content included in the active
model session (OpenAI or Anthropic). TypeSafe's Jev API (`api.typesafe.ai`) sits
under the same ceiling: teka scripts may send it task descriptions and raw teka
content (an email body, a document excerpt) to get typed judgments back — model
routing (`lifeproj route`), filing, priority, duplicate checks. It is a model
endpoint called by our own code, the same kind of exposure as the session
itself. Outside those, the only off-machine copy is the **encrypted** age
backup. Raw teka contents are never pasted into web tools or unrelated external
services.

## 9. Naming

- **teka** — each project instance (romanised тека / θήκη; "a curated folder on one
  subject"). The CLI is `lifeproj`; `git` manages repos, `lifeproj` manages tekas.
- Avoid the collisions on disk: `manifest` (an OCR page-index in one teka),
  `handoff` (a raw-input dump in another), `catalog`/`status` (already meaning
  specific things). "matter" was rejected as the universal noun — it is legal
  jargon that biases the skeleton toward timelines/privilege and doesn't fit a
  finite, transactional teka.

## 10. Osavul integration (cross-teka roll-up)

A teka cannot read another teka's folder — each runs in its own sandbox. **Osavul**
(a separate chief-of-staff teka) answers "what needs me today, *everywhere*?" by
reading a neutral **spool** that sits in every session's grant set. lifeproj owns
the *publish/drain mechanism*; the cross-teka roll-up itself is Osavul's job, not
lifeproj's.

**Two layers, deliberately split:**

- **CORE (every teka):** the strict `open_items[]` task schema + the digest
  discipline that keeps it current (`catalog_check.py` enforces it for
  `schema_version >= 2`; §3). Pure quality, no Osavul dependency.
- **Publishing (also every teka, since v0.8):** the publish-to-spool contract is
  part of the spine manual (`templates.CLAUDE_OSAVUL`), so a teka knows it from
  birth: the transport is the spool — never the a2a relay, which carries *asks*
  ("confirm the wire before Monday"), not the standing list — the trigger is the
  end of every digest (re-publish whenever `open_items[]` changes), the spool is
  self-registering, and discreet slices (`slice_title` / `redact`) or publishing
  nothing at all are legal by design. Before v0.8 this rode in an opt-in
  `osavul` module and a fresh teka scaffolded without it would improvise a
  transport; the module name survives as a compat no-op, and `lifeproj equip`
  inserts the section into pre-v0.8 manuals.

**The spool** — `~/.local/share/osavul/`, a sibling of the already-granted
`undrudge/` spool. The session's sandbox profile must grant it — one
`"$HOME/.local/share/osavul"` line — and that grant deliberately does **not**
live in either shared teka profile. It rides in dedicated extension profiles
reached through the `osavul-claude` and `osavul-codex` launcher aliases, so the
base `safe-claude` and `safe-codex` profiles stay minimal and the spool is
reachable only from sessions that actually publish. (Narrower still is possible:
grant just `inbox/` + `outbox/`, keeping Osavul's merged `state/` unreadable to
spokes.) A teka session started without the matching alias therefore hits the
no-op path by design — publish/drain print a one-line hint rather than failing
the digest — so an absent grant is a launch choice, not a misconfiguration to go
fix:

```
inbox/   <teka>.agenda.json   each teka WRITES its slice; Osavul READS all
outbox/  <teka>.intake.json   Osavul WRITES routed items; each teka READS+drains (v2)
state/                        Osavul's merged output
```

Self-registering: a teka enters Osavul's world the first time it publishes, so
there is **no new registry** — cmirror's config stays the registry for backup, the
spool is the registry for Osavul. (`OSAVUL_SPOOL` overrides the path for tests.)

**Why lifeproj, not the tap, not a copied-in script** (the §6 litmus): the
mechanism knows about tekas + the spool convention → useless to a stranger → *not*
the public homebrew tap. And the agenda slice is a shared interface Osavul reads
from every teka, so it must stay byte-identical → single-sourced as a `lifeproj`
subcommand, *not* copied-in-and-divergeable like `catalog_check.py` (whose per-teka
variation is legitimate; the slice's is not).

### `lifeproj publish` / `lifeproj drain`

- **`lifeproj publish`** — run from inside a teka. Reads `catalog.json`, validates
  `open_items[]`, projects them into the agenda slice, writes
  `inbox/<teka>.agenda.json` atomically (temp + `os.replace`). No-ops cleanly with a
  one-line grant hint if the spool isn't provisioned — safe as the last digest step.
- **`lifeproj drain`** — reads `outbox/<teka>.intake.json` and applies Osavul's
  `completions[]`: for each, moves the matching `open_item` to `processing_log`
  (`done`/`dropped`) and ACKs by removing the completion. Idempotent
  (unknown/already-closed skipped); atomic writes; **no republish** — the digest
  does that, and Osavul's roll-up then drops the item. The `items[]` routed-capture
  channel remains a documented stub.
- **`lifeproj drain --all`** — the deterministic fleet loop: drain + republish
  every registered teka (cmirror registry, so new tekas are picked up
  automatically), one line per teka (`--json` for a structured array). Republishes
  only tekas that drained something (no-op skips the republish to avoid slice
  churn). Resilient: one teka's failure is logged and the fleet continues; exit is
  non-zero if any errored. A registered dir with **no `catalog.json`** (an
  un-migrated/bare teka still being brought onto the standard) is a graceful
  **skip** (`status: skipped`), not an error — so the fleet stays green while
  migrations are in flight; `error` is reserved for a dir that *has* a
  `catalog.json` but fails to drain/publish. Runs **unsandboxed** from Osavul's cron — exactly like
  cmirror's backup, it reaches into every teka's folder, so it is never invoked
  from inside a sandboxed session. This is what takes the steady-state loop off the
  LLM: pull → `drain --all` → roll-up, all deterministic CLIs.

### `lifeproj brief` — the reading end (v0.10)

The published slices already answer "what needs me today, *everywhere*?" for a
human at a shell prompt, not just for Osavul. `lifeproj brief` walks the registry,
reads each active teka's slice, and prints one list bucketed by urgency (overdue /
today / next 7 days / later / no deadline / waiting on someone else), `--days N`
to narrow the horizon, `--teka` to filter, `--json` for machine use.

It is a **pure reader**: it never enters a teka, never runs a teka's own scripts,
never writes. That is the design choice worth stating, because the obvious
alternative — a script that `cd`s through a fixed list of teka repos and merges
the stdout of each one's bespoke rollup — hardcodes a fleet list that rots (§5's
lesson, the same one behind `lifeproj root`) and defines no contract between the
parts. The slice contract already exists; `brief` consumes it and nothing else.

Because a slice is a *cached* projection, the brief states what it cannot vouch
for rather than presenting stale work as current:

- a source `generated` more than 7 days ago is flagged (`slice is 11d old`);
- a registered teka that has never published is named, not silently omitted;
- undrained `outbox` completions are reported — shown items may already be closed;
- slices with no active teka (an archived teka's leftovers, another tool's
  publisher) are named and deliberately *not* briefed.

Degradation is deliberate. With no spool it prints a hint and exits 0 (the same
posture as `publish`). When cmirror's config is unreadable — a sandboxed teka
session that grants the spool but not the registry — it briefs every slice on the
spool and says so, so the command still works *inside* a teka, which is where the
question tends to get asked. The spine manual teaches it alongside publishing
(`templates.CLAUDE_BRIEF_BULLET`), and `equip` appends that one bullet to manuals
written before v0.10 without rewriting the section around it.

Osavul remains where judgment, routing and reconciliation happen; `brief` is the
mechanical glance you take before deciding whether to open Osavul at all.

### The contract (frozen) — agenda slice: `inbox/<teka>.agenda.json`

```json
{
  "teka": "cote",
  "lifecycle": "ongoing",               // ongoing | finite
  "active_chapter": null,               // single active chapter name, or null (back-compat)
  "active_chapters": [],                // authoritative active-chapter list (0/1/many)
  "generated": "2026-06-30T17:00:00Z",  // ISO8601 UTC; Osavul derives staleness
  "items": [
    {
      "id": "cote-2026-001",            // stable, teka-prefixed, never reused
      "title": "File AGM notice",
      "status": "open",                 // open | waiting | blocked | done
      "priority": "high",               // high | normal | low
      "due": "2026-07-05",              // ISO date, or null
      "no_deadline": false,             // true = intentionally dateless (null != forgotten)
      "tags": ["agm"],
      "waiting_on": null,               // free text; required when status = waiting|blocked
      "link": "DASHBOARD.md#cote-2026-001"  // relative path WITHIN the teka
    }
  ]
}
```

Rules: `id`, `title`, `status`, `priority` required; `due` XOR `no_deadline:true`
(nothing silently dateless); `waiting`/`blocked` require `waiting_on`; `done` items
appear once then drop from the next slice.

`active_chapters[]` is the authoritative active-chapter list (a teka can have 0, 1,
or many concurrently active chapters). `lifeproj publish` projects it from catalog
`meta.active_chapters` (falling back to `meta.current_chapters` for tekas mid-
migration); `active_chapter` (string|null) is retained for the single-chapter case
and auto-filled when exactly one chapter is active. Osavul reads `active_chapters[]`
when present and tolerates `active_chapter:null`.

**Slice-boundary projection.** `publish` is the single chokepoint into the shared
spool, so it normalises there. It **teka-prefixes** each slice `id` (`<teka>-<id>`,
idempotently — already-prefixed catalog ids are left alone) so ids are globally
unique in Osavul's merged view. And it **redacts** sensitive items at the boundary
while the catalog keeps the natural text: `slice_title` gives an explicit
replacement title, and `redact: true` emits a generic `title` (`[redacted]`) and
`waiting_on` (`[party]`). `tags` pass through unchanged (Osavul keys on functional
tags); the catalog's internal ids and `link` are untouched.

### The contract (frozen) — return channel (v2): `outbox/<teka>.intake.json`

```json
{
  "teka": "cote",
  "generated": "2026-06-30T17:00:00Z",
  "items": [                                        // routed captures → intake (v2 stub)
    {
      "title": "Call management co about parking",  // required
      "note": "from Todoist capture 2026-06-30",    // optional free text
      "due": "2026-07-10",                           // optional ISO date, or null
      "source": "todoist"                            // optional provenance tag
    }
  ],
  "completions": [                                   // close-outs applied by `lifeproj drain`
    {
      "id": "cote-012",                              // the teka's published SLICE id
      "action": "done",                              // done | dropped
      "at": "2026-06-30T18:00:00Z",                  // ISO8601
      "source": "google-tasks-via-osavul"            // provenance
    }
  ]
}
```

Osavul writes it. **`completions[]`** is live: `lifeproj drain` closes each referenced
`open_item` on the teka's next digest (see the `drain` bullet above). The completion
`id` is the published slice id (teka-prefixed); drain resolves it against the raw
catalog id or its `<teka>-` prefixed form, and Osavul appends completions
idempotently (never a duplicate id). **`items[]`** (routed captures → `intake/`) is
still a documented stub, to be wired in v2.

## 11. Non-goals (deliberately not built)

- **No `matter.toml`** — a third config surface duplicating cmirror + imap-extract,
  and a security regression. The registry is cmirror's config.
- **No imposed CAPS anatomy** (`TIMELINE/FACTS/CONTACTS/DEADLINES/...`) — it exists
  on no real teka and would regress the proven `catalog.json`. The spine + modules
  cover it.
- **No deadlines/contacts engine in config** — those are *content* (they live in
  the teka), not declarative fields.
- **No `status --all` daemon or registry service** — `lifeproj overview` is a thin
  read-only view over cmirror's project list; that's the whole control plane.
- **No unified `ingest`** that homogenises bespoke routing — per-teka filing logic
  is load-bearing and stays in the teka.
- **No web app, yet** — both end-state visions (a local "Life Projects" app vs the
  terminal) share this substrate; the app is a deferrable *local* skin over the
  same files + CLI + registry, added only if a real trigger appears. Build the
  convention now. The v0.12 starter is that skin in the terminal, over the same
  CLI: it composes commands, it does not become one.
