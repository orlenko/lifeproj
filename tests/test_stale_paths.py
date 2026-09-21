import tempfile
import unittest
from pathlib import Path

from lifeproj import stale_paths


class StalePathTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "Users" / "new"
        self.wd = self.home / "tekas" / "strata"
        (self.wd / "scripts").mkdir(parents=True)
        (self.wd / ".claude").mkdir()
        (self.wd / "scripts" / "run.sh").write_text(
            "cd /Users/old/personal/strata && /Users/old/.local/bin/x\n")
        (self.wd / ".claude" / "settings.json").write_text(
            '{"cmd": "~/personal/strata/hook.sh"}\n')
        (self.wd / "notes.md").write_text("filed from /Users/old/personal/strata\n")
        (self.wd / "clean.py").write_text("print('hi')\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_report_only_without_old_home(self):
        r = stale_paths.scan(self.wd, home=self.home)
        self.assertEqual(r["fixed"], [])
        self.assertEqual(sorted(rel for rel, _ in r["remaining"]),
                         ["notes.md", "scripts/run.sh"])
        self.assertIn("/Users/old/", (self.wd / "scripts" / "run.sh").read_text())

    def test_fix_rewrites_code_and_config_but_not_prose(self):
        r = stale_paths.scan(self.wd, old_home=Path("/Users/old/personal"),
                             fix=True, home=self.home)
        self.assertEqual(sorted(r["fixed"]), [".claude/settings.json", "scripts/run.sh"])
        self.assertEqual((self.wd / "scripts" / "run.sh").read_text(),
                         f"cd {self.home}/tekas/strata && {self.home}/.local/bin/x\n")
        self.assertEqual((self.wd / ".claude" / "settings.json").read_text(),
                         '{"cmd": "~/tekas/strata/hook.sh"}\n')
        # Prose keeps its history and is still reported.
        self.assertIn("/Users/old/personal/strata", (self.wd / "notes.md").read_text())
        self.assertEqual(r["remaining"], [("notes.md", 1)])

    def test_own_home_is_not_stale(self):
        (self.wd / "scripts" / "run.sh").write_text(f"{self.home}/tekas/strata\n")
        (self.wd / "notes.md").unlink()
        (self.wd / ".claude" / "settings.json").unlink()
        self.assertEqual(stale_paths.scan(self.wd, home=self.home)["remaining"], [])


if __name__ == "__main__":
    unittest.main()
