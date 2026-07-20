import tempfile
import unittest
from pathlib import Path

import tomlkit

from lifeproj import registry


SAMPLE = """\
identity_file = "/Users/me/.config/cmirror/identity.txt"
archive_retention_days = 0

[projects.strata]
working_dir = "/Users/me/personal/strata"
encrypted_dir = "/Users/me/personal/gd-sync/strata"
imap_folder = "Labels/Strata"

[projects.tax-2025]
working_dir = "/Users/me/personal/tax-2025"
encrypted_dir = "/Users/me/personal/gd-sync/tax-2025"
"""


class RegistryTests(unittest.TestCase):
    def doc(self):
        return tomlkit.parse(SAMPLE)

    def test_lists(self):
        doc = self.doc()
        self.assertEqual(set(registry.projects(doc)), {"strata", "tax-2025"})
        self.assertEqual(registry.archived(doc), {})

    def test_load_missing_config_returns_new_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = registry.load(Path(tmp) / "missing.toml")
            self.assertEqual(registry.projects(doc), {})

    def test_load_does_not_hide_permission_errors(self):
        class UnreadablePath:
            def read_text(self):
                raise PermissionError("denied")

        with self.assertRaises(PermissionError):
            registry.load(UnreadablePath())

    def test_add(self):
        doc = self.doc()
        registry.add(doc, "condo", "/wd/condo", "/ed/condo", imap_folder="Labels/Condo")
        self.assertIn("condo", registry.projects(doc))
        self.assertEqual(doc["projects"]["condo"]["imap_folder"], "Labels/Condo")

    def test_add_duplicate_rejected(self):
        doc = self.doc()
        with self.assertRaises(ValueError):
            registry.add(doc, "strata", "/x", "/y")

    def test_archive_round_trip_preserves_data_and_other_projects(self):
        doc = self.doc()
        registry.archive(doc, "tax-2025")
        self.assertNotIn("tax-2025", registry.projects(doc))
        self.assertIn("tax-2025", registry.archived(doc))
        # cmirror would no longer see it; strata untouched
        self.assertIn("strata", registry.projects(doc))
        # top-level keys survive a serialize round-trip
        text = tomlkit.dumps(doc)
        self.assertIn("identity_file", text)
        reparsed = tomlkit.parse(text)
        self.assertEqual(
            reparsed["archived"]["tax-2025"]["working_dir"],
            "/Users/me/personal/tax-2025",
        )

        registry.restore(doc, "tax-2025")
        self.assertIn("tax-2025", registry.projects(doc))
        self.assertNotIn("tax-2025", registry.archived(doc))

    def test_archive_missing(self):
        doc = self.doc()
        with self.assertRaises(KeyError):
            registry.archive(doc, "nope")

    def test_encrypted_root_round_trip(self):
        doc = self.doc()
        self.assertIsNone(registry.encrypted_root(doc))
        registry.set_encrypted_root(doc, Path("/backups/tekas"))
        reparsed = tomlkit.parse(tomlkit.dumps(doc))
        self.assertEqual(registry.encrypted_root(reparsed), Path("/backups/tekas"))
        # cmirror's own keys and the project tables survive untouched.
        self.assertEqual(reparsed["identity_file"],
                         "/Users/me/.config/cmirror/identity.txt")
        self.assertEqual(set(registry.projects(reparsed)), {"strata", "tax-2025"})

    def test_rehome_missing_repoints_only_absent_active_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            existing = Path(tmp) / "elsewhere" / "strata"
            existing.mkdir(parents=True)
            doc = self.doc()
            doc["projects"]["strata"]["encrypted_dir"] = str(existing)
            registry.archive(doc, "tax-2025")            # archived: never rehomed
            registry.add(doc, "mila", "/wd/mila", "/gone/gd-sync/mila")
            moved = registry.rehome_missing(doc, root)
            self.assertEqual(moved,
                             [("mila", "/gone/gd-sync/mila", str(root / "mila"))])
            # An encrypted_dir that exists holds real ciphertext — kept as-is.
            self.assertEqual(doc["projects"]["strata"]["encrypted_dir"],
                             str(existing))
            self.assertEqual(doc["archived"]["tax-2025"]["encrypted_dir"],
                             "/Users/me/personal/gd-sync/tax-2025")
            # Idempotent: the repointed dir is merely pending its first backup.
            self.assertEqual(registry.rehome_missing(doc, root), [])


if __name__ == "__main__":
    unittest.main()
