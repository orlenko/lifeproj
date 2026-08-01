import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from lifeproj import brief, cli, registry

TODAY = date(2026, 7, 31)
NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)
FRESH = "2026-07-31T09:00:00Z"


def item(iid, title, **kw):
    """One published slice item — the frozen contract's shape."""
    it = {"id": iid, "title": title, "status": "open", "priority": "normal",
          "due": None, "no_deadline": True, "tags": [], "waiting_on": None,
          "link": None}
    it.update(kw)
    if it["due"]:
        it["no_deadline"] = False
    return it


class BriefTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.spool = self.tmp / "spool"
        self.inbox = self.spool / "inbox"
        self.config = self.tmp / "config.toml"

    def register(self, *names, archived=()):
        doc = registry.load(self.config)
        for name in (*names, *archived):
            registry.add(doc, name, str(self.tmp / name), str(self.tmp / "enc" / name))
        for name in archived:
            registry.archive(doc, name)
        registry.save(doc, self.config)

    def publish(self, teka, items, generated=FRESH):
        self.inbox.mkdir(parents=True, exist_ok=True)
        (self.inbox / f"{teka}.agenda.json").write_text(json.dumps({
            "teka": teka, "lifecycle": "ongoing", "active_chapters": [],
            "generated": generated, "items": items}))

    def complete(self, teka, ids):
        outbox = self.spool / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        (outbox / f"{teka}.intake.json").write_text(json.dumps(
            {"completions": [{"id": i, "action": "done"} for i in ids]}))

    def collect(self, **kw):
        kw.setdefault("today", TODAY)
        kw.setdefault("now", NOW)
        return brief.collect(self.config, spool=self.spool, **kw)


class BriefCollectTests(BriefTestCase):
    def test_items_land_in_urgency_buckets(self):
        self.register("alpha")
        self.publish("alpha", [
            item("a1", "late", due="2026-07-01"),
            item("a2", "now", due="2026-07-31"),
            item("a3", "soon", due="2026-08-05"),
            item("a4", "far", due="2026-09-30"),
            item("a5", "someday"),
            item("a6", "theirs", status="waiting", waiting_on="counsel",
                 due="2026-08-02"),
            item("a7", "closed", status="done", due="2026-07-02"),
        ])
        buckets = {i["title"]: i["bucket"] for i in self.collect()["items"]}
        self.assertEqual(buckets, {
            "late": "overdue", "now": "today", "soon": "soon", "far": "later",
            "someday": "undated", "theirs": "waiting"})
        # A done item is nobody's Monday morning.
        self.assertNotIn("closed", buckets)

    def test_waiting_wins_over_the_date_bucket(self):
        """An item parked on someone else belongs in the waiting section even
        when it is overdue — chasing it is a different act from doing it."""
        self.register("alpha")
        self.publish("alpha", [item("a1", "blocked one", status="blocked",
                                    waiting_on="the city", due="2026-01-01")])
        self.assertEqual(self.collect()["items"][0]["bucket"], "waiting")

    def test_sources_report_stale_never_published_and_undrained(self):
        self.register("alpha", "beta")
        self.publish("alpha", [item("a1", "thing")],
                     generated="2026-07-20T15:39:36Z")
        self.complete("alpha", ["alpha-a1"])
        data = self.collect()
        sources = {s["teka"]: s for s in data["sources"]}
        self.assertEqual(sources["alpha"]["state"], "stale")
        self.assertEqual(round(sources["alpha"]["age_days"]), 11)
        self.assertEqual(sources["alpha"]["pending_completions"], 1)
        self.assertEqual(sources["beta"]["state"], "never-published")

        text = brief.render(data)
        self.assertIn("alpha: slice is 11d old", text)
        self.assertIn("beta: no slice published yet", text)
        self.assertIn("1 completion(s) not drained", text)

    def test_fresh_slice_is_not_flagged(self):
        self.register("alpha")
        self.publish("alpha", [item("a1", "thing")])
        source = self.collect()["sources"][0]
        self.assertEqual(source["state"], "ok")
        self.assertNotIn("Notes", brief.render(self.collect()))

    def test_orphan_slices_are_named_not_briefed(self):
        """A slice with no active teka (archived, or another tool's) must never
        silently contribute items — but must never be silently dropped either."""
        self.register("alpha", archived=("tax-2025",))
        self.publish("alpha", [item("a1", "mine")])
        self.publish("tax-2025", [item("t1", "last year")])
        self.publish("stranger", [item("s1", "not a teka")])
        data = self.collect()
        self.assertEqual([i["title"] for i in data["items"]], ["mine"])
        self.assertEqual(data["orphans"], ["stranger", "tax-2025 (archived)"])
        self.assertIn("slices with no active teka", brief.render(data))

    def test_tolerates_offset_stamps_and_sparse_items(self):
        """Real slices deviate: one publisher stamps a UTC offset instead of Z
        and omits optional item fields entirely."""
        self.register("alpha")
        self.publish("alpha", [{"id": "a1", "title": "sparse", "status": "open",
                                "priority": "high", "no_deadline": True}],
                     generated="2026-07-30T16:46:35-04:00")
        data = self.collect()
        self.assertEqual(data["sources"][0]["state"], "ok")
        self.assertLess(data["sources"][0]["age_days"], 2)
        self.assertEqual(data["items"][0]["bucket"], "undated")
        self.assertEqual(data["items"][0]["priority"], "high")

    def test_unparseable_due_is_undated_never_dropped(self):
        self.register("alpha")
        self.publish("alpha", [item("a1", "vague", due="sometime in August")])
        self.assertEqual(self.collect()["items"][0]["bucket"], "undated")

    def test_days_horizon_keeps_overdue_drops_undated(self):
        self.register("alpha")
        self.publish("alpha", [
            item("a1", "late", due="2026-06-01"),
            item("a2", "close", due="2026-08-03"),
            item("a3", "far", due="2026-09-30"),
            item("a4", "someday"),
        ])
        titles = [i["title"] for i in self.collect(days=7)["items"]]
        self.assertEqual(titles, ["late", "close"])

    def test_teka_filter_and_unknown_names(self):
        self.register("alpha", "beta")
        self.publish("alpha", [item("a1", "mine")])
        self.publish("beta", [item("b1", "theirs")])
        data = self.collect(tekas=["alpha", "nope"])
        self.assertEqual([i["title"] for i in data["items"]], ["mine"])
        self.assertEqual(data["unknown"], ["nope"])

    def test_unreadable_registry_falls_back_to_the_spool(self):
        """A sandboxed teka session grants the spool but not cmirror's config;
        the brief still works there, and says what it could not check."""
        self.register("alpha")
        self.publish("alpha", [item("a1", "mine")])
        self.publish("beta", [item("b1", "also briefed")])
        data = brief.collect(self.tmp, spool=self.spool, today=TODAY, now=NOW)
        self.assertEqual(sorted(i["title"] for i in data["items"]),
                         ["also briefed", "mine"])
        self.assertEqual(data["orphans"], [])
        self.assertIn("registry unreadable", " ".join(data["notes"]))

    def test_missing_spool_is_a_note_not_a_crash(self):
        self.register("alpha")
        data = self.collect()
        self.assertEqual(data["items"], [])
        self.assertIn("no agenda spool", " ".join(data["notes"]))
        self.assertIn("Nothing open", brief.render(data))


class BriefRenderTests(BriefTestCase):
    def test_long_titles_are_clipped_unless_full(self):
        self.register("alpha")
        long_title = "Confirm CRA's required instalment amount " * 6
        self.publish("alpha", [item("a1", long_title, due="2026-08-02")])
        data = self.collect()
        clipped = brief.render(data)
        self.assertIn("…", clipped)
        self.assertTrue(all(len(line) < 160 for line in clipped.splitlines()))
        self.assertIn(long_title.strip(), brief.render(data, full=True))

    def test_sections_and_priority_marker(self):
        self.register("alpha")
        self.publish("alpha", [
            item("a1", "urgent thing", due="2026-07-01", priority="high"),
            item("a2", "calm thing", due="2026-07-01"),
        ])
        text = brief.render(self.collect())
        self.assertIn("OVERDUE", text)
        self.assertIn("! 2026-07-01  alpha  urgent thing", text)
        self.assertIn("  2026-07-01  alpha  calm thing", text)


class BriefCliTests(BriefTestCase):
    def _run(self, argv):
        out = io.StringIO()
        with mock.patch.dict("os.environ", {"OSAVUL_SPOOL": str(self.spool)}):
            with redirect_stdout(out):
                rc = cli.main(argv + ["--config", str(self.config)])
        return rc, out.getvalue()

    def test_json_output_is_machine_readable(self):
        self.register("alpha")
        self.publish("alpha", [item("a1", "mine")])
        rc, out = self._run(["brief", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["items"][0]["title"], "mine")

    def test_unknown_teka_is_an_error_not_an_empty_brief(self):
        self.register("alpha")
        self.publish("alpha", [item("a1", "mine")])
        rc, out = self._run(["brief", "--teka", "typo"])
        self.assertEqual(rc, 1)
        self.assertIn("unknown teka(s): typo", out)


if __name__ == "__main__":
    unittest.main()
