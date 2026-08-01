"""`lifeproj brief` — one cross-teka answer to "what needs me today?".

Every teka publishes a standard agenda slice into the Osavul spool at the end of
each digest (DESIGN §10), so the Monday-morning question is already answerable
from outside every teka: read the slices, merge, sort by urgency. This module is
a pure **reader** — it never enters a teka, never runs a teka's own scripts, and
never writes. The slice contract is the interface; stdout of bespoke per-teka
scripts is not.

It is deliberately mechanical. Osavul, the chief-of-staff teka, remains where
judgment, routing and reconciliation happen; `brief` is the glance you take
before deciding whether to open Osavul at all.

Two honesty features keep the list trustworthy, because a slice is a *cached*
projection: every source's `generated` age is checked (a teka that hasn't run a
digest in weeks is flagged, not silently trusted), and pending completions
sitting in the outbox are reported (items shown here may already be closed
upstream). Tekas that never published are named rather than omitted.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from lifeproj import osavul, registry

# A slice older than this hasn't seen a digest in a while — flag it rather than
# quietly presenting stale work as current.
STALE_DAYS = 7
# Buckets, in the order a human reads them: what's late, what's now, what's
# coming, then the parked stuff, then other people's court.
BUCKETS = ("overdue", "today", "soon", "later", "undated", "waiting")
SOON_DAYS = 7
WAITING_STATUSES = ("waiting", "blocked")
_PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}

_TITLES = {
    "overdue": "OVERDUE",
    "today": "TODAY",
    "soon": f"NEXT {SOON_DAYS} DAYS",
    "later": "LATER",
    "undated": "NO DEADLINE",
    "waiting": "WAITING ON SOMEONE ELSE",
}

_SUFFIX = ".agenda.json"
# A teka's open_items[] title can legitimately run to a paragraph (a tax item
# carrying its whole decision context). Full text is what `--json` and the teka
# itself are for; a scannable brief needs one line per item.
TITLE_WIDTH = 96
WAITING_ON_WIDTH = 44


def _clip(text: str, width: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width - 1].rstrip() + "…"


def _parse_generated(value) -> Optional[datetime]:
    """Parse a slice's ``generated`` stamp. Tolerant on purpose: the canonical
    form is ``...Z``, but a teka may publish a UTC offset instead."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):          # fromisoformat only accepts Z from 3.11
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp


def _read_json(path: Path):
    try:
        return json.loads(path.read_text()), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _pending_completions(root: Path, teka: str) -> int:
    """Completions Osavul wrote that the teka hasn't drained — so the items
    below may already be closed."""
    data, _ = _read_json(root / "outbox" / f"{teka}.intake.json")
    if not isinstance(data, dict):
        return 0
    completions = data.get("completions")
    return len(completions) if isinstance(completions, list) else 0


def _shape(item: dict, teka: str, today: date) -> dict:
    due_raw = item.get("due")
    due = None
    if due_raw:
        try:
            due = date.fromisoformat(str(due_raw))
        except (ValueError, TypeError):
            due = None              # unparseable: treat as undated, never drop
    status = item.get("status") or "open"
    days_out = (due - today).days if due else None
    if status in WAITING_STATUSES:
        bucket = "waiting"
    elif due is None:
        bucket = "undated"
    elif days_out < 0:
        bucket = "overdue"
    elif days_out == 0:
        bucket = "today"
    elif days_out <= SOON_DAYS:
        bucket = "soon"
    else:
        bucket = "later"
    return {
        "teka": teka,
        "id": item.get("id"),
        "title": item.get("title") or "(untitled)",
        "status": status,
        "priority": item.get("priority") or "normal",
        "due": due.isoformat() if due else None,
        "no_deadline": bool(item.get("no_deadline")),
        "waiting_on": item.get("waiting_on"),
        "tags": item.get("tags") or [],
        "link": item.get("link"),
        "bucket": bucket,
        "days_out": days_out,
    }


def _sort_key(item: dict):
    return (item["due"] or "9999-12-31",
            _PRIORITY_ORDER.get(item["priority"], 1),
            item["teka"], item["title"])


def collect(config_path: Optional[Path] = None, *, spool: Optional[Path] = None,
            today: Optional[date] = None, now: Optional[datetime] = None,
            tekas: Optional[list] = None, days: Optional[int] = None) -> dict:
    """Merge every active teka's published slice into one list.

    Registry-driven, so a new teka joins the brief the day it first publishes and
    an archived one drops out. When the registry can't be read (a sandboxed teka
    session that grants the spool but not cmirror's config), it degrades to
    briefing every slice on the spool and says so.
    """
    root = Path(spool).expanduser() if spool else osavul.spool_root()
    inbox = root / "inbox"
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    notes: list = []
    unknown: list = []

    try:
        doc = registry.load(config_path)
        active = list(registry.projects(doc))
        archived = set(registry.archived(doc))
    except OSError:
        active, archived = None, set()
        notes.append("cmirror registry unreadable here (sandboxed?) — briefing "
                     "every slice on the spool, including archived tekas")

    data = {"today": today.isoformat(), "spool": str(inbox), "items": [],
            "sources": [], "orphans": [], "notes": notes, "unknown": unknown}

    if not inbox.is_dir():
        notes.append(f"no agenda spool at {inbox} — nothing to brief (each teka "
                     "publishes its slice with `lifeproj publish`)")
        return data

    on_disk = {p.name[:-len(_SUFFIX)]: p for p in sorted(inbox.glob("*" + _SUFFIX))}
    names = active if active is not None else sorted(on_disk)
    if tekas:
        wanted = list(dict.fromkeys(tekas))
        unknown.extend(n for n in wanted if n not in names and n not in on_disk)
        names = [n for n in wanted if n not in unknown]

    for name in names:
        source = {"teka": name, "generated": None, "age_days": None, "items": 0,
                  "state": "ok", "error": None, "pending_completions": 0}
        path = on_disk.get(name)
        if path is None:
            source["state"] = "never-published"
            data["sources"].append(source)
            continue
        slice_obj, error = _read_json(path)
        if not isinstance(slice_obj, dict):
            source["state"] = "unreadable"
            source["error"] = error or "slice is not a JSON object"
            data["sources"].append(source)
            continue
        stamp = _parse_generated(slice_obj.get("generated"))
        source["generated"] = slice_obj.get("generated")
        if stamp is not None:
            source["age_days"] = (now - stamp).total_seconds() / 86400
            if source["age_days"] > STALE_DAYS:
                source["state"] = "stale"
        source["pending_completions"] = _pending_completions(root, name)
        for raw in slice_obj.get("items") or []:
            if not isinstance(raw, dict) or raw.get("status") == "done":
                continue            # a closed item is nobody's Monday morning
            item = _shape(raw, slice_obj.get("teka") or name, today)
            if days is not None and (item["days_out"] is None or item["days_out"] > days):
                continue
            data["items"].append(item)
            source["items"] += 1
        data["sources"].append(source)

    if active is not None and not tekas:
        data["orphans"] = [f"{n} (archived)" if n in archived else n
                           for n in sorted(on_disk) if n not in active]
    data["items"].sort(key=_sort_key)
    return data


def render(data: dict, *, full: bool = False) -> str:
    items = data["items"]
    live = [s for s in data["sources"] if s["state"] in ("ok", "stale")]
    lines = [f"Brief for {data['today']} · {len(items)} item(s) "
             f"from {len(live)} slice(s)"]

    width = max((len(i["teka"]) for i in items), default=4)
    for bucket in BUCKETS:
        group = [i for i in items if i["bucket"] == bucket]
        if not group:
            continue
        lines.extend(["", _TITLES[bucket]])
        for item in sorted(group, key=_sort_key):
            mark = "!" if item["priority"] == "high" else " "
            due = item["due"] or "—"
            title = item["title"] if full else _clip(item["title"], TITLE_WIDTH)
            tail = ""
            if bucket == "waiting" and item["waiting_on"]:
                who = (item["waiting_on"] if full
                       else _clip(item["waiting_on"], WAITING_ON_WIDTH))
                tail = f"  ← {who}"
            lines.append(f"  {mark} {due:<10}  {item['teka']:<{width}}  "
                         f"{title}{tail}")
    if not items:
        lines.append("")
        lines.append("Nothing open in the published slices.")

    notes = list(data["notes"])
    for source in data["sources"]:
        teka, state = source["teka"], source["state"]
        if state == "never-published":
            notes.append(f"{teka}: no slice published yet — run a digest there "
                         "(`lifeproj publish`)")
        elif state == "unreadable":
            notes.append(f"{teka}: slice unreadable — {source['error']}")
        elif state == "stale":
            notes.append(f"{teka}: slice is {source['age_days']:.0f}d old "
                         f"({source['generated']}) — may be out of date")
        if source["pending_completions"]:
            notes.append(f"{teka}: {source['pending_completions']} completion(s) "
                         "not drained (`lifeproj drain`) — some items above may "
                         "already be closed")
    if data["unknown"]:
        notes.append("unknown teka(s): " + ", ".join(data["unknown"]))
    if data["orphans"]:
        notes.append("slices with no active teka, not briefed: "
                     + ", ".join(data["orphans"]))
    if notes:
        lines.extend(["", "Notes"])
        lines.extend(f"  · {n}" for n in notes)
    return "\n".join(lines)
