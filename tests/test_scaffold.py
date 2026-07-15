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
            for f in ("AGENTS.md", "CLAUDE.md", "README.md", "DASHBOARD.md",
                      "catalog.json", "catalog_check.py"):
                self.assertTrue((wd / f).exists(), f)
            # Tekas are local-only (no git), so no .gitignore is scaffolded.
            self.assertFalse((wd / ".gitignore").exists())
            catalog = json.loads((wd / "catalog.json").read_text())
            self.assertEqual(catalog["meta"]["schema_version"], 2)
            self.assertEqual(catalog["documents"], [])
            # Dashboard renders the three roll-up buckets.
            dash = (wd / "DASHBOARD.md").read_text()
            for bucket in ("Overdue", "Due soon", "No deadline"):
                self.assertIn(bucket, dash)

    def test_spine_supports_codex_and_claude_from_one_manual(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._build(tmp, [])
            res = scaffold.apply(plan)
            wd = Path(res["working_dir"])
            agents = (wd / "AGENTS.md").read_text()
            claude = (wd / "CLAUDE.md").read_text()
            self.assertIn("Read it completely before", agents)
            self.assertIn("acting and follow it", agents)
            self.assertIn("`CLAUDE.md`", agents)
            self.assertIn("Codex", claude)
            self.assertIn("Claude Code", claude)

            codex_skill = wd / ".agents" / "skills" / "humanize" / "SKILL.md"
            claude_skill = wd / ".claude" / "skills" / "humanize" / "SKILL.md"
            self.assertTrue(codex_skill.exists())
            self.assertTrue(claude_skill.exists())
            body = codex_skill.read_text()
            self.assertEqual(body, claude_skill.read_text())
            self.assertIn("name: humanize", body)
            # Copied verbatim — no unrendered tokens, attribution intact.
            self.assertNotIn("{{", body)
            self.assertIn("blader/humanizer", body)
            # The shared manual binds drafting to both agents' skill copies.
            self.assertIn(".agents/skills/humanize/", claude)
            self.assertIn(".claude/skills/humanize/", claude)

    def test_email_module_renders_env_and_correspondence(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._build(tmp, ["email-intake"], imap_folder="Labels/Demo")
            res = scaffold.apply(plan)
            wd = Path(res["working_dir"])
            env = wd / "scripts" / "mail" / ".env"
            # Config lives in scripts/mail (persistent), NOT in the intake drain.
            self.assertTrue(env.exists())
            self.assertFalse((wd / "intake" / "mail" / ".env").exists())
            self.assertTrue((wd / "intake" / "mail").is_dir())
            self.assertTrue((wd / "correspondence").is_dir())
            body = env.read_text()
            self.assertIn("IMAP_FOLDER=Labels/Demo", body)
            # Mail still drains into intake/mail via TARGET_DIR (absolute path).
            self.assertIn(f"TARGET_DIR={(wd / 'intake' / 'mail').resolve()}", body)
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

    def test_osavul_module_adds_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._build(tmp, ["osavul"])
            claude = plan.files["CLAUDE.md"]
            self.assertIn("Module: osavul", claude)
            self.assertIn("lifeproj publish", claude)

    def _run_check(self, wd, open_items):
        catalog = json.loads((wd / "catalog.json").read_text())
        catalog["open_items"] = open_items
        (wd / "catalog.json").write_text(json.dumps(catalog, indent=2))
        return subprocess.run([sys.executable, str(wd / "catalog_check.py")],
                              capture_output=True, text=True)

    def test_catalog_check_enforces_strict_open_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(scaffold.apply(self._build(tmp, []))["working_dir"])
            good = [{"id": "demo-2026-001", "title": "x", "status": "open",
                     "priority": "high", "due": "2026-07-01"}]
            self.assertEqual(self._run_check(wd, good).returncode, 0)
            # neither due nor no_deadline
            self.assertEqual(self._run_check(wd, [dict(good[0], due=None)]).returncode, 1)
            # bad enum
            self.assertEqual(self._run_check(wd, [dict(good[0], status="nope")]).returncode, 1)
            # waiting without waiting_on
            self.assertEqual(self._run_check(wd, [dict(good[0], status="waiting")]).returncode, 1)
            # missing required field
            self.assertEqual(self._run_check(wd, [{"id": "demo-2026-002"}]).returncode, 1)

    def test_catalog_check_legacy_schema_skips_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(scaffold.apply(self._build(tmp, []))["working_dir"])
            catalog = json.loads((wd / "catalog.json").read_text())
            catalog["meta"]["schema_version"] = 1  # un-migrated teka
            catalog["open_items"] = [{"id": "loose", "title": "no schema here"}]
            (wd / "catalog.json").write_text(json.dumps(catalog, indent=2))
            proc = subprocess.run([sys.executable, str(wd / "catalog_check.py")],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
