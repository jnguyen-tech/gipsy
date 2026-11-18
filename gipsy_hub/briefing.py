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
  * Calendar links can also be added from the app (Calendars button on the
    This week screen). Those are kept in calendars.json on the PC and only
    ever shown back masked, because anyone with an iCal link can read it.
  * Market events: built in are US stock market holidays, 1 PM early closes
    and monthly options expiry (quad witching in Mar/Jun/Sep/Dec), worked out
    from the exchange's rules. Other modules add more (Fed, CPI, earnings)
    with register_market_source(fn). fn(start: date, end: date) is async and
    returns [{"date","time","title","kind","symbol"}].

Everything is read-only except tasks.json and calendars.json. Nothing leaves the PC except the
calendar downloads themselves.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
# Next to this file, or GIPSY_DATA_DIR (/data in Docker) so it survives updates.
DATA_DIR = Path(os.environ.get("GIPSY_DATA_DIR") or HERE)
TASKS_FILE = DATA_DIR / "tasks.json"
CALENDARS_FILE = DATA_DIR / "calendars.json"

MarketSource = Callable[[date, date], Awaitable[list[dict[str, Any]]]]

_cfg: dict[str, Any] = {}
_market_sources: list[MarketSource] = []
_ics_cache: dict[str, tuple[float, bytes]] = {}
_tasks_lock = asyncio.Lock()


def init(cfg: dict[str, Any]) -> None:
    """Called once by gipsy_hub with the loaded config."""
    _cfg.clear()
    _cfg.update(cfg)


def register_market_source(fn: MarketSource) -> None:
    """Add a source of market events. Several can be registered."""
    if fn not in _market_sources:
        _market_sources.append(fn)


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
    for ev in recurring_ical_events.of(cal, skip_bad_series=True).between(start, end + timedelta(days=1)):
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
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

    await asyncio.gather(*(one(c) for c in all_calendars()))
    return events, problems


# ------------------------------------------- calendars linked from the app ---


def _load_linked() -> list[dict[str, Any]]:
    if not CALENDARS_FILE.exists():
        return []
    try:
        rows = json.loads(CALENDARS_FILE.read_text(encoding="utf-8"))
        return rows if isinstance(rows, list) else []
    except (OSError, json.JSONDecodeError):
        log.warning("calendars.json is unreadable; ignoring it")
        return []


def all_calendars() -> list[dict[str, Any]]:
    """config.json "calendars" plus the ones linked from the app."""
    cfg = [{**c, "from": "config"} for c in _cfg.get("calendars", []) if c.get("url")]
    return cfg + [c for c in _load_linked() if c.get("url")]


def mask_url(url: str) -> str:
    """Enough to recognise a link, never enough to use it."""
    m = re.match(r"^\w+://([^/]+)", url or "")
    return f"{m[1]}/...{url[-4:]}" if m else "..."


def public_calendar(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c.get("id", ""),
        "name": c.get("name") or "Calendar",
        "kind": c.get("kind", "calendar"),
        "url": mask_url(c.get("url", "")),
        # Ones in config.json can only be removed by editing config.json.
        "removable": c.get("from") != "config",
    }


async def link_calendar(name: str, url: str, kind: str = "calendar") -> dict[str, Any]:
    """Save an iCal link, then try it so a bad link shows up straight away."""
    url = re.sub(r"^webcals?://", "https://", (url or "").strip())
    if not re.match(r"^https?://\S+$", url):
        raise ValueError("Paste the calendar's iCal link (it starts with https:// or webcal://)")
    row = {
        "id": uuid.uuid4().hex[:8],
        "name": (name or "").strip()[:60] or "Calendar",
        "url": url,
        "kind": kind if kind in ("school", "appointment", "calendar") else "calendar",
    }
    async with _tasks_lock:
        rows = _load_linked()
        rows.append(row)
        CALENDARS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CALENDARS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        tmp.replace(CALENDARS_FILE)
    out = {**public_calendar(row), "ok": True, "error": ""}
    try:
        data = await _fetch_ics(url)
        if b"BEGIN:VCALENDAR" not in data[:4000]:
            raise ValueError("that link returned a web page, not a calendar")
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e) if isinstance(e, ValueError) else f"couldn't download it ({type(e).__name__})"
    return out


async def unlink_calendar(cal_id: str) -> bool:
    async with _tasks_lock:
        rows = _load_linked()
        kept = [c for c in rows if c.get("id") != cal_id]
        if len(kept) != len(rows):
            tmp = CALENDARS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(kept, indent=2), encoding="utf-8")
            tmp.replace(CALENDARS_FILE)
    _ics_cache.clear()
    return len(kept) != len(rows)


# ------------------------------------------- built-in market calendar ------
# Worked out from the NYSE's holiday rules, so it never goes out of date.


def _easter(y: int) -> date:
    """Anonymous Gregorian algorithm."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    return date(y, (h + l - 7 * m + 114) // 31, ((h + l - 7 * m + 114) % 31) + 1)


def _nth_weekday(y: int, month: int, weekday: int, n: int) -> date:
    """n-th weekday (Mon=0) of a month; n=-1 for the last one."""
    if n > 0:
        d = date(y, month, 1)
        return d + timedelta(days=(weekday - d.weekday()) % 7, weeks=n - 1)
    d = date(y + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d


def market_holidays(y: int) -> dict[date, str]:
    """Full-day US stock market closures."""
    h: dict[date, str] = {}
    if date(y, 1, 1).weekday() != 5:  # a Saturday New Year's Day isn't made up on Friday
        h[_observed(date(y, 1, 1))] = "New Year's Day"
    h[_nth_weekday(y, 1, 0, 3)] = "Martin Luther King Jr. Day"
    h[_nth_weekday(y, 2, 0, 3)] = "Presidents' Day"
    h[_easter(y) - timedelta(days=2)] = "Good Friday"
    h[_nth_weekday(y, 5, 0, -1)] = "Memorial Day"
    if y >= 2022:
        h[_observed(date(y, 6, 19))] = "Juneteenth"
    h[_observed(date(y, 7, 4))] = "Independence Day"
    h[_nth_weekday(y, 9, 0, 1)] = "Labor Day"
    h[_nth_weekday(y, 11, 3, 4)] = "Thanksgiving"
    h[_observed(date(y, 12, 25))] = "Christmas"
    return h


def market_early_closes(y: int) -> dict[date, str]:
    """1 PM Eastern early closes."""
    hol = market_holidays(y)
    out = {_nth_weekday(y, 11, 3, 4) + timedelta(days=1): "day after Thanksgiving"}
    for d, why in ((date(y, 7, 3), "day before Independence Day"), (date(y, 12, 24), "Christmas Eve")):
        if d.weekday() < 5 and d not in hol:
            out[d] = why
    return out


async def builtin_market_events(start: date, end: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for y in range(start.year, end.year + 1):
        hol = market_holidays(y)
        for d, name in hol.items():
            if start <= d <= end:
                out.append({"date": d.isoformat(), "time": "", "title": f"US stock market closed: {name}",
                            "kind": "holiday", "symbol": ""})
        for d, name in market_early_closes(y).items():
            if start <= d <= end:
                # 1 PM Eastern is noon on John's Central-time clock; the title says ET.
                out.append({"date": d.isoformat(), "time": "", "kind": "holiday", "symbol": "",
                            "title": f"US stock market closes early at 1 PM ET ({name})"})
        for mo in range(1, 13):
            d = _nth_weekday(y, mo, 4, 3)  # third Friday
            if d in hol:
                d -= timedelta(days=1)  # expiry moves to Thursday
            if start <= d <= end:
                out.append({"date": d.isoformat(), "time": "", "kind": "options", "symbol": "",
                            "title": "Quadruple witching: quarterly options and futures expire" if mo % 3 == 0
                            else "Monthly options expiration"})
    return out


register_market_source(builtin_market_events)


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

    if _cfg.get("market_events_enabled", True):
        seen: set[tuple[str, str]] = set()
        for source in _market_sources:
            try:
                for ev in await source(first, last):
                    key = (ev.get("date", ""), (ev.get("title") or "").lower())
                    if key in seen:  # two sources listing the same holiday
                        continue
                    seen.add(key)
                    items.append({**ev, "source": "Markets"})
            except Exception as e:
                log.warning("Market events from %s failed: %s", getattr(source, "__name__", source), e)
                problems.append("Couldn't load some market events")

    order = {"holiday": -1, "appointment": 0, "school": 1, "task": 2, "calendar": 3, "fed": 4, "econ": 5,
             "earnings": 6, "options": 7}
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
        "calendars": [c.get("name", "Calendar") for c in all_calendars()],
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
