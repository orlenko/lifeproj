# lifeproj repository instructions

lifeproj is a thin Python orchestrator for tekas: plaintext local life-admin
folders whose off-machine backups are encrypted by cmirror. Keep the centre
small. Reusable public mechanisms belong in the homebrew tap; teka-aware
scaffolding and fleet operations belong here; one-off domain logic belongs in
the individual teka.

## Before changing behavior

- Read `docs/DESIGN.md` for the system invariants and privacy model.
- Prior agent rationale is stored outside this repository in
  `~/.rationale/repo/`. When investigating unfamiliar behavior or revisiting a
  design decision, search it with `rationale search <path-or-keyword>`.
- Do not inspect real teka contents, cmirror configuration, IMAP secrets, or the
  Osavul spool unless the user explicitly puts that data in scope. Tests should
  use temporary directories and synthetic data.

## Implementation conventions

- Support Codex and Claude Code equally. Codex discovers project guidance in
  `AGENTS.md` and repo skills in `.agents/skills/`; Claude Code uses `CLAUDE.md`
  and `.claude/skills/`.
- In generated tekas, `CLAUDE.md` is the shared operating manual and
  `AGENTS.md` is the stable Codex bridge to it. Do not create two independently
  editable copies of the manual.
- A packaged spine skill has one source under `src/lifeproj/data/skills/` and is
  copied to both agent-specific skill directories when scaffolding or equipping
  a teka.
- `lifeproj equip` must remain idempotent and fleet-resilient. Preserve
  customized skill copies unless `--force` is explicit, and never overwrite
  living `AGENTS.md` or `CLAUDE.md` instructions wholesale.
- Generated tekas are intentionally not Git repositories. Do not add Git
  scaffolding or send confidential content to external services.
- Keep `pyproject.toml` and `src/lifeproj/__init__.py` versions in sync.

## Verification

Run the full suite after behavior changes:

```sh
uv run python -m unittest discover -s tests -v
```

When changing scaffolded output, also exercise `lifeproj new --dry-run` and
inspect a generated temporary teka. Add or update tests for fresh scaffolds,
legacy retrofit behavior, idempotency, dry runs, and customization preservation.
