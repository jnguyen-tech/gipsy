"""
Market week ahead + John's portfolio, for Gipsy's weekly briefing.

market_calendar(days)   events coming up: Fed (FOMC) meetings, CPI / jobs /
                        PPI / GDP releases, market holidays and early closes,
                        and earnings dates for the symbols John follows.
get_portfolio()         John's holdings and watchlist from portfolio.json,
                        priced live, with gain/loss and the 50/200 EMA trend.

Why a portfolio.json and not Robinhood directly? Robinhood has no public API
for stock accounts. Its MCP connector signs in to Claude on claude.ai, not to
programs on this PC, so the local model can't call it. Instead, ask Claude in
the Gipsy project to "sync my Robinhood to Gipsy": it reads your positions and
watchlists (read-only) and writes portfolio.json for you. You can also edit
the file by hand. It never leaves your PC and is ignored by git.

Data sources (no keys): Nasdaq's earnings calendar, the BLS release calendar
(ics), and a built-in list of Fed meetings and NYSE holidays.
"""

from __future__ import annotations

import json
import os
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from tools import TIMEOUT, UA, cached, get_emas, get_price

log = logging.getLogger("gipsy")
HERE = Path(__file__).resolve().parent
# GIPSY_DATA_DIR is /data in Docker so the portfolio survives updates.
PORTFOLIO = Path(os.environ.get("GIPSY_DATA_DIR") or HERE) / "portfolio.json"

# Second day of each FOMC meeting: the 2 PM ET statement, then the press
# conference. Source: federalreserve.gov FOMC calendar. Add next year's dates
# when the Fed publishes them.
FOMC_DECISIONS = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]
FOMC_WITH_PROJECTIONS = {"2026-03-18", "2026-06-17", "2026-09-16", "2026-12-09"}

# NYSE/Nasdaq full closures and 1 PM ET early closes.
MARKET_CLOSED = {
    "2026-11-26": "Thanksgiving",
    "2026-12-25": "Christmas",
    "2027-01-01": "New Year's Day",
    "2027-01-18": "Martin Luther King Jr. Day",
    "2027-02-15": "Presidents' Day",
    "2027-03-26": "Good Friday",
    "2027-05-31": "Memorial Day",
    "2027-06-18": "Juneteenth (observed)",
    "2027-07-05": "Independence Day (observed)",
    "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving",
    "2027-12-24": "Christmas (observed)",
}
EARLY_CLOSE = {"2026-11-27": "Day after Thanksgiving", "2026-12-24": "Christmas Eve", "2027-11-26": "Day after Thanksgiving"}

# BLS releases worth knowing about, by a word in the event title.
BLS_WATCH = {
    "Consumer Price Index": "CPI inflation report (8:30 AM ET)",
    "Employment Situation": "Jobs report: payrolls and unemployment (8:30 AM ET)",
    "Producer Price Index": "PPI wholesale inflation (8:30 AM ET)",
    "Job Openings and Labor Turnover": "JOLTS job openings (10 AM ET)",
}

# Big names whose earnings move the whole market, always included.
MARKET_MOVERS = {"AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "WMT", "COST", "NFLX"}


# ------------------------------------------------------------ portfolio -----


def load_portfolio() -> dict[str, Any]:
    if not PORTFOLIO.exists():
        return {"holdings": [], "watchlist": []}
    try:
        return json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    except ValueError as e:
        raise LookupError(f"portfolio.json isn't valid JSON: {e}")


def followed_symbols() -> list[str]:
    p = load_portfolio()
    syms = [h.get("symbol", "") for h in p.get("holdings", [])] + list(p.get("watchlist", []))
    seen: list[str] = []
    for s in syms:
        s = s.strip().upper()
        if s and s not in seen:
            seen.append(s)
    return seen


async def get_portfolio() -> dict[str, Any]:
    p = load_portfolio()
    holdings = p.get("holdings", [])
    if not holdings and not p.get("watchlist"):
        return {
            "error": "No portfolio yet. Ask Claude in the Gipsy project to sync Robinhood to Gipsy, "
            "or copy portfolio.example.json to portfolio.json and edit it."
        }
    rows: list[dict[str, Any]] = []
    total_value = total_cost = 0.0
    for h in holdings:
        sym = h["symbol"].upper()
        row: dict[str, Any] = {"symbol": sym, "shares": h.get("shares", 0)}
        try:
            q = await get_price(sym)
            price = float(str(q["price"]).replace(",", "").rstrip("%"))
            row["price"] = q["price"]
            row["change_today"] = q.get("change_today", "")
            shares = float(h.get("shares", 0))
            value = shares * price
            row["value"] = round(value, 2)
            total_value += value
            if h.get("average_cost"):
                cost = shares * float(h["average_cost"])
                total_cost += cost
                row["gain"] = f"{value - cost:+,.2f} ({(value - cost) / cost * 100:+.1f}%)" if cost else ""
            e = await get_emas(sym, [50, 200])
            row["trend"] = {k: v["price_is"] for k, v in e["emas"].items() if isinstance(v, dict)}
        except Exception as ex:
            row["error"] = str(ex)
        rows.append(row)
    watch: list[dict[str, Any]] = []
    for sym in p.get("watchlist", []):
        try:
            q = await get_price(sym)
            watch.append({"symbol": q["symbol"], "price": q["price"], "change_today": q.get("change_today", "")})
        except Exception as ex:
            watch.append({"symbol": sym, "error": str(ex)})
    out: dict[str, Any] = {"holdings": rows, "watchlist": watch, "synced": p.get("updated", "unknown")}
    if total_value:
        out["total_value"] = round(total_value, 2)
    if total_cost:
        out["total_gain"] = f"{total_value - total_cost:+,.2f} ({(total_value - total_cost) / total_cost * 100:+.1f}%)"
    out["note"] = "Prices can be delayed. Education only, not financial advice."
    return out


# ------------------------------------------------------------- calendar -----


def _fixed_events(start: date, end: date) -> list[dict[str, str]]:
    ev: list[dict[str, str]] = []
    for d in FOMC_DECISIONS:
        if start.isoformat() <= d <= end.isoformat():
            extra = " with new economic projections (dot plot)" if d in FOMC_WITH_PROJECTIONS else ""
            ev.append({"date": d, "kind": "fed", "what": f"Fed interest-rate decision at 2 PM ET, press conference 2:30 PM{extra}"})
    for d, name in MARKET_CLOSED.items():
        if start.isoformat() <= d <= end.isoformat():
            ev.append({"date": d, "kind": "holiday", "what": f"US stock market closed: {name}"})
    for d, name in EARLY_CLOSE.items():
        if start.isoformat() <= d <= end.isoformat():
            ev.append({"date": d, "kind": "holiday", "what": f"US stock market closes early at 1 PM ET: {name}"})
    return ev


def parse_ics(text: str) -> list[tuple[str, str]]:
    """(YYYY-MM-DD, summary) for every VEVENT. Handles folded lines."""
    text = re.sub(r"\r?\n[ \t]", "", text)
    out: list[tuple[str, str]] = []
    for block in text.split("BEGIN:VEVENT")[1:]:
        m_d = re.search(r"^DTSTART[^:]*:(\d{8})", block, re.M)
        m_s = re.search(r"^SUMMARY[^:]*:(.+)$", block, re.M)
        if m_d and m_s:
            d = m_d.group(1)
            out.append((f"{d[:4]}-{d[4:6]}-{d[6:]}", m_s.group(1).strip().replace("\\,", ",")))
    return out


async def _bls_events(start: date, end: date) -> list[dict[str, str]]:
    async def fetch() -> list[tuple[str, str]]:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=UA, follow_redirects=True) as c:
            r = await c.get("https://www.bls.gov/schedule/news_release/bls.ics")
            r.raise_for_status()
            return parse_ics(r.text)

    rows = await cached("bls.ics", 12 * 3600, fetch)
    ev = []
    for d, summary in rows:
        if not (start.isoformat() <= d <= end.isoformat()):
            continue
        for key, label in BLS_WATCH.items():
            if key.lower() in summary.lower():
                ev.append({"date": d, "kind": "economy", "what": label})
    return ev


async def _earnings_on(day: date) -> list[dict[str, Any]]:
    async def fetch() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={**UA, "Accept": "application/json"}) as c:
            r = await c.get("https://api.nasdaq.com/api/calendar/earnings", params={"date": day.isoformat()})
            r.raise_for_status()
            return ((r.json().get("data") or {}).get("rows")) or []

    return await cached(f"earn:{day}", 6 * 3600, fetch)


def _when(code: str) -> str:
    return {"time-pre-market": "before the open", "time-after-hours": "after the close"}.get(code or "", "time not confirmed")


async def _earnings_events(start: date, end: date, mine: set[str]) -> list[dict[str, str]]:
    symbols = mine | MARKET_MOVERS
    ev: list[dict[str, str]] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            try:
                for row in await _earnings_on(d):
                    sym = (row.get("symbol") or "").upper()
                    if sym in symbols:
                        tag = " (you follow this)" if sym in mine else ""
                        ev.append({
                            "date": d.isoformat(),
                            "kind": "earnings",
                            "what": f"{row.get('name') or sym} ({sym}) reports earnings {_when(row.get('time', ''))}{tag}",
                        })
            except Exception as e:
                log.info("Earnings calendar for %s failed: %s", d, e)
        d += timedelta(days=1)
    return ev


async def market_calendar(days: int = 7) -> dict[str, Any]:
    days = max(1, min(int(days or 7), 31))
    start = datetime.now().date()
    end = start + timedelta(days=days - 1)
    events = _fixed_events(start, end)
    problems: list[str] = []
    try:
        events += await _bls_events(start, end)
    except Exception as e:
        problems.append(f"economic calendar unavailable ({type(e).__name__})")
    try:
        mine = set(followed_symbols())
    except LookupError as e:
        mine = set()
        problems.append(str(e))
    events += await _earnings_events(start, end, mine)
    events.sort(key=lambda e: (e["date"], e["kind"]))
    for e in events:
        e["day"] = datetime.fromisoformat(e["date"]).strftime("%A %b %d").replace(" 0", " ")
    out: dict[str, Any] = {"from": start.isoformat(), "to": end.isoformat(), "events": events}
    if problems:
        out["problems"] = problems
    if not any(e["kind"] == "earnings" for e in events):
        out["earnings_note"] = "No earnings found for followed symbols or big market movers (or the calendar was unreachable)."
    return out


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "market_calendar",
            "description": (
                "Upcoming market events: Fed rate decisions, CPI / jobs / PPI reports, market holidays and early "
                "closes, and earnings dates for John's stocks and the biggest companies. Use for 'this week', "
                "'what's coming up', 'when is CPI / the Fed / earnings', and the weekly briefing."
            ),
            "parameters": {
                "type": "object",
                "properties": {"days": {"type": "integer", "description": "How many days ahead, default 7"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio",
            "description": (
                "John's stock holdings and watchlist (synced from his Robinhood), priced now, with gain/loss "
                "and whether each is above or below its 50 and 200 day EMA. Read-only. Use for 'my portfolio', "
                "'my stocks', 'how am I doing', 'my watchlist'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

FUNCTIONS = {"market_calendar": market_calendar, "get_portfolio": get_portfolio}
DESCRIBE = {"market_calendar": "Checking the market calendar", "get_portfolio": "Looking at your portfolio"}


async def market_events(start: date, end: date) -> list[dict[str, str]]:
    """Plug-in for briefing.py (register_market_source). Fed, economic and
    earnings events between start and end inclusive, without holidays
    (briefing.py has its own holiday list). Shape:
    {"date", "time" ("HH:MM" ET or ""), "title", "kind": fed|econ|earnings, "symbol"}
    """
    out: list[dict[str, str]] = []
    for e in _fixed_events(start, end):
        if e["kind"] == "fed":
            out.append({"date": e["date"], "time": "14:00", "title": e["what"], "kind": "fed", "symbol": ""})
    try:
        for e in await _bls_events(start, end):
            t = re.search(r"\((\d{1,2})(?::(\d\d))? AM ET\)", e["what"])
            hhmm = f"{int(t.group(1)):02d}:{t.group(2) or '00'}" if t else ""
            out.append({"date": e["date"], "time": hhmm, "title": e["what"].split(" (")[0], "kind": "econ", "symbol": ""})
    except Exception as ex:
        log.info("BLS calendar unavailable: %s", ex)
    try:
        mine = set(followed_symbols())
    except LookupError:
        mine = set()
    for e in await _earnings_events(start, end, mine):
        sym = re.search(r"\(([A-Z.\-]+)\)", e["what"])
        out.append({"date": e["date"], "time": "", "title": e["what"], "kind": "earnings", "symbol": sym.group(1) if sym else ""})
    out.sort(key=lambda e: (e["date"], e["time"] or "99"))
    return out
