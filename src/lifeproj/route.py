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
    "asks_for_care": {
        "type": "noul",
        "instructions": "Does the author of `task.description` explicitly ask for "
                        "extra care or thoroughness, or say they are worried about "
                        "getting it wrong?",
        "criteria": {
            "true": "Words like 'deep check', 'deep re-read', 'carefully', "
                    "'double-check', 'thorough', or a stated worry such "
                    "as 'so we don't embarrass ourselves' or 'so I don't send "
                    "something stupid'",
            "false": "A plain request with no comment on how carefully to do it",
        },
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
COSTLY_CONSENSUS = 0.6  # ... as does this much probability on "costly" or "severe":
                        # a firm "costly" scores 2.0 and would never reach COSTLY
PROSE = 0.5
CARE = 0.5          # the author asked for extra care: one tier up, at most opus
CARE_DEPTH = 1.5    # ... but care about a mechanical step doesn't need opus
# A split depth judgment bumps one tier only when real probability sits on
# levels the chosen tier is too small for. (Confidence alone is the wrong
# signal: a split between "mechanical" and "moderate" is low-confidence and
# still nowhere near opus.)
BUMP_TO_SONNET = 0.35   # haiku → sonnet when P(moderate or deep) reaches this
BUMP_TO_OPUS = 0.25     # sonnet → opus when P(deep) reaches this


def clip(text: str, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return f"{text[:head]}\n[… {len(text) - limit} characters omitted …]\n{text[-tail:]}"


def build_request(description: str, *, domain: Optional[str] = None,
                  facts: Optional[dict] = None, extra_state: Optional[dict] = None,
                  extra_questions: Optional[dict] = None) -> dict:
    """The exact body sent to Jev. ``facts`` are things code already knows
    (file count, outbound or not) that the spawning session may have left out."""
    task = {"description": clip(description)}
    if domain:
        task["teka_domain"] = domain
    if facts:
        task["known_facts"] = facts
    return {"state": {"task": task, **(extra_state or {})}, "model": JEV_MODEL,
            "questions": {**QUESTIONS, **(extra_questions or {})}}


def decide(answers: dict) -> tuple[str, list]:
    """Map Jev's answers to a tier. Pure; raises KeyError on a malformed reply."""
    depth = answers["reasoning_depth"]["score"]
    cost = answers["error_cost"]["score"]
    prose = answers["writes_for_human"]["noul"]
    cost_levels = answers["error_cost"].get("probabilities") or {}
    costly = (cost >= COSTLY or
              cost_levels.get("2", 0.0) + cost_levels.get("3", 0.0) >= COSTLY_CONSENSUS)

    if depth >= DEEP and cost >= SEVERE:
        tier, why = "fable", ["deep reasoning with severe error cost"]
    elif depth >= DEEP:
        tier, why = "opus", ["deep reasoning"]
    elif depth >= MODERATE and (costly or prose >= PROSE):
        tier, why = "opus", ["moderate reasoning on costly or outbound work"]
    elif depth >= MODERATE or costly or prose >= PROSE:
        tier, why = "sonnet", ["moderate reasoning, costly error, or outbound prose"]
    else:
        tier, why = "haiku", ["mechanical or light judgment, cheap to get wrong"]

    levels = answers["reasoning_depth"].get("probabilities") or {}
    p_deep = levels.get("3", 0.0)
    p_moderate_up = p_deep + levels.get("2", 0.0)
    if tier == "haiku" and p_moderate_up >= BUMP_TO_SONNET:
        tier = "sonnet"
        why.append(f"P(moderate or deep) {p_moderate_up:.2f} ≥ {BUMP_TO_SONNET}: bumped to sonnet")
    elif tier == "sonnet" and p_deep >= BUMP_TO_OPUS:
        tier = "opus"
        why.append(f"P(deep) {p_deep:.2f} ≥ {BUMP_TO_OPUS}: bumped to opus")
    care = answers.get("asks_for_care", {}).get("noul", 0.0)
    if care >= CARE and (tier == "haiku" or (tier == "sonnet" and depth >= CARE_DEPTH)):
        tier = TIERS[TIERS.index(tier) + 1]
        why.append(f"author asked for extra care ({care:.2f}): up one tier")
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


REQUESTS_NAME = "route-requests.jsonl"
# The request log holds full prompt text, so it is a rolling window, not an
# archive: once it passes REQUESTS_TRIM_AT lines it is cut back to REQUESTS_KEEP.
REQUESTS_KEEP = 500
REQUESTS_TRIM_AT = 600


def _log_request(entry: dict, log_path: Optional[Path]) -> None:
    """While Jev is under evaluation: the exact body sent and the raw reply (or
    the error), next to the decision log and joined to it by ``at``. Best-effort
    like `_log`."""
    try:
        path = (log_path or default_log_path()).with_name(REQUESTS_NAME)
        if str(log_path) == os.devnull:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        lines = path.read_text().splitlines(keepends=True)
        if len(lines) > REQUESTS_TRIM_AT:
            tmp = path.with_suffix(".tmp")
            tmp.write_text("".join(lines[-REQUESTS_KEEP:]))
            tmp.replace(path)
    except OSError:
        pass


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
          extra_state: Optional[dict] = None, extra_questions: Optional[dict] = None,
          log_fields: Optional[dict] = None,
          annotate: Optional[Callable[[dict], dict]] = None,
          post: Callable[[dict, str], dict] = _post) -> dict:
    """Decide a tier for one task. Never raises for service trouble. Nouls asked
    through ``extra_questions`` come back in ``scores`` under their ids."""
    result = {"model": FALLBACK, "routed": False, "why": [], "scores": {}}
    at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not description.strip():
        result["why"] = ["empty task description"]
    elif not api_key:
        result["why"] = ["TYPESAFE_API_KEY not set"]
    else:
        body = build_request(description, domain=domain, facts=facts,
                             extra_state=extra_state, extra_questions=extra_questions)
        exchange = {"at": at, **(log_fields or {}), "request": body}
        started = datetime.datetime.now()
        try:
            reply = post(body, api_key)
            exchange["response"] = reply
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
                "asks_for_care": round(answers["asks_for_care"]["noul"], 2),
                **{qid: round(answers[qid]["noul"], 2) for qid in (extra_questions or {})},
            }
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
            result["why"] = [f"routing failed ({type(exc).__name__}: {exc}); using fallback"]
            exchange["error"] = f"{type(exc).__name__}: {exc}"
        exchange["ms"] = round((datetime.datetime.now() - started).total_seconds() * 1000)
        exchange["decision"] = result["model"] if result["routed"] else None
        exchange.update(annotate(result) if annotate else {})
        _log_request(exchange, log_path)

    _log({"at": at,
          "domain": domain, "description": clip(description, 500), **result,
          **(log_fields or {}), **(annotate(result) if annotate else {})}, log_path)
    return result


SPAWN_TOOLS = ("Agent", "Task")


def _tier_of(model: Optional[str]) -> Optional[str]:
    """'opus', 'claude-opus-5', 'opus[1m]' → 'opus'; 'inherit' or unknown → None."""
    model = (model or "").lower()
    return next((t for t in TIERS if t in model), None)


def _agent_dirs(cwd: Optional[str]) -> list:
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    dirs = [config / "agents"]
    if cwd:
        here = Path(cwd)
        dirs = [d / ".claude" / "agents" for d in (here, *here.parents)] + dirs
    return dirs + sorted(config.glob("plugins/**/agents"))


def agent_definition_tier(subagent_type: Optional[str], cwd: Optional[str]) -> Optional[str]:
    """The tier an agent definition pins in its frontmatter (`model: opus`).
    Someone chose that model for that agent; an explicit `model` on the spawn
    overrides the frontmatter, so without this the hook would lower it.
    Best-effort: a definition we can't find or read pins nothing."""
    if not subagent_type:
        return None
    name = subagent_type.split(":")[-1]        # plugin agents are "plugin:agent"
    try:
        for directory in _agent_dirs(cwd):
            for path in sorted(directory.glob("*.md")):
                head = path.read_text(errors="replace").split("---", 2)
                if len(head) < 3:
                    continue
                fields = dict(line.split(":", 1) for line in head[1].splitlines() if ":" in line)
                declared = fields.get("name", "").strip().strip("\"'") or path.stem
                if declared == name:
                    return _tier_of(fields.get("model", "").strip().strip("\"'"))
    except OSError:
        pass
    return None


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
    result = route(description, domain=_teka_domain(event.get("cwd")), log_path=log_path,
                   log_fields={"kind": "spawn", "session": event.get("session_id")})
    if not result["routed"]:
        return 0
    # A session leaves `model` unset unless someone chose one — the user ("spawn
    # an Opus subagent") or the prompt hook's instruction — and an agent
    # definition may pin one. Routing may raise those choices, never lower them.
    model = result["model"]
    for chosen in (_tier_of(tool_input.get("model")),
                   agent_definition_tier(tool_input.get("subagent_type"), event.get("cwd"))):
        if chosen and TIERS.index(chosen) > TIERS.index(model):
            model = chosen
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "updatedInput": {**tool_input, "model": model},
    }}))
    return 0


PROMPT_QUESTIONS = {
    "needs_conversation": {
        "type": "noul",
        "instructions": "Does understanding `task.description` require "
                        "`previous_assistant_reply`?",
        "criteria": {
            "true": "It answers, accepts, rejects or asks about something in "
                    "`previous_assistant_reply`, or uses words like 'yes', 'that', "
                    "'both', 'the second one', 'again' that only make sense after it",
            "false": "It states what to do and what to do it to in its own words; "
                     "`previous_assistant_reply` could be deleted without losing "
                     "meaning",
        },
    },
    "is_conversation": {
        "type": "noul",
        "instructions": "Can `task.description` be fully dealt with by a short "
                        "conversational reply, with no analysis, file reading or "
                        "other work?",
        "criteria": {
            "true": "Thanks, a greeting, an acknowledgement, a remark that needs no "
                    "action, picking one of the options the assistant just offered, "
                    "or asking the assistant to repeat or explain what it just did",
            "false": "A request to find, check, read, file, draft, plan, fix or "
                     "change something — or a question asking for advice, a "
                     "recommendation, or what to do next, which needs the situation "
                     "to be analysed before it can be answered",
        },
    },
}

NEEDS_CONVERSATION = 0.4    # at or above: the driver must write the context into the brief
CONVERSATION = 0.4          # at or above: the driver keeps it
DEFAULT_DRIVER = "sonnet"
HARNESS_PREFIXES = ("/", "<task-notification", "<system-reminder", "<local-command",
                    # aiq's resume note after a quota-account switch: "continue where
                    # the last session stopped" is an order to the driver, which holds
                    # that context. Handing it to a cold subagent is the wrong move.
                    "aiq moved this session")
MAX_PREVIOUS_REPLY_CHARS = 1500

DELEGATE_TMPL = """\
ROUTER (lifeproj route): this prompt was scored as {model}-level work ({why}). \
Do not carry it out yourself. Spawn one subagent with the Agent tool, \
model "{model}", and give it the user's prompt verbatim as its task, plus any \
file paths or facts from this conversation it would need. When it returns, \
check its result against the teka's working rules and report to the user."""


# The prompt leans on the conversation ("those three drafts"), so passing it
# verbatim would strand the subagent. The driver holds the context; it writes it.
DELEGATE_WITH_CONTEXT_TMPL = """\
ROUTER (lifeproj route): this prompt was scored as {model}-level work ({why}). \
Do not carry it out yourself. Spawn one subagent with the Agent tool, \
model "{model}". The prompt refers back to this conversation, so write the \
subagent a self-contained brief: quote the user's prompt, name every file, \
item and fact it refers to, say what has already been done and checked, and \
say what must not be touched. When it returns, check its result against the \
teka's working rules and report to the user."""


def _previous_reply(transcript_path: Optional[str]) -> Optional[str]:
    """The main session's last text reply, so Jev can tell a follow-up from a
    fresh request. Best-effort: the transcript format is not a contract."""
    try:
        last = None
        with open(transcript_path) as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                    if entry.get("type") != "assistant" or entry.get("isSidechain"):
                        continue
                    texts = [b["text"] for b in entry["message"]["content"]
                             if b.get("type") == "text"]
                except (ValueError, KeyError, TypeError, AttributeError):
                    continue    # a half-written or unfamiliar line
                if texts:
                    last = "\n".join(texts)
        return clip(last, MAX_PREVIOUS_REPLY_CHARS) if last else None
    except (OSError, TypeError):
        return None


def should_delegate(result: dict, driver: str) -> bool:
    """Only upward: a spawn starts a fresh context, which costs more than the
    driver answering something at or below its own tier. Leaning on the
    conversation does not keep work with the driver — it changes the
    instruction (see `prompt_hook`)."""
    scores = result["scores"]
    return (bool(result["routed"])
            and scores["is_conversation"] < CONVERSATION
            and TIERS.index(result["model"]) > TIERS.index(driver))


def prompt_hook(log_path: Optional[Path] = None) -> int:
    """Claude Code UserPromptSubmit hook. A hook cannot rewrite the prompt, so
    when the prompt is self-contained work above the driver's tier this adds an
    instruction to delegate it. Printing nothing leaves the prompt alone."""
    try:
        event = json.load(sys.stdin)
        prompt = event["prompt"]
        # Slash commands, and events the harness submits as prompts (a finished
        # background task, a monitor firing), are not requests from the user.
        if not prompt.strip() or prompt.lstrip().startswith(HARNESS_PREFIXES):
            return 0
    except (ValueError, KeyError, TypeError, AttributeError):
        return 0
    driver = os.environ.get("LIFEPROJ_DRIVER", DEFAULT_DRIVER)
    if driver not in TIERS:
        driver = DEFAULT_DRIVER
    previous = _previous_reply(event.get("transcript_path"))
    fields = {"kind": "prompt", "session": event.get("session_id"), "driver": driver}
    result = route(prompt, domain=_teka_domain(event.get("cwd")),
                   extra_state={"previous_assistant_reply": previous or "(none: first prompt)"},
                   extra_questions=PROMPT_QUESTIONS, log_path=log_path, log_fields=fields,
                   annotate=lambda r: {"delegate": should_delegate(r, driver)})
    if not should_delegate(result, driver):
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": (
            DELEGATE_WITH_CONTEXT_TMPL
            if result["scores"]["needs_conversation"] >= NEEDS_CONVERSATION
            else DELEGATE_TMPL).format(model=result["model"], why="; ".join(result["why"])),
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
