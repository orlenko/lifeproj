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

    def _outbox(self, spool, teka, payload):
        d = spool / "outbox"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{teka}.intake.json").write_text(json.dumps(payload))

    def test_drain_applies_done_and_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = _teka(tmp, [
                {"id": "demo-1", "title": "A", "status": "open", "priority": "high", "due": "2026-07-01"},
                {"id": "demo-2", "title": "B", "status": "open", "priority": "low", "no_deadline": True},
                {"id": "demo-3", "title": "C", "status": "open", "priority": "normal", "no_deadline": True},
            ])
            spool = Path(tmp) / "spool"
            self._outbox(spool, "demo", {"teka": "demo", "completions": [
                {"id": "demo-1", "action": "done", "at": "2026-07-01T00:00:00Z", "source": "google-tasks-via-osavul"},
                {"id": "demo-2", "action": "dropped", "at": "2026-07-01T00:00:00Z"},
            ]})
            with mock.patch.dict(os.environ, {"OSAVUL_SPOOL": str(spool)}):
                self.assertEqual(osavul.drain(wd), 0)
            cat = json.loads((wd / "catalog.json").read_text())
            self.assertEqual([i["id"] for i in cat["open_items"]], ["demo-3"])
            self.assertEqual({e["id"]: e["action"] for e in cat["processing_log"]},
                             {"demo-1": "done", "demo-2": "dropped"})
            self.assertFalse((spool / "outbox" / "demo.intake.json").exists())  # fully consumed

    def test_drain_resolves_prefixed_slice_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = _teka(tmp, [{"id": "item-0001", "title": "A", "status": "open",
                              "priority": "high", "due": "2026-07-01"}])
            spool = Path(tmp) / "spool"
            self._outbox(spool, "demo", {"completions": [
                {"id": "demo-item-0001", "action": "done", "at": "t"}]})  # teka-prefixed slice id
            with mock.patch.dict(os.environ, {"OSAVUL_SPOOL": str(spool)}):
                self.assertEqual(osavul.drain(wd), 0)
            cat = json.loads((wd / "catalog.json").read_text())
            self.assertEqual(cat["open_items"], [])
            self.assertEqual(cat["processing_log"][-1]["id"], "item-0001")

    def test_drain_idempotent_and_preserves_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = _teka(tmp, [{"id": "demo-1", "title": "A", "status": "open",
                              "priority": "high", "due": "2026-07-01"}])
            spool = Path(tmp) / "spool"
            self._outbox(spool, "demo", {"items": [{"title": "routed"}], "completions": [
                {"id": "demo-1", "action": "done", "at": "t"},
                {"id": "demo-unknown", "action": "done", "at": "t"}]})
            with mock.patch.dict(os.environ, {"OSAVUL_SPOOL": str(spool)}):
                self.assertEqual(osavul.drain(wd), 0)
                self.assertEqual(osavul.drain(wd), 0)  # re-run: nothing new, no double-apply
            cat = json.loads((wd / "catalog.json").read_text())
            self.assertEqual(cat["open_items"], [])
            ob = json.loads((spool / "outbox" / "demo.intake.json").read_text())
            self.assertEqual(ob["items"], [{"title": "routed"}])                 # items[] preserved
            self.assertEqual([c["id"] for c in ob["completions"]], ["demo-unknown"])  # applied gone, unknown lingers

    def test_drain_no_outbox_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = _teka(tmp, GOOD)
            spool = Path(tmp) / "spool"
            spool.mkdir()
            with mock.patch.dict(os.environ, {"OSAVUL_SPOOL": str(spool)}):
                self.assertEqual(osavul.drain(wd), 0)
            self.assertEqual(len(json.loads((wd / "catalog.json").read_text())["open_items"]), 1)

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
