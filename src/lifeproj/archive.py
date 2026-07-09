"""`lifeproj archive` / `restore` — retire a teka from the sync cycle, or revive it.

archive: ensure the encrypted backup is current and verified, move the teka from
``[projects.*]`` to ``[archived.*]`` so cmirror stops touching it, and (only with
``--purge-local``) delete the local plaintext working copy. The encrypted blob
stays in Drive; set ``gd-sync/<name>`` to Drive "online-only" afterwards to free
the local ciphertext too.

restore: move it back to ``[projects.*]`` and pull the working copy from Drive.
Idempotent — safe to re-run after a failed pull — and it recreates the working
dir first (``cmirror pull`` requires it; ``--purge-local`` deleted it).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from lifeproj import registry


class ArchiveError(RuntimeError):
    pass


def _cmirror() -> str:
    exe = shutil.which("cmirror")
    if not exe:
        raise ArchiveError("cmirror not found on PATH; refusing to proceed.")
    return exe


def _run(args: list[str]) -> int:
    print("  $ " + " ".join(args))
    return subprocess.call(args)


def archive(name: str, *, purge_local: bool = False, yes: bool = False,
            skip_verify: bool = False, config_path: Optional[Path] = None) -> dict:
    doc = registry.load(config_path)
    section, table = registry.find(doc, name)
    if section is None:
        raise ArchiveError(f"teka {name!r} is not registered.")
    if section == registry.ARCHIVED:
        raise ArchiveError(f"teka {name!r} is already archived.")

    working_dir = Path(str(table.get("working_dir", ""))).expanduser()
    encrypted_dir = Path(str(table.get("encrypted_dir", ""))).expanduser()
    cmirror = _cmirror()

    print(f"Archiving {name!r}.")
    print("Step 1/3: final backup")
    if _run([cmirror, "backup", "--project", name]) != 0:
        raise ArchiveError("final backup failed; nothing changed.")

    if not skip_verify:
        print("Step 2/3: verify backup integrity")
        if _run([cmirror, "verify", "--project", name]) != 0:
            raise ArchiveError("verify failed; nothing changed (local copy kept).")
    else:
        print("Step 2/3: verify SKIPPED (--skip-verify)")

    print("Step 3/3: move to [archived.*]")
    registry.archive(doc, name)
    registry.save(doc, config_path)

    result = {"name": name, "archived": True, "purged": False,
              "encrypted_dir": str(encrypted_dir)}

    if purge_local:
        if working_dir.exists():
            if not yes:
                reply = input(f"Delete local plaintext {working_dir}? [y/N] ").strip().lower()
                if reply not in ("y", "yes"):
                    print("Kept local copy. Teka is archived (no longer backed up).")
                    return result
            shutil.rmtree(working_dir)
            result["purged"] = True
            print(f"Deleted {working_dir}")
        else:
            print(f"Local working dir already absent: {working_dir}")
        print(f"Tip: in Google Drive, set {encrypted_dir} to 'online-only' to free "
              "the local ciphertext too (the cloud copy is retained).")
    else:
        print("Local copy kept. Re-run with --purge-local to delete it once you're sure.")
    return result


def restore(name: str, *, config_path: Optional[Path] = None) -> dict:
    doc = registry.load(config_path)
    section, table = registry.find(doc, name)
    if section is None:
        raise ArchiveError(f"teka {name!r} is not registered.")

    if section == registry.ARCHIVED:
        print(f"Restoring {name!r}: move to [projects.*]")
        registry.restore(doc, name)
        registry.save(doc, config_path)
    else:
        # Already active. cmirror only reads [projects.*], so restore must
        # flip the entry active *before* it can pull — which means a pull that
        # fails (e.g. a purged working_dir) leaves the teka active-but-empty and
        # a naive re-run would hard-error. Make restore idempotent instead:
        # re-entry just retries the pull.
        print(f"Teka {name!r} already active; re-pulling working copy.")

    raw_wd = str(table.get("working_dir", "")).strip()
    if not raw_wd:
        raise ArchiveError(f"teka {name!r} has no working_dir in the registry.")
    working_dir = Path(raw_wd).expanduser()
    # cmirror pull refuses to run unless working_dir exists, and
    # `archive --purge-local` deletes it — so recreate it here or the
    # purge → restore round-trip can never complete.
    working_dir.mkdir(parents=True, exist_ok=True)

    cmirror = _cmirror()
    print("Pull working copy from Drive")
    rc = _run([cmirror, "pull", "--project", name])
    if rc != 0:
        raise ArchiveError("pull failed; teka is re-activated but local copy not restored.")
    print("Done. Re-baseline imap-extract (delete intake/mail/state.json) if this teka watches mail.")
    return {"name": name, "active": True}
