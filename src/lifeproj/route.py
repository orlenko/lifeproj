"""`lifeproj route` — pick the subagent model for one task.

A session running on a mid-tier model spawns subagents on that same tier unless
something tells it otherwise. This module is that something: it sends the task
description to TypeSafe's Jev (a fast model that returns typed judgments, not
text), reads back four judgments, and maps them to a model tier in code.

Jev supplies the semantic part — how much reasoning the task needs, how bad an
unnoticed mistake would be, whether the output is prose for another person,
whether it is code. The policy is plain thresholds here, so it can be read,
tested, and tuned from the decision log without touching the questions.

Routing never blocks work: with no API key, no network, or a bad response the
answer is ``FALLBACK`` and the exit code is still 0.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

API_URL = "https://api.typesafe.ai/v1/systemone"
# Pinned, not `jev-latest`: the thresholds below were tuned against this
# version, and an alias moves without a change on our side.
JEV_MODEL = "jev-1.13.0"
TIMEOUT_S = 8

TIERS = ("haiku", "sonnet", "opus", "fable")
FALLBACK = "sonnet"

# Jev's accuracy drops when state carries more than the question needs, so the
# cap is far below its 32k-token limit. A long description keeps its head and
# tail: the ask is usually up front, the constraints at the end.
MAX_DESCRIPTION_CHARS = 6000

QUESTIONS = {
    "reasoning_depth": {
        "type": "score",
        "instructions": "How much multi-step reasoning does completing "
                        "`task.description` require from the agent that performs it?",
        "criteria": [
            "Mechanical: follow a fixed recipe, copy, rename, move or reformat "
            "with no judgment",
            "Light judgment: pick one of a few known categories or fill a known "
            "schema from clearly stated facts",
            "Moderate: reconcile several sources, resolve ambiguity, or write a "
            "short text a person will read",
            "Deep: design a plan, weigh trade-offs with legal, financial or "
            "irreversible consequences, or debug an unknown cause",
        ],
    },
    "error_cost": {
        "type": "score",
        "instructions": "If the agent performs `task.description` wrongly and "
                        "nobody notices for a week, how bad is the result?",
        "criteria": [
            "Harmless: a misfiled note or cosmetic mistake, fixed in a minute",
            "Annoying: some rework or a confusing record",
            "Costly: a missed deadline, lost money, or a wrong message reaching "
            "another person",
            "Severe: legal, tax, immigration or health consequences that are "
            "hard to undo",
        ],
    },
    "writes_for_human": {
        "type": "noul",
        "instructions": "Does `task.description` ask the agent to write prose "
                        "that will be sent to or read by a person other than the owner?",
    },
    "is_code": {
        "type": "noul",
        "instructions": "Does `task.description` ask the agent to write or "
                        "change program code?",
    },
}

# Policy thresholds. Scores run 0–3 over the levels above; nouls are P(yes).
DEEP = 2.5          # reasoning_depth at or above this needs opus
MODERATE = 1.75     # ... and this needs sonnet
COSTLY = 2.25       # error_cost at or above this raises the floor
SEVERE = 2.5        # with DEEP, this is a fable task
PROSE = 0.5
UNSURE = 0.5        # depth confidence below this bumps one tier


def clip(text: str, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return f"{text[:head]}\n[… {len(text) - limit} characters omitted …]\n{text[-tail:]}"


def build_request(description: str, *, domain: Optional[str] = None,
                  facts: Optional[dict] = None) -> dict:
    """The exact body sent to Jev. ``facts`` are things code already knows
    (file count, outbound or not) that the spawning session may have left out."""
    task = {"description": clip(description)}
    if domain:
        task["teka_domain"] = domain
    if facts:
        task["known_facts"] = facts
    return {"state": {"task": task}, "model": JEV_MODEL, "questions": QUESTIONS}


def decide(answers: dict) -> tuple[str, list]:
    """Map Jev's answers to a tier. Pure; raises KeyError on a malformed reply."""
    depth = answers["reasoning_depth"]["score"]
    depth_conf = answers["reasoning_depth"]["confidence"]
    cost = answers["error_cost"]["score"]
    prose = answers["writes_for_human"]["noul"]

    if depth >= DEEP and cost >= SEVERE:
        tier, why = "fable", ["deep reasoning with severe error cost"]
    elif depth >= DEEP:
        tier, why = "opus", ["deep reasoning"]
    elif depth >= MODERATE and (cost >= COSTLY or prose >= PROSE):
        tier, why = "opus", ["moderate reasoning on costly or outbound work"]
    elif depth >= MODERATE or cost >= COSTLY or prose >= PROSE:
        tier, why = "sonnet", ["moderate reasoning, costly error, or outbound prose"]
    else:
        tier, why = "haiku", ["mechanical or light judgment, cheap to get wrong"]

    if depth_conf < UNSURE and tier in ("haiku", "sonnet"):
        tier = TIERS[TIERS.index(tier) + 1]
        why.append(f"depth confidence {depth_conf:.2f} < {UNSURE}: bumped one tier")
    return tier, why


def _post(body: dict, api_key: str) -> dict:
    req = urllib.request.Request(
        API_URL, json.dumps(body).encode(),
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
         "User-Agent": "lifeproj-route"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.load(resp)


def default_log_path() -> Path:
    return Path.home() / ".local" / "share" / "lifeproj" / "route-log.jsonl"


def _log(entry: dict, path: Optional[Path]) -> None:
    """Best-effort: a sandboxed session may not be able to write here."""
    try:
        path = path or default_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def route(description: str, *, domain: Optional[str] = None,
          facts: Optional[dict] = None, log_path: Optional[Path] = None,
          post: Callable[[dict, str], dict] = _post) -> dict:
    """Decide a tier for one task. Never raises for service trouble."""
    result = {"model": FALLBACK, "routed": False, "why": [], "scores": {}}
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not description.strip():
        result["why"] = ["empty task description"]
    elif not api_key:
        result["why"] = ["TYPESAFE_API_KEY not set"]
    else:
        try:
            reply = post(build_request(description, domain=domain, facts=facts), api_key)
            answers = reply["answers"]
            result["model"], result["why"] = decide(answers)
            result["routed"] = True
            result["jev"] = reply.get("model")
            result["scores"] = {
                "reasoning_depth": round(answers["reasoning_depth"]["score"], 2),
                "depth_confidence": round(answers["reasoning_depth"]["confidence"], 2),
                "error_cost": round(answers["error_cost"]["score"], 2),
                "writes_for_human": round(answers["writes_for_human"]["noul"], 2),
                "is_code": round(answers["is_code"]["noul"], 2),
            }
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
            result["why"] = [f"routing failed ({type(exc).__name__}: {exc}); using fallback"]

    _log({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
          "domain": domain, "description": clip(description, 500), **result}, log_path)
    return result


SPAWN_TOOLS = ("Agent", "Task")


def hook(log_path: Optional[Path] = None) -> int:
    """Claude Code PreToolUse hook: read the pending subagent spawn on stdin and
    rewrite its ``model``. Anything unexpected prints nothing, which leaves the
    spawn exactly as the session wrote it."""
    try:
        event = json.load(sys.stdin)
        tool_input = event["tool_input"]
        if event.get("tool_name") not in SPAWN_TOOLS:
            return 0
        # A fork always runs on the parent's model; an override is ignored.
        if tool_input.get("subagent_type") == "fork":
            return 0
        description = "\n\n".join(
            t for t in (tool_input.get("description"), tool_input.get("prompt")) if t)
    except (ValueError, KeyError, TypeError, AttributeError):
        return 0
    result = route(description, domain=_teka_domain(event.get("cwd")), log_path=log_path)
    if not result["routed"]:
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "updatedInput": {**tool_input, "model": result["model"]},
    }}))
    return 0


def _teka_domain(cwd: Optional[str]) -> Optional[str]:
    try:
        meta = json.loads((Path(cwd) / "catalog.json").read_text())["meta"]
        return meta.get("domain")
    except (OSError, ValueError, KeyError, TypeError):
        return None


def main(description: Optional[str], *, domain: Optional[str] = None,
         as_json: bool = False, log_path: Optional[Path] = None) -> int:
    if description is None or description == "-":
        description = sys.stdin.read()
    result = route(description, domain=domain, log_path=log_path)
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result["model"])
        for line in result["why"]:
            print(f"  {line}", file=sys.stderr)
    return 0
