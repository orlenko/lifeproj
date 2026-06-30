import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lifeproj import osavul, scaffold


def _teka(tmp, open_items):
    plan = scaffold.build(
        "demo", Path(tmp) / "demo", Path(tmp) / "gd" / "demo",
        domain="general", lifecycle="ongoing", summary="A demo teka.",
        modules=["osavul"], created="2026-06-30", register=False,
    )
    wd = Path(scaffold.apply(plan)["working_dir"])
    catalog = json.loads((wd / "catalog.json").read_text())
    catalog["open_items"] = open_items
    (wd / "catalog.json").write_text(json.dumps(catalog, indent=2))
    return wd


GOOD = [{"id": "demo-2026-001", "title": "File AGM notice", "status": "open",
         "priority": "high", "due": "2026-07-05", "tags": ["agm"]}]


class OsavulTests(unittest.TestCase):
    def test_validate_flags_each_rule(self):
        self.assertEqual(osavul.validate_open_items(GOOD), [])
        bad = [dict(GOOD[0], due=None)]                       # neither due nor no_deadline
        self.assertTrue(osavul.validate_open_items(bad))
        self.assertTrue(osavul.validate_open_items([dict(GOOD[0], status="x")]))
        self.assertTrue(osavul.validate_open_items([dict(GOOD[0], status="blocked")]))
        # reused id (already in processing_log)
        self.assertTrue(osavul.validate_open_items(GOOD, [{"id": "demo-2026-001"}]))

    def test_project_slice_shape(self):
        catalog = {"meta": {"name": "demo", "lifecycle": "ongoing"}, "open_items": GOOD}
        s = osavul.project_slice(catalog, Path("/x/demo"), now="2026-06-30T00:00:00Z")
        self.assertEqual(s["teka"], "demo")
        self.assertEqual(s["lifecycle"], "ongoing")
        self.assertIsNone(s["active_chapter"])
        self.assertEqual(s["generated"], "2026-06-30T00:00:00Z")
        item = s["items"][0]
        self.assertEqual(set(item), set(osavul.ITEM_FIELDS))
        self.assertIs(item["no_deadline"], False)

    def test_active_chapters_projection(self):
        def slice_for(meta):
            return osavul.project_slice({"meta": {"name": "demo", **meta}},
                                        Path("/x/demo"), now="t")
        # single active chapter -> carried in the array AND auto-filled into active_chapter
        s = slice_for({"active_chapters": ["leak-2026"]})
        self.assertEqual(s["active_chapters"], ["leak-2026"])
        self.assertEqual(s["active_chapter"], "leak-2026")
        # many -> array carries all; active_chapter stays null
        s = slice_for({"active_chapters": ["str-claim", "leak-2026"]})
        self.assertEqual(s["active_chapters"], ["str-claim", "leak-2026"])
        self.assertIsNone(s["active_chapter"])
        # fallback to meta.current_chapters for tekas mid-migration
        s = slice_for({"current_chapters": ["leak-2026"]})
        self.assertEqual(s["active_chapters"], ["leak-2026"])
        # none -> empty list + null
        s = slice_for({})
        self.assertEqual(s["active_chapters"], [])
        self.assertIsNone(s["active_chapter"])

    def test_id_prefix_is_idempotent(self):
        cat = {"meta": {"name": "strata"}, "open_items": [
            {"id": "item-0001", "title": "x", "status": "open", "priority": "high", "due": "2026-07-01"},
            {"id": "strata-2026-002", "title": "y", "status": "open", "priority": "low", "no_deadline": True},
        ]}
        ids = [i["id"] for i in osavul.project_slice(cat, Path("/x/strata"), now="t")["items"]]
        self.assertEqual(ids, ["strata-item-0001", "strata-2026-002"])  # added once, not doubled

    def test_redaction_projection(self):
        cat = {"meta": {"name": "strata"}, "open_items": [
            {"id": "strata-1", "title": "Dispute w/ Catriona", "status": "waiting",
             "priority": "high", "no_deadline": True, "waiting_on": "Catriona/Edward",
             "redact": True, "tags": ["needs-date"]},
            {"id": "strata-2", "title": "Real title", "slice_title": "Roof matter",
             "status": "open", "priority": "normal", "due": "2026-07-01"},
        ]}
        a, b = osavul.project_slice(cat, Path("/x/strata"), now="t")["items"]
        self.assertEqual(a["title"], "[redacted]")
        self.assertEqual(a["waiting_on"], "[party]")
        self.assertEqual(a["tags"], ["needs-date"])   # functional tags preserved
        self.assertEqual(b["title"], "Roof matter")   # slice_title wins
        self.assertIsNone(b["waiting_on"])            # not redacted

    def test_validate_redact_and_slice_title_types(self):
        base = dict(GOOD[0])
        self.assertTrue(osavul.validate_open_items([dict(base, redact="true")]))   # str, not bool
        self.assertTrue(osavul.validate_open_items([dict(base, slice_title="")]))  # empty
        self.assertEqual(osavul.validate_open_items([dict(base, redact=True, slice_title="ok")]), [])

    def test_publish_writes_valid_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = _teka(tmp, GOOD)
            spool = Path(tmp) / "spool"
            spool.mkdir()  # provisioned
            with mock.patch.dict(os.environ, {"OSAVUL_SPOOL": str(spool)}):
                rc = osavul.publish(wd, now="2026-06-30T00:00:00Z")
            self.assertEqual(rc, 0)
            out = spool / "inbox" / "demo.agenda.json"
            self.assertTrue(out.exists())
            slice_obj = json.loads(out.read_text())
            self.assertEqual(slice_obj["teka"], "demo")
            self.assertEqual(len(slice_obj["items"]), 1)
            self.assertEqual(osavul.validate_open_items(slice_obj["items"]), [])

    def test_publish_noop_when_spool_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = _teka(tmp, GOOD)
            missing = Path(tmp) / "not-granted"
            with mock.patch.dict(os.environ, {"OSAVUL_SPOOL": str(missing)}):
                rc = osavul.publish(wd, now="2026-06-30T00:00:00Z")
            self.assertEqual(rc, 0)            # no-op, not an error
            self.assertFalse(missing.exists())  # did not create the spool

    def test_publish_rejects_invalid_open_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = _teka(tmp, [dict(GOOD[0], due=None)])  # invalid: dateless
            spool = Path(tmp) / "spool"
            spool.mkdir()
            with mock.patch.dict(os.environ, {"OSAVUL_SPOOL": str(spool)}):
                rc = osavul.publish(wd)
            self.assertEqual(rc, 1)
            self.assertFalse((spool / "inbox" / "demo.agenda.json").exists())

    def test_drain_stub_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = _teka(tmp, GOOD)
            spool = Path(tmp) / "spool"
            with mock.patch.dict(os.environ, {"OSAVUL_SPOOL": str(spool)}):
                rc = osavul.drain(wd)
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
