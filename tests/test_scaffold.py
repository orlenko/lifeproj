import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lifeproj import scaffold


class ScaffoldTests(unittest.TestCase):
    def _build(self, tmp, modules, **kw):
        return scaffold.build(
            "demo", Path(tmp) / "demo", Path(tmp) / "gd" / "demo",
            domain=kw.get("domain", "general"), lifecycle="ongoing",
            summary="A demo teka.", modules=modules, created="2026-06-26",
            imap_folder=kw.get("imap_folder"), chapter_noun=kw.get("chapter_noun", "chapter"),
            register=False,
        )

    def test_spine_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._build(tmp, [])
            res = scaffold.apply(plan)
            wd = Path(res["working_dir"])
            for f in ("CLAUDE.md", "README.md", "DASHBOARD.md", "catalog.json", "catalog_check.py", ".gitignore"):
                self.assertTrue((wd / f).exists(), f)
            catalog = json.loads((wd / "catalog.json").read_text())
            self.assertEqual(catalog["meta"]["schema_version"], 1)
            self.assertEqual(catalog["documents"], [])

    def test_email_module_renders_env_and_correspondence(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._build(tmp, ["email-intake"], imap_folder="Labels/Demo")
            res = scaffold.apply(plan)
            wd = Path(res["working_dir"])
            self.assertTrue((wd / "intake" / "mail" / ".env").exists())
            self.assertTrue((wd / "correspondence").is_dir())
            self.assertIn("IMAP_FOLDER=Labels/Demo", (wd / "intake" / "mail" / ".env").read_text())
            self.assertIn("Module: email-intake", (wd / "CLAUDE.md").read_text())

    def test_entities_module_adds_catalog_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._build(tmp, ["entities"])
            res = scaffold.apply(plan)
            catalog = json.loads((Path(res["working_dir"]) / "catalog.json").read_text())
            self.assertIn("entities", catalog)

    def test_chapters_noun_substituted(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._build(tmp, ["chapters"], chapter_noun="tenancy")
            res = scaffold.apply(plan)
            claude = (Path(res["working_dir"]) / "CLAUDE.md").read_text()
            self.assertIn("tenancy", claude)
            self.assertNotIn("{{CHAPTER_NOUN}}", claude)
            self.assertTrue((Path(res["working_dir"]) / "chapters" / "_past").is_dir())

    def test_generated_catalog_check_runs_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._build(tmp, ["entities", "email-intake"], imap_folder="Labels/Demo")
            res = scaffold.apply(plan)
            wd = Path(res["working_dir"])
            proc = subprocess.run([sys.executable, str(wd / "catalog_check.py")],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("catalog OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()
