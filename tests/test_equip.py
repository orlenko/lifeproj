import shutil
import tempfile
import unittest
from pathlib import Path

from lifeproj import equip, scaffold, templates

SKILL_REL = ".claude/skills/humanize/SKILL.md"


class EquipTests(unittest.TestCase):
    def _teka(self, tmp, name="demo", pre_skill=True):
        """Scaffold a teka; with pre_skill=True, strip the skill + CLAUDE.md rule
        to simulate one stamped before the skill existed."""
        plan = scaffold.build(
            name, Path(tmp) / name, Path(tmp) / "gd" / name,
            domain="general", lifecycle="ongoing", summary="A demo teka.",
            modules=[], created="2026-06-26", register=False,
        )
        wd = Path(scaffold.apply(plan)["working_dir"])
        if pre_skill:
            shutil.rmtree(wd / ".claude")
            claude = wd / "CLAUDE.md"
            claude.write_text("\n".join(
                line for line in claude.read_text().splitlines()
                if ".claude/skills" not in line) + "\n")
        return wd

    def test_installs_missing_skill_and_adds_claude_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = self._teka(tmp)
            entry = equip.equip_teka(wd)
            self.assertEqual(entry["actions"][0], (SKILL_REL, "installed"))
            self.assertTrue((wd / SKILL_REL).exists())
            # The drafting rule lands inside the working-rules section.
            self.assertFalse(entry["claude_hint"])
            self.assertEqual(entry["actions"][1][0], "CLAUDE.md")
            claude = (wd / "CLAUDE.md").read_text()
            rules_at = claude.index("## Working rules")
            bullet_at = claude.index(".claude/skills/humanize")
            next_section_at = claude.index("## Open items")
            self.assertTrue(rules_at < bullet_at < next_section_at)
            # Second run is a full no-op.
            entry = equip.equip_teka(wd)
            self.assertEqual(entry["actions"], [(SKILL_REL, "current")])
            self.assertEqual(claude, (wd / "CLAUDE.md").read_text())

    def test_customized_claude_without_anchor_gets_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = self._teka(tmp)
            before = "# my own manual\n\nNo standard sections here.\n"
            (wd / "CLAUDE.md").write_text(before)
            entry = equip.equip_teka(wd)
            self.assertTrue(entry["claude_hint"])
            self.assertEqual((wd / "CLAUDE.md").read_text(), before)

    def test_customized_skill_kept_unless_forced(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = self._teka(tmp, pre_skill=False)
            target = wd / SKILL_REL
            target.write_text("# my customized version\n")
            entry = equip.equip_teka(wd)
            self.assertIn("differs", entry["actions"][0][1])
            self.assertEqual(target.read_text(), "# my customized version\n")
            entry = equip.equip_teka(wd, force=True)
            self.assertEqual(entry["actions"], [(SKILL_REL, "updated")])
            self.assertEqual(target.read_text(),
                             templates.data("skills/humanize/SKILL.md"))

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = self._teka(tmp)
            before = (wd / "CLAUDE.md").read_text()
            entry = equip.equip_teka(wd, dry_run=True)
            self.assertEqual(entry["actions"][0], (SKILL_REL, "installed"))
            self.assertEqual(entry["actions"][1][0], "CLAUDE.md")
            self.assertFalse((wd / SKILL_REL).exists())
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
            self.assertTrue((wd / SKILL_REL).exists())
            # Unknown name errors; nothing else is touched.
            self.assertEqual(equip.equip_all(config, names=["nope"]), 1)

    def test_scaffolded_teka_has_no_claude_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = self._teka(tmp, pre_skill=False)
            entry = equip.equip_teka(wd)
            self.assertEqual(entry["actions"], [(SKILL_REL, "current")])
            self.assertFalse(entry["claude_hint"])


if __name__ == "__main__":
    unittest.main()
