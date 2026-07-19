"""lifeproj — a thin orchestrator for local, agent-maintained *tekas* with encrypted backups.

A teka is a plain local folder (the source of truth, plaintext, on this machine
only). Durability + portability come from cmirror's encrypted mirror in Google
Drive; reusable tools come from the homebrew tap; bespoke per-teka logic stays in
the teka. lifeproj only does the cross-cutting plumbing: scaffold, register,
archive, restore, and a read-only overview.

See docs/DESIGN.md for the full model.
"""

__version__ = "0.8.0"
