import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from lifeproj import equip, scaffold, templates

CODEX_SKILL_REL = ".agents/skills/humanize/SKILL.md"
CLAUDE_SKILL_REL = ".claude/skills/humanize/SKILL.md"
SKILL_RELS = (CODEX_SKILL_REL, CLAUDE_SKILL_REL)


class EquipTests(unittest.TestCase):
    def _teka(self, tmp, name="demo", pre_assets=True):
        """Scaffold a teka, optionally stripping agent assets to make a legacy one."""
        plan = scaffold.build(
            name, Path(tmp) / name, Path(tmp) / "gd" / name,
            domain="general", lifecycle="ongoing", summary="A demo teka.",
            modules=[], created="2026-06-26", register=False,
        )
        wd = Path(scaffold.apply(plan)["working_dir"])
        if pre_assets:
            (wd / "AGENTS.md").unlink()
            shutil.rmtree(wd / ".agents")
            shutil.rmtree(wd / ".claude")
            claude = wd / "CLAUDE.md"
            body = claude.read_text()
            start = body.index("- **Drafts sound human.**")
            end = body.index("- **Privacy posture.**")
            body = body[:start] + body[end:]
            # Pre-v0.8 manuals also predate the spine Osavul section.
            start = body.index("## Publishing to Osavul")
            end = body.index("## Repository map")
            claude.write_text(body[:start] + body[end:])
        return wd

    def test_installs_codex_bridge_and_both_skill_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = self._teka(tmp)
            entry = equip.equip_teka(wd)
            self.assertIn(("AGENTS.md", "installed Codex bridge"), entry["actions"])
            for rel in SKILL_RELS:
                self.assertIn((rel, "installed"), entry["actions"])
                self.assertTrue((wd / rel).exists())
            self.assertEqual((wd / CODEX_SKILL_REL).read_text(),
                             (wd / CLAUDE_SKILL_REL).read_text())
            self.assertEqual((wd / "AGENTS.md").read_text(), templates.AGENTS_BRIDGE)
            # The drafting rule lands inside the working-rules section.
            self.assertFalse(entry["claude_hint"])
            self.assertIn(("CLAUDE.md", "drafting rule added to working rules"),
                          entry["actions"])
            claude = (wd / "CLAUDE.md").read_text()
            rules_at = claude.index("## Working rules")
            bullet_at = claude.index(".agents/skills/humanize")
            next_section_at = claude.index("## Open items")
            self.assertTrue(rules_at < bullet_at < next_section_at)
            # The Osavul publishing section lands before the repository map.
            self.assertFalse(entry["osavul_hint"])
            self.assertIn(("CLAUDE.md", "Osavul publishing section added"),
                          entry["actions"])
            osavul_at = claude.index("## Publishing to Osavul")
            self.assertTrue(next_section_at < osavul_at
                            < claude.index("## Repository map"))
            # Second run is a full no-op.
            entry = equip.equip_teka(wd)
            self.assertEqual(entry["actions"], [
                ("AGENTS.md", "current"),
                (CODEX_SKILL_REL, "current"),
                (CLAUDE_SKILL_REL, "current"),
            ])
            self.assertEqual(claude, (wd / "CLAUDE.md").read_text())

    def test_customized_claude_without_anchor_gets_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = self._teka(tmp)
            before = "# my own manual\n\nNo standard sections here.\n"
            (wd / "CLAUDE.md").write_text(before)
            entry = equip.equip_teka(wd)
            self.assertTrue(entry["claude_hint"])
            self.assertTrue(entry["osavul_hint"])
            self.assertEqual((wd / "CLAUDE.md").read_text(), before)

    def test_old_module_section_counts_as_taught(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = self._teka(tmp)
            claude = wd / "CLAUDE.md"
            body = claude.read_text()
            at = body.index("## Repository map")
            claude.write_text(
                body[:at]
                + "## Module: osavul (cross-teka agenda publishing)\n\n"
                  "Run `lifeproj publish` as the last digest step.\n\n"
                + body[at:])
            entry = equip.equip_teka(wd)
            self.assertFalse(entry["osavul_hint"])
            self.assertNotIn("## Publishing to Osavul",
                             (wd / "CLAUDE.md").read_text())

    def test_customized_skill_kept_unless_forced(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = self._teka(tmp, pre_assets=False)
            target = wd / CODEX_SKILL_REL
            target.write_text("# my customized version\n")
            entry = equip.equip_teka(wd)
            action = next(a for rel, a in entry["actions"] if rel == CODEX_SKILL_REL)
            self.assertIn("differs", action)
            self.assertEqual(target.read_text(), "# my customized version\n")
            entry = equip.equip_teka(wd, force=True)
            action = next(a for rel, a in entry["actions"] if rel == CODEX_SKILL_REL)
            self.assertEqual(action, "updated")
            self.assertEqual(target.read_text(),
                             templates.data("skills/humanize/SKILL.md"))

    def test_customized_agents_instructions_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = self._teka(tmp, pre_assets=False)
            target = wd / "AGENTS.md"
            target.write_text("# my Codex rules\n")
            entry = equip.equip_teka(wd, force=True)
            action = next(a for rel, a in entry["actions"] if rel == "AGENTS.md")
            self.assertIn("living instructions", action)
            self.assertEqual(target.read_text(), "# my Codex rules\n")

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = self._teka(tmp)
            before = (wd / "CLAUDE.md").read_text()
            entry = equip.equip_teka(wd, dry_run=True)
            self.assertIn(("AGENTS.md", "installed Codex bridge"), entry["actions"])
            self.assertIn(("CLAUDE.md", "drafting rule added to working rules"),
                          entry["actions"])
            self.assertIn(("CLAUDE.md", "Osavul publishing section added"),
                          entry["actions"])
            self.assertFalse((wd / "AGENTS.md").exists())
            for rel in SKILL_RELS:
                self.assertFalse((wd / rel).exists())
            self.assertEqual((wd / "CLAUDE.md").read_text(), before)

    def test_skips_non_teka_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            bare = Path(tmp) / "bare"
            bare.mkdir()
            self.assertEqual(equip.equip_teka(bare)["status"], "skipped")
            gone = Path(tmp) / "gone"
            self.assertEqual(equip.equip_teka(gone)["status"], "skipped")

    def test_equip_all_from_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = self._teka(tmp)
            config = Path(tmp) / "config.toml"
            config.write_text(
                f'[projects.demo]\nworking_dir = "{wd}"\nencrypted_dir = "{tmp}/gd/demo"\n')
            self.assertEqual(equip.equip_all(config), 0)
            self.assertTrue((wd / "AGENTS.md").exists())
            for rel in SKILL_RELS:
                self.assertTrue((wd / rel).exists())
            # Unknown name errors; nothing else is touched.
            self.assertEqual(equip.equip_all(config, names=["nope"]), 1)

    def test_equip_all_reports_empty_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = StringIO()
            with redirect_stdout(output):
                rc = equip.equip_all(Path(tmp) / "missing.toml", dry_run=True)
            self.assertEqual(rc, 0)
            self.assertIn("no registered active tekas", output.getvalue())

    def test_scaffolded_teka_has_no_claude_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = self._teka(tmp, pre_assets=False)
            entry = equip.equip_teka(wd)
            self.assertEqual(entry["actions"], [
                ("AGENTS.md", "current"),
                (CODEX_SKILL_REL, "current"),
                (CLAUDE_SKILL_REL, "current"),
            ])
            self.assertFalse(entry["claude_hint"])
            self.assertFalse(entry["osavul_hint"])


if __name__ == "__main__":
    unittest.main()
