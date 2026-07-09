import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import tomlkit

from lifeproj import archive, registry


class RestoreTests(unittest.TestCase):
    """`lifeproj restore` must survive the archive --purge-local round-trip:
    recreate the purged working_dir before pulling, and be safe to re-run."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        self.config = root / "config.toml"
        self.working = root / "wd" / "tax-2025"       # deliberately absent (purged)
        self.encrypted = root / "ed" / "tax-2025"

        doc = tomlkit.parse('identity_file = "/x"\n')
        doc["archived"] = tomlkit.table(is_super_table=True)
        table = tomlkit.table()
        table["working_dir"] = str(self.working)
        table["encrypted_dir"] = str(self.encrypted)
        doc["archived"]["tax-2025"] = table
        self.config.write_text(tomlkit.dumps(doc))

    def tearDown(self):
        self._tmp.cleanup()

    def _reload(self):
        return tomlkit.parse(self.config.read_text())

    def test_restore_creates_working_dir_before_pull(self):
        # As after `archive --purge-local`: the working dir is gone.
        self.assertFalse(self.working.exists())
        seen = {}

        def fake_run(args):
            # cmirror pull refuses unless working_dir exists — prove it does by now.
            seen["existed_at_pull"] = self.working.is_dir()
            return 0

        with mock.patch.object(archive, "_cmirror", return_value="cmirror"), \
             mock.patch.object(archive, "_run", side_effect=fake_run):
            result = archive.restore("tax-2025", config_path=self.config)

        self.assertTrue(seen["existed_at_pull"],
                        "working_dir must exist before cmirror pull runs")
        self.assertTrue(self.working.is_dir())
        self.assertEqual(result, {"name": "tax-2025", "active": True})
        self.assertIn("tax-2025", registry.projects(self._reload()))

    def test_restore_is_idempotent_when_already_active(self):
        calls = []

        with mock.patch.object(archive, "_cmirror", return_value="cmirror"), \
             mock.patch.object(archive, "_run", side_effect=lambda a: calls.append(a) or 0):
            archive.restore("tax-2025", config_path=self.config)   # archived -> active + pull
            archive.restore("tax-2025", config_path=self.config)   # already active: must NOT raise

        self.assertEqual(len(calls), 2, "second restore should retry the pull, not error")
        self.assertIn("tax-2025", registry.projects(self._reload()))

    def test_restore_unregistered_raises(self):
        with self.assertRaises(archive.ArchiveError):
            archive.restore("nope", config_path=self.config)


if __name__ == "__main__":
    unittest.main()
