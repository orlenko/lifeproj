import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from lifeproj import cli, route


def answers(depth, cost, prose=0.0, code=0.0, depth_conf=0.9, levels=None,
            cost_levels=None, care=0.0):
    return {
        "reasoning_depth": {"type": "score", "score": depth, "confidence": depth_conf,
                            "probabilities": levels or {}},
        "error_cost": {"type": "score", "score": cost, "confidence": 0.8,
                       "probabilities": cost_levels or {}},
        "asks_for_care": {"type": "noul", "noul": care},
        "writes_for_human": {"type": "noul", "noul": prose},
        "is_code": {"type": "noul", "noul": code},
    }


class DecideTest(unittest.TestCase):
    def tier(self, *a, **kw):
        return route.decide(answers(*a, **kw))[0]

    def test_tiers(self):
        self.assertEqual(self.tier(1.0, 1.2), "haiku")
        self.assertEqual(self.tier(1.0, 2.4), "sonnet")           # cheap to do, costly to botch
        self.assertEqual(self.tier(1.2, 1.0, prose=0.9), "sonnet")
        self.assertEqual(self.tier(2.3, 2.4, prose=0.9), "opus")
        self.assertEqual(self.tier(3.0, 1.6, code=0.9), "opus")
        self.assertEqual(self.tier(3.0, 2.75), "fable")

    def test_bump_follows_the_distribution_not_the_confidence(self):
        # Live, 2026-09-18: a one-word edit to an outbound draft. Split between
        # mechanical and moderate (confidence 0.30), nothing on deep. Prose makes
        # it sonnet; low confidence alone must not make it opus.
        edit = answers(0.70, 1.13, prose=0.56, depth_conf=0.30,
                       levels={"0": 0.57, "1": 0.16, "2": 0.27, "3": 0.00})
        self.assertEqual(route.decide(edit)[0], "sonnet")
        # Real weight on "deep" does bump sonnet to opus …
        tier, why = route.decide(answers(1.9, 1.0, levels={"1": 0.4, "2": 0.3, "3": 0.3}))
        self.assertEqual(tier, "opus")
        self.assertIn("bumped to opus", why[-1])
        # … and weight on moderate-or-deep bumps haiku to sonnet.
        self.assertEqual(route.decide(answers(1.2, 1.0, levels={"0": 0.3, "1": 0.3, "2": 0.4}))[0],
                         "sonnet")
        self.assertEqual(route.decide(answers(1.2, 1.0, depth_conf=0.2,
                                              levels={"0": 0.45, "1": 0.45, "2": 0.1}))[0], "haiku")


    def test_firm_costly_counts_without_weight_on_severe(self):
        # Live, 2026-09-18: "deep re-read … so I don't send something stupid".
        # 0.93 on "costly" scores 2.01, under the 2.25 score threshold.
        reread = answers(2.07, 2.01, prose=0.25, cost_levels={"1": 0.03, "2": 0.93, "3": 0.04})
        self.assertEqual(route.decide(reread)[0], "opus")
        self.assertEqual(self.tier(2.07, 2.01, cost_levels={"1": 0.5, "2": 0.5}), "sonnet")

    def test_author_asking_for_care_goes_up_one_tier(self):
        tier, why = route.decide(answers(2.0, 1.2, care=0.9))
        self.assertEqual(tier, "opus")
        self.assertIn("extra care", why[-1])
        self.assertEqual(self.tier(1.0, 1.0, care=0.9), "sonnet")
        # "make sure validation passes": careful, costly, but mechanical — sonnet is enough
        self.assertEqual(self.tier(0.8, 1.75, care=0.9, cost_levels={"2": 0.8}), "sonnet")
        self.assertEqual(self.tier(3.0, 1.0, care=0.9), "opus")     # never to fable on tone


class BuildRequestTest(unittest.TestCase):
    def test_shape_and_pinned_model(self):
        body = route.build_request("file this", domain="tax", facts={"files": 3})
        self.assertEqual(body["model"], route.JEV_MODEL)
        self.assertEqual(body["state"]["task"],
                         {"description": "file this", "teka_domain": "tax",
                          "known_facts": {"files": 3}})
        self.assertEqual(set(body["questions"]), set(route.QUESTIONS))

    def test_long_description_keeps_head_and_tail(self):
        text = "HEAD" + "x" * 50000 + "TAIL"
        clipped = route.clip(text)
        self.assertLess(len(clipped), route.MAX_DESCRIPTION_CHARS + 100)
        self.assertTrue(clipped.startswith("HEAD"))
        self.assertTrue(clipped.endswith("TAIL"))
        self.assertIn("omitted", clipped)


class RouteTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log = Path(tmp.name) / "log.jsonl"
        env = mock.patch.dict("os.environ", {"TYPESAFE_API_KEY": "k"})
        env.start()
        self.addCleanup(env.stop)

    def test_routes_and_logs(self):
        post = mock.Mock(return_value={"model": "jev-1.13.0", "answers": answers(3.0, 2.8)})
        result = route.route("plan the filing", log_path=self.log, post=post)
        self.assertEqual(result["model"], "fable")
        self.assertTrue(result["routed"])
        self.assertEqual(post.call_args[0][1], "k")
        entry = json.loads(self.log.read_text())
        self.assertEqual(entry["model"], "fable")
        self.assertEqual(entry["scores"]["reasoning_depth"], 3.0)

    def test_request_log_keeps_the_whole_exchange(self):
        reply = {"model": "jev-1.13.0", "answers": answers(3.0, 2.8),
                 "usage": {"input_tokens": 600, "output_tokens": 40}}
        route.route("plan the filing", log_path=self.log, post=mock.Mock(return_value=reply),
                    extra_state={"previous_assistant_reply": "file both?"},
                    log_fields={"kind": "prompt", "session": "s1"},
                    annotate=lambda r: {"delegate": True})
        decision = json.loads(self.log.read_text())
        exchange = json.loads((self.log.parent / route.REQUESTS_NAME).read_text())
        self.assertEqual(exchange["at"], decision["at"])
        self.assertEqual((exchange["kind"], exchange["session"]), ("prompt", "s1"))
        self.assertEqual(exchange["request"]["state"]["previous_assistant_reply"], "file both?")
        self.assertEqual(exchange["request"]["questions"], route.QUESTIONS)
        self.assertEqual(exchange["response"], reply)
        self.assertEqual(exchange["decision"], "fable")
        self.assertIs(exchange["delegate"], True)
        self.assertNotIn("k", json.dumps(exchange["request"]).split())  # no api key in the body

    def test_request_log_records_failures_and_rolls(self):
        route.route("x", log_path=self.log, post=mock.Mock(side_effect=TimeoutError("slow")))
        path = self.log.parent / route.REQUESTS_NAME
        exchange = json.loads(path.read_text())
        self.assertIn("TimeoutError", exchange["error"])
        self.assertIsNone(exchange["decision"])
        path.write_text("".join(f'{{"n": {i}}}\n' for i in range(route.REQUESTS_TRIM_AT)))
        route.route("x", log_path=self.log, post=mock.Mock(return_value={"answers": answers(1, 1)}))
        lines = path.read_text().splitlines()
        self.assertEqual(len(lines), route.REQUESTS_KEEP)
        self.assertEqual(json.loads(lines[-1])["decision"], "haiku")

    def test_service_failure_falls_back(self):
        for exc in (urllib.error.URLError("down"), TimeoutError(), ValueError("bad json")):
            result = route.route("x", log_path=self.log, post=mock.Mock(side_effect=exc))
            self.assertEqual((result["model"], result["routed"]), (route.FALLBACK, False))

    def test_malformed_reply_falls_back(self):
        result = route.route("x", log_path=self.log, post=mock.Mock(return_value={"answers": {}}))
        self.assertEqual(result["model"], route.FALLBACK)

    def test_no_key_never_calls_out(self):
        post = mock.Mock()
        with mock.patch.dict("os.environ", {}, clear=True):
            result = route.route("x", log_path=self.log, post=post)
        post.assert_not_called()
        self.assertEqual(result["model"], route.FALLBACK)

    def test_unwritable_log_is_ignored(self):
        post = mock.Mock(return_value={"answers": answers(1.0, 1.0)})
        result = route.route("x", log_path=Path("/dev/null/nope/log.jsonl"), post=post)
        self.assertEqual(result["model"], "haiku")


class HookTest(unittest.TestCase):
    def run_hook(self, event, routed):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps(event))), \
                mock.patch.object(route, "route", return_value=routed) as r, redirect_stdout(out):
            code = route.hook()
        return code, out.getvalue(), r

    def test_rewrites_model_and_keeps_the_rest(self):
        event = {"tool_name": "Agent", "cwd": "/nonexistent",
                 "tool_input": {"description": "d", "prompt": "p", "subagent_type": "Explore"}}
        code, out, r = self.run_hook(event, {"model": "haiku", "routed": True})
        self.assertEqual(code, 0)
        self.assertEqual(r.call_args[0][0], "d\n\np")
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["updatedInput"],
                         {"description": "d", "prompt": "p", "subagent_type": "Explore",
                          "model": "haiku"})

    def test_never_lowers_an_explicit_model(self):
        spawn = {"description": "d", "prompt": "p", "model": "opus"}
        _, out, _ = self.run_hook({"tool_name": "Agent", "tool_input": spawn},
                                  {"model": "sonnet", "routed": True})
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["updatedInput"]["model"], "opus")
        _, out, _ = self.run_hook({"tool_name": "Agent", "tool_input": {**spawn, "model": "haiku"}},
                                  {"model": "opus", "routed": True})
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["updatedInput"]["model"], "opus")

    def test_leaves_spawn_alone(self):
        spawn = {"description": "d", "prompt": "p"}
        for event, routed in (
                ({"tool_name": "Bash", "tool_input": {}}, {"model": "opus", "routed": True}),
                ({"tool_name": "Agent", "tool_input": {**spawn, "subagent_type": "fork"}},
                 {"model": "opus", "routed": True}),
                ({"tool_name": "Agent", "tool_input": spawn}, {"model": "sonnet", "routed": False}),
        ):
            self.assertEqual(self.run_hook(event, routed)[:2], (0, ""))


class PromptHookTest(unittest.TestCase):
    OPUS = {"model": "opus", "routed": True, "why": ["deep reasoning"]}

    def run_hook(self, prompt, scores, base=None, env=None, transcript=None):
        result = {**(base or self.OPUS), "scores": scores}
        event = {"prompt": prompt, "session_id": "s", "cwd": "/nonexistent",
                 "transcript_path": transcript}
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps(event))), \
                mock.patch.dict("os.environ", env or {}), \
                mock.patch.object(route, "route", return_value=result) as r, \
                redirect_stdout(out):
            self.assertEqual(route.prompt_hook(), 0)
        return out.getvalue(), r

    def test_delegates_standalone_work_above_the_driver(self):
        out, r = self.run_hook("plan the dispute", {"needs_conversation": 0.1, "is_conversation": 0.05})
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn('model "opus"', context)
        self.assertEqual(r.call_args.kwargs["log_fields"]["kind"], "prompt")

    def test_context_dependent_work_is_delegated_with_a_brief(self):
        # Live, 2026-09-18: "those three drafts are still valid in light of latest intake?"
        out, _ = self.run_hook("those three drafts…", {"needs_conversation": 0.83, "is_conversation": 0.1})
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("self-contained brief", context)
        self.assertNotIn("verbatim", context)

    def test_driver_keeps_the_rest(self):
        standalone = {"needs_conversation": 0.1, "is_conversation": 0.05}
        sonnet = {"model": "sonnet", "routed": True, "why": []}
        for scores, base, env in (
                ({"needs_conversation": 0.9, "is_conversation": 0.9}, None, None),   # "yes, both"
                ({"needs_conversation": 0.1, "is_conversation": 0.9}, None, None),   # "thanks"
                (standalone, sonnet, None),                       # at the driver's tier
                (standalone, None, {"LIFEPROJ_DRIVER": "opus"}),  # driver already opus
                ({}, {"model": "sonnet", "routed": False, "why": []}, None),  # Jev unreachable
        ):
            self.assertEqual(self.run_hook("x", scores, base, env)[0], "")

    def test_slash_commands_and_harness_events_never_reach_jev(self):
        for prompt in ("/wip", "<task-notification> <task-id>b1</task-id> …",
                       "  <system-reminder>x</system-reminder>",
                       "aiq moved this session to a fresh quota account; the conversation …"):
            out, r = self.run_hook(prompt, {})
            r.assert_not_called()
            self.assertEqual(out, "")

    def test_previous_reply_is_last_main_session_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            rows = [
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "first"}]}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "file both?"}]}},
                {"type": "assistant", "isSidechain": True,
                 "message": {"content": [{"type": "text", "text": "subagent chatter"}]}},
                {"type": "assistant", "message": {"content": [{"type": "tool_use"}]}},
                {"type": "user", "message": {"content": "yes"}},
            ]
            path.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
            self.assertEqual(route._previous_reply(str(path)), "file both?")
        self.assertIsNone(route._previous_reply(None))


class CliTest(unittest.TestCase):
    def test_prints_bare_model_on_stdout(self):
        fake = {"model": "opus", "routed": True, "why": ["deep reasoning"], "scores": {}}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(route, "route", return_value=fake), \
                redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["route", "debug the roll-up"])
        self.assertEqual((code, out.getvalue()), (0, "opus\n"))
        self.assertIn("deep reasoning", err.getvalue())


if __name__ == "__main__":
    unittest.main()
