"""lifeproj command-line interface.

    lifeproj new <name> [--intake email,docs] [--artifact timeline,ledger] ...
    lifeproj overview
    lifeproj root [<path>] [--rehome]
    lifeproj archive <name> [--purge-local]
    lifeproj restore <name>
    lifeproj equip [<name> ...] [--force] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from lifeproj import (__version__, archive, equip, osavul, overview, registry,
                      scaffold, templates)

INTAKE_MAP = {"email": "email-intake", "docs": "docs-intake", "github": "github-source"}
ARTIFACT_MAP = {
    "timeline": "timeline", "ledger": "ledger", "chapters": "chapters",
    "entities": "entities", "catalog": None,  # catalog == the spine; no extra module
}


def _csv(value: str) -> list:
    return [v.strip() for v in value.split(",") if v.strip()]


def _modules_from_args(args) -> list:
    mods: list = []
    for token in args.intake:
        if token not in INTAKE_MAP:
            raise SystemExit(f"unknown --intake {token!r}; choose from {', '.join(INTAKE_MAP)}")
        mods.append(INTAKE_MAP[token])
    for token in args.artifact:
        if token not in ARTIFACT_MAP:
            raise SystemExit(f"unknown --artifact {token!r}; choose from {', '.join(ARTIFACT_MAP)}")
        m = ARTIFACT_MAP[token]
        if m:
            mods.append(m)
    mods.extend(args.module)
    # de-dupe, preserve order
    seen, out = set(), []
    for m in mods:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def cmd_new(args) -> int:
    name = args.name
    working_dir = Path(args.path).expanduser() if args.path else Path(f"~/personal/{name}").expanduser()
    config = Path(args.config).expanduser() if args.config else None
    # encrypted_dir: explicit flag > configured root (`lifeproj root`) > legacy
    # default. The legacy path predates the root and may not exist any more —
    # the note below surfaces that at scaffold time, not first-backup time.
    try:
        root = registry.encrypted_root(registry.load(config))
    except OSError:
        root = None   # registry unreadable (e.g. sandboxed dry-run) — fall back
    if args.encrypted_dir:
        encrypted_dir = Path(args.encrypted_dir).expanduser()
    elif root:
        encrypted_dir = root / name
    else:
        encrypted_dir = Path(f"~/personal/gd-sync/{name}").expanduser()
    created = datetime.date.today().isoformat()
    modules = _modules_from_args(args)

    plan = scaffold.build(
        name, working_dir, encrypted_dir, domain=args.domain, lifecycle=args.lifecycle,
        summary=args.summary or f"(describe what the {name} teka is for)",
        modules=modules, created=created, imap_folder=args.imap_folder,
        chapter_noun=args.chapter_noun, register=not args.no_register,
    )
    if plan.register and not encrypted_dir.parent.is_dir():
        plan.notes.append(
            f"encrypted_dir parent {encrypted_dir.parent} does not exist — cmirror"
            " backup will fail until it does. Set the base folder once with"
            " `lifeproj root <path>` (or pass --encrypted-dir).")

    if args.dry_run:
        print(f"[dry-run] would create teka {name!r} at {working_dir}")
        print(f"  modules : {', '.join(modules) or '(spine only)'}")
        print(f"  dirs    : {', '.join(plan.dirs)}")
        print(f"  files   : {', '.join(sorted(plan.files))}")
        print(f"  register: {'yes' if plan.register else 'no'} "
              f"(encrypted_dir={encrypted_dir}"
              + (f", imap_folder={plan.imap_folder}" if plan.imap_folder else "") + ")")
        for note in plan.notes:
            print(f"  note    : {note}")
        return 0

    shared = Path(args.imap_shared).expanduser() if args.imap_shared else None
    result = scaffold.apply(plan, shared_env=shared, config_path=config)

    print(f"Created teka {name!r} at {result['working_dir']}")
    print(f"  registered in cmirror config: {'yes' if result['registered'] else 'no'}")
    if result["env"]:
        print(f"  intake env: {result['env']}")
    for note in result["notes"]:
        print(f"  note: {note}")
    print("\nNext:")
    print(f"  1. Edit {working_dir}/CLAUDE.md (the shared operating manual) and README.md.")
    if plan.imap_folder:
        print(f"  2. Create the IMAP label {plan.imap_folder!r}, then: "
              f"cd {working_dir}/scripts/mail && imap-extract --once")
    print(f"  3. First backup: cmirror backup --project {name}")
    print("  4. Sandbox: the teka session profile must grant ~/.local/share/osavul"
          " (the agenda spool),")
    print("     or `lifeproj publish` will no-op with a hint each digest.")
    print(f"  5. Open {working_dir} in Codex or Claude Code and run the digest ritual.")
    return 0


def cmd_overview(args) -> int:
    config = Path(args.config).expanduser() if args.config else None
    print(overview.render(overview.collect(config)))
    return 0


def cmd_root(args) -> int:
    """Show or set [lifeproj].encrypted_root — the base folder new tekas back
    up under — and report/repair each active teka's encrypted_dir against it."""
    config = Path(args.config).expanduser() if args.config else None
    doc = registry.load(config)
    changed = False
    if args.path:
        root = Path(args.path).expanduser()
        if not root.is_dir():
            print(f"error: {root} is not an existing directory — create/sync it"
                  " first (is Google Drive for Desktop running?)", file=sys.stderr)
            return 1
        registry.set_encrypted_root(doc, root)
        changed = True
    root = registry.encrypted_root(doc)
    if root is None:
        print("no encrypted root configured; set one with: lifeproj root <path>")
        return 0

    if args.rehome:
        for name, old, new in registry.rehome_missing(doc, root):
            print(f"{name}: rehomed {old} -> {new}")
            changed = True
    if changed:
        registry.save(doc, config)

    print(f"encrypted root: {root}")
    for name, table in registry.projects(doc).items():
        raw = table.get("encrypted_dir") if hasattr(table, "get") else None
        if not raw:
            print(f"  {name}: no encrypted_dir in registry")
            continue
        ed = Path(str(raw)).expanduser()
        if ed.exists():
            note = "ok" if ed.parent == root else f"ok (outside root: {ed})"
        else:
            note = (f"MISSING {ed} — repoint with `lifeproj root --rehome`"
                    if not args.rehome else f"pending first backup: {ed}")
        print(f"  {name}: {note}")
    return 0


def cmd_archive(args) -> int:
    config = Path(args.config).expanduser() if args.config else None
    try:
        archive.archive(args.name, purge_local=args.purge_local, yes=args.yes,
                        skip_verify=args.skip_verify, config_path=config)
    except archive.ArchiveError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_restore(args) -> int:
    config = Path(args.config).expanduser() if args.config else None
    try:
        archive.restore(args.name, config_path=config)
    except archive.ArchiveError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_publish(args) -> int:
    return osavul.publish(Path(args.path).expanduser() if args.path else None)


def cmd_equip(args) -> int:
    config = Path(args.config).expanduser() if args.config else None
    if args.path:
        entry = equip.equip_teka(Path(args.path).expanduser(),
                                 force=args.force, dry_run=args.dry_run)
        prefix = "[dry-run] " if args.dry_run else ""
        if entry["status"] == "skipped":
            print(f"{prefix}{entry['dir']}: skipped — {entry['error']}")
            return 1
        for rel, act in entry["actions"]:
            print(f"{prefix}{rel}: {act}")
        if entry["claude_hint"]:
            print("\nCLAUDE.md has no standard working-rules section to extend."
                  " Paste this bullet where it fits:\n")
            print(equip.CLAUDE_RULE_HINT)
        if entry["osavul_hint"]:
            print("\nCLAUDE.md has no '## Repository map' heading to anchor the"
                  " Osavul publishing section. Paste this section where it fits:\n")
            print(templates.CLAUDE_OSAVUL)
        return 0
    return equip.equip_all(config, names=args.name or None,
                           force=args.force, dry_run=args.dry_run)


def cmd_drain(args) -> int:
    if getattr(args, "all", False):
        config = Path(args.config).expanduser() if args.config else None
        return osavul.drain_all(config, as_json=args.json)
    return osavul.drain(Path(args.path).expanduser() if args.path else None)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lifeproj", description="Orchestrate local, agent-maintained tekas with encrypted backups.")
    p.add_argument("--version", action="version", version=f"lifeproj {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    n = sub.add_parser("new", help="scaffold a new teka")
    n.add_argument("name")
    n.add_argument("--path", help="working dir (default ~/personal/<name>)")
    n.add_argument("--encrypted-dir",
                   help="cmirror encrypted_dir (default <root>/<name> per `lifeproj root`,"
                        " legacy ~/personal/gd-sync/<name> when no root is set)")
    n.add_argument("--domain", default="general", help="legal | tenancy | condo | product | tax | general")
    n.add_argument("--lifecycle", default="ongoing", choices=["ongoing", "finite"])
    n.add_argument("--summary", help="one-line description of the teka")
    n.add_argument("--intake", type=_csv, default=[], help="csv: email,docs,github")
    n.add_argument("--artifact", type=_csv, default=[], help="csv: catalog,timeline,ledger,chapters,entities")
    n.add_argument("--module", action="append", default=[], help="add a module by name (repeatable)")
    n.add_argument("--imap-folder", help="IMAP label for the email-intake module")
    n.add_argument("--chapter-noun", default="chapter", help="label for chapters (e.g. tenancy)")
    n.add_argument("--imap-shared", help="shared IMAP secrets file (default ~/.config/lifeproj/imap-shared.env)")
    n.add_argument("--no-register", action="store_true", help="do not add to cmirror config")
    n.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    n.add_argument("--config", help="cmirror config path (default $CMIRROR_CONFIG or ~/.config/cmirror/config.toml)")
    n.set_defaults(func=cmd_new)

    o = sub.add_parser("overview", help="cross-teka read-only status")
    o.add_argument("--config")
    o.set_defaults(func=cmd_overview)

    rt = sub.add_parser("root", help="show or set the base folder for encrypted backups")
    rt.add_argument("path", nargs="?", help="new root (must already exist); omit to show")
    rt.add_argument("--rehome", action="store_true",
                    help="repoint active tekas whose encrypted_dir is missing on disk to <root>/<name>")
    rt.add_argument("--config", help="cmirror config path (default $CMIRROR_CONFIG or ~/.config/cmirror/config.toml)")
    rt.set_defaults(func=cmd_root)

    a = sub.add_parser("archive", help="retire a teka from the sync cycle")
    a.add_argument("name")
    a.add_argument("--purge-local", action="store_true", help="delete the local plaintext copy after verify")
    a.add_argument("--yes", action="store_true", help="don't prompt before deleting")
    a.add_argument("--skip-verify", action="store_true", help="skip the post-backup integrity check (not recommended)")
    a.add_argument("--config")
    a.set_defaults(func=cmd_archive)

    r = sub.add_parser("restore", help="revive an archived teka from Drive")
    r.add_argument("name")
    r.add_argument("--config")
    r.set_defaults(func=cmd_restore)

    pub = sub.add_parser("publish", help="project this teka's open_items into the Osavul agenda spool")
    pub.add_argument("--path", help="teka dir (default: current directory)")
    pub.set_defaults(func=cmd_publish)

    eq = sub.add_parser("equip", help="sync Codex/Claude spine assets into existing tekas")
    eq.add_argument("name", nargs="*",
                    help="registered teka name(s); default: every registered teka")
    eq.add_argument("--path", help="equip one teka by directory instead of by name")
    eq.add_argument("--force", action="store_true",
                    help="overwrite customized skill copies (never living instruction files)")
    eq.add_argument("--dry-run", action="store_true", help="report actions, write nothing")
    eq.add_argument("--config", help="cmirror config path (default $CMIRROR_CONFIG or ~/.config/cmirror/config.toml)")
    eq.set_defaults(func=cmd_equip)

    dr = sub.add_parser("drain", help="apply Osavul completion signals to a teka (or --all registered tekas)")
    dr.add_argument("--path", help="teka dir (default: current directory)")
    dr.add_argument("--all", action="store_true",
                    help="drain + republish every registered teka (registry-driven; run unsandboxed, e.g. from cron)")
    dr.add_argument("--json", action="store_true", help="with --all: emit a structured JSON array")
    dr.add_argument("--config", help="cmirror config path (default $CMIRROR_CONFIG or ~/.config/cmirror/config.toml)")
    dr.set_defaults(func=cmd_drain)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
