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
