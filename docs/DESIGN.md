# lifeproj design

The model behind tekas and the reasoning for the choices. This is the spec; the
code is thin enough to read after.

## 1. The pattern

Several folders under `~/personal` are long-running, correspondence- and
document-heavy threads of life-admin co-maintained with Claude: a legal matter, a
tax year, a strata/condo board, rental properties, dogfooding an app. They are not
N unrelated projects — they are **one system instantiated N times**, and the
instance is a **teka** (тека / θήκη / -thèque: a curated folder of material on one
subject). `~/personal` is the cabinet of tekas.

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
CLAUDE.md          operating manual, loaded every session (the teka's brain)
README.md          human "start here"
DASHBOARD.md       current truth, regenerated from catalog.json
catalog.json       structured single source of truth
catalog_check.py   validator (copied in — thick teka, thin centre)
intake/            transient dropzone, drained after filing
scripts/           bespoke per-teka automation
```

Everything else is an **opt-in module** (`email-intake`, `docs-intake`,
`github-source`, `timeline`, `ledger`, `chapters`, `entities`). Modules compose;
nobody pays for what they don't use; adding a capability later is switching one on.
A module contributes some of: directories, files, a `CLAUDE.md` section, repo-map
rows, extra `catalog.json` arrays, and whether it needs an IMAP folder.

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

## 7. Lifecycle, end to end

1. **Create** — `lifeproj new <name> --intake … --artifact …` stamps the spine +
   modules, registers `[projects.<name>]`, renders `intake/mail/.env`.
2. **Wire intake** — create the IMAP label; for email tekas run `imap-extract
   --once` (or on a schedule). For dogfooding, point `sources/github.toml` at the
   repo.
3. **Daily ops** — open the folder in Claude Code → read `CLAUDE.md` → run the
   digest ritual → draft outbound (you approve). `cmirror backup` runs nightly via
   launchd.
4. **Add things** — turn on a module or just add a folder/script/array + a row in
   `CLAUDE.md`'s repo-map. No central change unless it affects backup/intake.
5. **Archive** — `lifeproj archive <name>` runs a final `cmirror backup` +
   `verify`, moves the table to `[archived.*]` (backup stops), and with
   `--purge-local` deletes the local plaintext after verify. The encrypted blob
   stays in Drive; set `gd-sync/<name>` to Drive "online-only" to free the local
   ciphertext too. `lifeproj restore <name>` reverses it (`cmirror pull`).
6. **Move machines** — install the tools; **hand-carry the age identity** (the one
   true secret); restore `~/.config/cmirror/config.toml` + the shared IMAP secrets;
   `cmirror pull --all` reconstitutes every teka from Drive ciphertext; re-baseline
   the imap-extract cursors.

**Bootstrap chicken-and-egg:** the *only* thing you must move by hand is the age
identity. Everything else — config, secrets, all teka content — can itself sit as a
tiny cmirror-encrypted bootstrap blob in Drive, because once the identity is in
place you can decrypt it. One secret to guard; everything else self-restoring.

## 8. Privacy posture (firm)

All work happens in **local Claude Code sessions** — never cloud-hosted. The only
thing that leaves the machine is **encrypted** age backup. The accepted exposure
ceiling is Claude Code conversation content to Anthropic; raw teka contents are
never stored in the cloud in plain form, and never pasted into web tools.

## 9. Naming

- **teka** — each project instance (romanised тека / θήκη; "a curated folder on one
  subject"). The CLI is `lifeproj`; `git` manages repos, `lifeproj` manages tekas.
- Avoid the collisions on disk: `manifest` (an OCR page-index in one teka),
  `handoff` (a raw-input dump in another), `catalog`/`status` (already meaning
  specific things). "matter" was rejected as the universal noun — it is legal
  jargon that biases the skeleton toward timelines/privilege and doesn't fit a
  finite, transactional teka.

## 10. Non-goals (deliberately not built)

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
  convention now.
