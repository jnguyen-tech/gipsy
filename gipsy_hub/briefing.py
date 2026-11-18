"""
This week's tasks for Gipsy: school work, appointments, your own to-do list and
(through a pluggable source) market events.

Where the data comes from
  * Calendars: any iCal (.ics) feed. Google Calendar's "secret address in iCal
    format", your school's Canvas/Schoology/Google Classroom calendar feed,
    Outlook "publish calendar" links and iCloud public calendars all work.
    List them in config.json under "calendars".
  * Tasks: a small to-do list kept on the PC in tasks.json. Add things by
    voice ("Hey Gipsy, add a task: chem lab report due Friday") or in the app.
  * Market events: another module registers a source with
    register_market_source(fn). fn(start: date, end: date) is async and returns
    [{"date","time","title","kind","symbol"}].

Everything is read-only except tasks.json. Nothing leaves the PC except the
calendar downloads themselves.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger("gipsy.briefing")

HERE = Path(__file__).resolve().parent
TASKS_FILE = HERE / "tasks.json"

_cfg: dict[str, Any] = {}
_market_source: Optional[Callable[[date, date], Awaitable[list[dict[str, Any]]]]] = None
_ics_cache: dict[str, tuple[float, bytes]] = {}
_tasks_lock = asyncio.Lock()


def init(cfg: dict[str, Any]) -> None:
    """Called once by gipsy_hub with the loaded config."""
    _cfg.clear()
    _cfg.update(cfg)


def register_market_source(fn: Callable[[date, date], Awaitable[list[dict[str, Any]]]]) -> None:
    global _market_source
    _market_source = fn


def tz() -> ZoneInfo:
    return ZoneInfo(_cfg.get("timezone") or "America/Chicago")


def today() -> date:
    return datetime.now(tz()).date()


# ------------------------------------------------------------------ tasks ----


def _load_tasks() -> list[dict[str, Any]]:
    if not TASKS_FILE.exists():
        return []
    try:
        return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("tasks.json is unreadable; starting an empty list")
        return []


def _save_tasks(tasks: list[dict[str, Any]]) -> None:
    tmp = TASKS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, indent=2), encoding="utf-8")
    tmp.replace(TASKS_FILE)


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_due(text: str, ref: Optional[date] = None) -> str:
    """'2026-11-20', 'today', 'tomorrow', 'friday', 'next monday', '11/20' -> ISO date or ''."""
    ref = ref or today()
    t = (text or "").strip().lower()
    if not t:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return t
    if t in ("today", "tonight"):
        return ref.isoformat()
    if t == "tomorrow":
        return (ref + timedelta(days=1)).isoformat()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", t)
    if m:
        y = int(m[3]) if m[3] else ref.year
        y = y + 2000 if y < 100 else y
        d = date(y, int(m[1]), int(m[2]))
        if not m[3] and d < ref - timedelta(days=60):
            d = d.replace(year=y + 1)
        return d.isoformat()
    m = re.fullmatch(r"(next |this )?(" + "|".join(_WEEKDAYS) + r")", t)
    if m:
        ahead = (_WEEKDAYS.index(m[2]) - ref.weekday()) % 7
        if m[1] == "next ":
            # "next friday" = the friday of next week
            ahead += 7 if (ref + timedelta(days=ahead)).isocalendar()[1] == ref.isocalendar()[1] or ahead == 0 else 0
        return (ref + timedelta(days=ahead)).isoformat()
    raise ValueError(f"I couldn't understand the due date {text!r}. Try a weekday, 'tomorrow' or 2026-11-20.")


async def list_tasks(include_done: bool = False) -> list[dict[str, Any]]:
    async with _tasks_lock:
        tasks = _load_tasks()
    return [t for t in tasks if include_done or not t.get("done")]


async def add_task(title: str, due: str = "", kind: str = "task") -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise ValueError("A task needs a title")
    task = {
        "id": uuid.uuid4().hex[:8],
        "title": title,
        "due": parse_due(due),
        "kind": kind if kind in ("task", "school", "appointment") else "task",
        "done": False,
        "created": datetime.now(tz()).isoformat(timespec="seconds"),
    }
    async with _tasks_lock:
        tasks = _load_tasks()
        tasks.append(task)
        _save_tasks(tasks)
    return task


async def complete_task(task: str) -> dict[str, Any]:
    """Mark done by id, or by the best title match."""
    key = (task or "").strip().lower()
    async with _tasks_lock:
        tasks = _load_tasks()
        open_tasks = [t for t in tasks if not t.get("done")]
        hit = next((t for t in open_tasks if t["id"] == key), None)
        if hit is None:
            hits = [t for t in open_tasks if key and key in t["title"].lower()]
            if len(hits) > 1:
                raise LookupError("More than one task matches: " + "; ".join(t["title"] for t in hits))
            hit = hits[0] if hits else None
        if hit is None:
            raise LookupError(f"No open task matches {task!r}")
        hit["done"] = True
        hit["done_at"] = datetime.now(tz()).isoformat(timespec="seconds")
        _save_tasks(tasks)
    return hit


async def delete_task(task_id: str) -> bool:
    async with _tasks_lock:
        tasks = _load_tasks()
        kept = [t for t in tasks if t["id"] != task_id]
        _save_tasks(kept)
    return len(kept) != len(tasks)


# -------------------------------------------------------------- calendars ----


async def _fetch_ics(url: str) -> bytes:
    url = re.sub(r"^webcals?://", "https://", url.strip())
    hit = _ics_cache.get(url)
    if hit and time.monotonic() - hit[0] < 15 * 60:
        return hit[1]
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": "GipsyHub/1.0 (personal calendar reader)"})
        r.raise_for_status()
    _ics_cache[url] = (time.monotonic(), r.content)
    return r.content


def parse_ics(data: bytes, start: date, end: date, source: str, kind: str) -> list[dict[str, Any]]:
    """Events between start and end (inclusive), recurring ones expanded."""
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(data)
    zone = tz()
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end + timedelta(days=1)):
        dt = ev.decoded("DTSTART")
        if isinstance(dt, datetime):
            local = (dt if dt.tzinfo else dt.replace(tzinfo=zone)).astimezone(zone)
            d, hhmm = local.date(), local.strftime("%H:%M")
        else:  # all-day
            d, hhmm = dt, ""
        if not (start <= d <= end):
            continue
        out.append(
            {
                "date": d.isoformat(),
                "time": hhmm,
                "title": str(ev.get("SUMMARY", "(no title)")).strip(),
                "kind": kind,
                "source": source,
                "location": str(ev.get("LOCATION", "") or "").strip(),
            }
        )
    return out


async def calendar_events(start: date, end: date) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    problems: list[str] = []

    async def one(c: dict[str, Any]) -> None:
        name = c.get("name") or "Calendar"
        try:
            data = await _fetch_ics(c["url"])
            events.extend(await asyncio.to_thread(parse_ics, data, start, end, name, c.get("kind", "calendar")))
        except Exception as e:  # one broken feed shouldn't hide the others
            log.warning("Calendar %s failed: %s", name, e)
            problems.append(f"Couldn't read the {name} calendar ({type(e).__name__})")

    await asyncio.gather(*(one(c) for c in _cfg.get("calendars", []) if c.get("url")))
    return events, problems


# ----------------------------------------------------------------- the week --


async def week_agenda(days: int = 7, start: str = "") -> dict[str, Any]:
    """Everything coming up: calendars, tasks due, market events, by day."""
    days = max(1, min(int(days or 7), 31))
    first = date.fromisoformat(start) if start else today()
    last = first + timedelta(days=days - 1)

    items, problems = await calendar_events(first, last)

    tasks = await list_tasks()
    overdue = [t for t in tasks if t.get("due") and t["due"] < first.isoformat()]
    undated = [t for t in tasks if not t.get("due")]
    for t in tasks:
        if t.get("due") and first.isoformat() <= t["due"] <= last.isoformat():
            items.append({"date": t["due"], "time": "", "title": t["title"], "kind": t.get("kind", "task"),
                          "source": "To-do", "task_id": t["id"]})

    if _market_source and _cfg.get("market_events_enabled", True):
        try:
            for ev in await _market_source(first, last):
                items.append({**ev, "source": "Markets"})
        except Exception as e:
            log.warning("Market events failed: %s", e)
            problems.append("Couldn't load market events")

    order = {"appointment": 0, "school": 1, "task": 2, "calendar": 3, "fed": 4, "econ": 5, "earnings": 6}
    items.sort(key=lambda i: (i["date"], i.get("time") or "99:99", order.get(i.get("kind", ""), 9), i["title"]))
    by_day = []
    for n in range(days):
        d = first + timedelta(days=n)
        by_day.append({
            "date": d.isoformat(),
            "weekday": d.strftime("%A"),
            "items": [i for i in items if i["date"] == d.isoformat()],
        })
    return {
        "start": first.isoformat(),
        "end": last.isoformat(),
        "days": by_day,
        "overdue": overdue,
        "undated": undated,
        "problems": problems,
        "calendars": [c.get("name", "Calendar") for c in _cfg.get("calendars", []) if c.get("url")],
    }


# ------------------------------------------------------------ LLM tools ------

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_week_agenda",
            "description": (
                "John's schedule: school work due, appointments, events from his calendars, his to-do "
                "list and market events (Fed meetings, CPI/jobs reports, earnings). Use for 'what's this "
                "week', 'what's due', 'am I free Thursday', 'any earnings this week'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "How many days to cover, default 7"},
                    "start": {"type": "string", "description": "First day as YYYY-MM-DD, default today"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Add something to John's to-do list, optionally with a due date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "due": {"type": "string", "description": "YYYY-MM-DD, a weekday, 'today' or 'tomorrow'"},
                    "kind": {"type": "string", "enum": ["task", "school", "appointment"]},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark one of John's to-do items as done, by part of its title.",
            "parameters": {
                "type": "object",
                "properties": {"task": {"type": "string"}},
                "required": ["task"],
            },
        },
    },
]


async def _tool_add(title: str, due: str = "", kind: str = "task") -> dict[str, Any]:
    return {"added": await add_task(title, due, kind)}


async def _tool_done(task: str) -> dict[str, Any]:
    return {"completed": await complete_task(task)}


FUNCTIONS = {"get_week_agenda": week_agenda, "add_task": _tool_add, "complete_task": _tool_done}

DESCRIPTIONS = {
    "get_week_agenda": lambda a: "Checking your week",
    "add_task": lambda a: f"Adding to your to-do list: {a.get('title', '')}",
    "complete_task": lambda a: f"Ticking off: {a.get('task', '')}",
}


def install_tools(tools_module: Any) -> None:
    """Add these tools to the hub's tool list (tools.py)."""
    names = {t["function"]["name"] for t in tools_module.TOOLS}
    tools_module.TOOLS.extend(t for t in TOOLS if t["function"]["name"] not in names)
    tools_module.FUNCTIONS.update(FUNCTIONS)
    extra = getattr(tools_module, "EXTRA_DESCRIPTIONS", None)
    if isinstance(extra, dict):
        extra.update(DESCRIPTIONS)
