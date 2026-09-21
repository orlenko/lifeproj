import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from lifeproj import cli, registry


class CliRootTests(unittest.TestCase):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_root_set_show_and_rehome(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = str(Path(tmp) / "config.toml")
            root = Path(tmp) / "backups"
            root.mkdir()
            dead = Path(tmp) / "gone" / "mila"
            doc = registry.load(Path(cfg))
            registry.add(doc, "mila", str(Path(tmp) / "mila"), str(dead))
            registry.save(doc, Path(cfg))

            rc, out, _ = self._run(["root", "--config", cfg])
            self.assertEqual(rc, 0)
            self.assertIn("no encrypted root configured", out)

            rc, out, _ = self._run(["root", str(root), "--config", cfg])
            self.assertEqual(rc, 0)
            self.assertIn(f"encrypted root: {root}", out)
            self.assertIn("MISSING", out)

            rc, out, _ = self._run(["root", "--rehome", "--config", cfg])
            self.assertEqual(rc, 0)
            self.assertIn(f"mila: rehomed {dead} -> {root / 'mila'}", out)
            doc = registry.load(Path(cfg))
            self.assertEqual(str(registry.projects(doc)["mila"]["encrypted_dir"]),
                             str(root / "mila"))

    def test_home_set_show_and_rehome(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = str(Path(tmp) / "config.toml")
            home = Path(tmp) / "tekas"
            old = Path(tmp) / "old-home" / "mila"
            doc = registry.load(Path(cfg))
            registry.add(doc, "mila", str(old), str(Path(tmp) / "enc" / "mila"))
            registry.add(doc, "tax-2025", str(Path(tmp) / "old-home" / "tax-2025"),
                         str(Path(tmp) / "enc" / "tax-2025"))
            registry.archive(doc, "tax-2025")
            registry.save(doc, Path(cfg))

            rc, out, _ = self._run(["home", "--config", cfg])
            self.assertEqual(rc, 0)
            self.assertIn("no teka home configured", out)

            rc, out, _ = self._run(["home", str(home), "--config", cfg])
            self.assertEqual(rc, 0)
            self.assertTrue(home.is_dir())               # created on set
            self.assertIn(f"teka home: {home}", out)
            self.assertIn("MISSING", out)

            rc, out, _ = self._run(["home", "--rehome", "--config", cfg])
            self.assertEqual(rc, 0)
            self.assertIn(f"mila: rehomed {old} -> {home / 'mila'}", out)
            doc = registry.load(Path(cfg))
            self.assertEqual(str(registry.projects(doc)["mila"]["working_dir"]),
                             str(home / "mila"))
            # Archived tekas are rehomed too, so a later restore lands in home.
            self.assertEqual(str(registry.archived(doc)["tax-2025"]["working_dir"]),
                             str(home / "tax-2025"))
            # Already under home but not on disk yet: a restore, not a repoint.
            rc, out, _ = self._run(["home", "--config", cfg])
            self.assertIn(f"mila: pending restore: {home / 'mila'}", out)
            self.assertNotIn("MISSING", out)
            # The encrypted side is `lifeproj root`'s business.
            self.assertEqual(str(registry.projects(doc)["mila"]["encrypted_dir"]),
                             str(Path(tmp) / "enc" / "mila"))

    def test_new_defaults_working_dir_under_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = str(Path(tmp) / "config.toml")
            home = Path(tmp) / "tekas"
            self._run(["home", str(home), "--config", cfg])
            rc, out, _ = self._run(["new", "demo", "--dry-run", "--config", cfg])
            self.assertEqual(rc, 0)
            self.assertIn(f"would create teka 'demo' at {home / 'demo'}", out)

    def test_root_rejects_missing_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = str(Path(tmp) / "config.toml")
            rc, _, err = self._run(["root", str(Path(tmp) / "nope"), "--config", cfg])
            self.assertEqual(rc, 1)
            self.assertIn("not an existing directory", err)
            # A failed set writes nothing.
            self.assertFalse(Path(cfg).exists())

    def test_new_defaults_encrypted_dir_under_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            root = Path(tmp) / "backups"
            root.mkdir()
            doc = registry.load(cfg)
            registry.set_encrypted_root(doc, root)
            registry.save(doc, cfg)
            rc, out, _ = self._run(["new", "demo", "--path", str(Path(tmp) / "demo"),
                                    "--dry-run", "--config", str(cfg)])
            self.assertEqual(rc, 0)
            self.assertIn(f"encrypted_dir={root / 'demo'}", out)
            self.assertNotIn("does not exist", out)

    def test_new_warns_when_encrypted_parent_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            rc, out, _ = self._run(["new", "demo", "--path", str(Path(tmp) / "demo"),
                                    "--encrypted-dir", str(Path(tmp) / "void" / "demo"),
                                    "--dry-run", "--config", str(cfg)])
            self.assertEqual(rc, 0)
            self.assertIn("does not exist", out)
            self.assertIn("lifeproj root", out)


if __name__ == "__main__":
    unittest.main()


class CliRestoreTests(unittest.TestCase):
    def test_restore_all_pulls_only_missing_or_empty_tekas(self):
        from unittest import mock
        from lifeproj import archive
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            doc = registry.load(cfg)
            present = Path(tmp) / "tekas" / "present"
            present.mkdir(parents=True)
            (present / "catalog.json").write_text("{}")
            empty = Path(tmp) / "tekas" / "empty"
            (empty / ".agents" / "skills").mkdir(parents=True)   # interrupted pull
            registry.add(doc, "present", str(present), str(Path(tmp) / "e1"))
            registry.add(doc, "empty", str(empty), str(Path(tmp) / "e2"))
            registry.add(doc, "gone", str(Path(tmp) / "tekas" / "gone"), str(Path(tmp) / "e3"))
            registry.save(doc, cfg)

            pulled = []
            with mock.patch.object(archive, "_cmirror", return_value="cmirror"), \
                 mock.patch.object(archive, "_run",
                                   side_effect=lambda a: pulled.append(a[-1]) or 0):
                out = io.StringIO()
                with redirect_stdout(out):
                    rc = cli.main(["restore", "--all", "--config", str(cfg)])
            self.assertEqual(rc, 0)
            self.assertEqual(sorted(pulled), ["empty", "gone"])
            self.assertTrue((Path(tmp) / "tekas" / "gone").is_dir())
