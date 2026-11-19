"""
Gipsy's tools: things the local model can ask the hub to do for it.

A language model only knows the world up to its training date, and it can't
browse. So we describe a few tools to it (name, what it does, what inputs it
takes). When the model decides it needs one, Ollama returns a "tool call"
instead of text. The hub runs the matching Python function below, hands the
result back to the model, and the model answers using that fresh data.

Tools here (none need an API key):
  search_news     latest headlines (Google News RSS)
  web_search      general web search (DuckDuckGo, via the ddgs package)
  get_price       live-ish quotes for stocks, ETFs, gold, silver, crypto,
                  bond yields, the dollar (Yahoo Finance chart API)
  get_emas        a symbol's 20/50/200 EMAs computed from daily closes, plus
                  whether a golden/death cross happened recently
  get_economic    US economic series from FRED (mortgage rate, home prices,
                  CPI, unemployment, Fed funds rate)
  get_weather     current weather + the next few days (Open-Meteo)
"""

from __future__ import annotations

import csv
import io
import logging
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable

import httpx

log = logging.getLogger("gipsy")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GipsyHub/1.1"}
TIMEOUT = httpx.Timeout(12, connect=6)

# ------------------------------------------------------------ symbols -------

# Friendly names -> Yahoo Finance symbols, so "gold" or "the 10 year" just work.
ALIASES: dict[str, str] = {
    "gold": "GC=F",
    "silver": "SI=F",
    "copper": "HG=F",
    "oil": "CL=F",
    "crude": "CL=F",
    "crude oil": "CL=F",
    "natural gas": "NG=F",
    "bitcoin": "BTC-USD",
    "btc": "BTC-USD",
    "ethereum": "ETH-USD",
    "eth": "ETH-USD",
    "solana": "SOL-USD",
    "sol": "SOL-USD",
    "xrp": "XRP-USD",
    "dogecoin": "DOGE-USD",
    "doge": "DOGE-USD",
    "s&p 500": "^GSPC",
    "s&p": "^GSPC",
    "sp500": "^GSPC",
    "spx": "^GSPC",
    "nasdaq": "^IXIC",
    "nasdaq 100": "^NDX",
    "dow": "^DJI",
    "dow jones": "^DJI",
    "russell 2000": "^RUT",
    "vix": "^VIX",
    "dollar": "DX-Y.NYB",
    "dollar index": "DX-Y.NYB",
    "dxy": "DX-Y.NYB",
    "10 year": "^TNX",
    "10 year yield": "^TNX",
    "10y": "^TNX",
    "10-year": "^TNX",
    "5 year": "^FVX",
    "5 year yield": "^FVX",
    "30 year": "^TYX",
    "30 year yield": "^TYX",
    "3 month": "^IRX",
    "3 month yield": "^IRX",
    "t-bill": "^IRX",
    "long bonds": "TLT",
    "bonds": "TLT",
    "tips": "TIP",
    "homebuilders": "XHB",
    "home builders": "XHB",
    "reits": "VNQ",
    "real estate": "VNQ",
    "gold miners": "GDX",
    "euro": "EURUSD=X",
    "yen": "JPY=X",
    "pound": "GBPUSD=X",
}

YIELD_SYMBOLS = {"^TNX", "^FVX", "^TYX", "^IRX"}

# FRED series the economic tool knows by friendly name.
FRED_SERIES: dict[str, tuple[str, str]] = {
    "mortgage rate": ("MORTGAGE30US", "30-year fixed mortgage rate, % (weekly, Freddie Mac)"),
    "15 year mortgage rate": ("MORTGAGE15US", "15-year fixed mortgage rate, % (weekly)"),
    "home prices": ("CSUSHPINSA", "Case-Shiller US national home price index (monthly)"),
    "median home price": ("MSPUS", "Median sales price of US houses sold, $ (quarterly)"),
    "housing starts": ("HOUST", "New housing starts, thousands of units, annual rate (monthly)"),
    "cpi": ("CPIAUCSL", "Consumer price index, all items (monthly)"),
    "inflation": ("CPIAUCSL", "Consumer price index, all items (monthly)"),
    "unemployment": ("UNRATE", "Unemployment rate, % (monthly)"),
    "fed funds": ("FEDFUNDS", "Effective federal funds rate, % (monthly)"),
    "fed funds rate": ("FEDFUNDS", "Effective federal funds rate, % (monthly)"),
    "2 year yield": ("DGS2", "2-year Treasury yield, % (daily)"),
    "10 year yield": ("DGS10", "10-year Treasury yield, % (daily)"),
    "yield curve": ("T10Y2Y", "10-year minus 2-year Treasury yield spread, percentage points (daily)"),
    "real yield": ("DFII10", "10-year TIPS (real) yield, % (daily)"),
    "m2": ("M2SL", "M2 money supply, $ billions (monthly)"),
}


def resolve_symbol(name: str) -> str:
    key = re.sub(r"\s+", " ", name.strip().lower())
    key = re.sub(r"\b(price|of|the|current|today'?s?)\b", "", key).strip()
    key = re.sub(r"\s+", " ", key)
    if key in ALIASES:
        return ALIASES[key]
    return name.strip().upper().replace(" ", "")


# --------------------------------------------------------- tiny cache -------

_cache: dict[str, tuple[float, Any]] = {}


async def cached(key: str, ttl: float, fn: Callable[[], Awaitable[Any]]) -> Any:
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = await fn()
    _cache[key] = (time.time(), val)
    return val


# ----------------------------------------------------------------- news -----


def _parse_rss(xml_text: str, limit: int) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    out: list[dict[str, str]] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        # Google News titles end in " - Source"; keep the headline clean.
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        when = item.findtext("pubDate") or ""
        try:
            when = parsedate_to_datetime(when).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            pass
        out.append({"title": title, "source": source, "published": when, "link": item.findtext("link") or ""})
        if len(out) >= limit:
            break
    return out


async def search_news(query: str = "", limit: int = 6) -> dict[str, Any]:
    limit = max(1, min(int(limit or 6), 10))
    if query.strip():
        q = urllib.parse.quote_plus(query.strip())
        url = f"https://news.google.com/rss/search?q={q}+when:7d&hl=en-US&gl=US&ceid=US:en"
    else:  # top stories
        url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"

    async def fetch() -> list[dict[str, str]]:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=UA, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
            return _parse_rss(r.text, limit)

    items = await cached("news:" + url, 600, fetch)

    # Headlines alone are thin. DuckDuckGo news adds a sentence or two of
    # summary when the optional ddgs package is installed.
    if query.strip():
        try:
            extra = await _ddg("news", query, 4)
            for e in extra:
                items.append({
                    "title": e.get("title", ""),
                    "source": e.get("source", ""),
                    "published": (e.get("date") or "")[:16],
                    "summary": (e.get("body") or "")[:300],
                })
        except Exception as e:
            log.info("ddgs news skipped: %s", e)
    return {"query": query or "top stories", "results": items}


async def _ddg(kind: str, query: str, limit: int) -> list[dict[str, Any]]:
    import asyncio

    from ddgs import DDGS  # optional dependency

    def run() -> list[dict[str, Any]]:
        d = DDGS(timeout=10)
        return list(d.news(query, max_results=limit) if kind == "news" else d.text(query, max_results=limit))

    return await cached(f"ddg:{kind}:{query}:{limit}", 600, lambda: asyncio.to_thread(run))


async def web_search(query: str, limit: int = 5) -> dict[str, Any]:
    limit = max(1, min(int(limit or 5), 8))
    try:
        rows = await _ddg("text", query, limit)
    except ImportError:
        return {"error": "Web search needs the ddgs package: pip install ddgs"}
    return {
        "query": query,
        "results": [
            {"title": r.get("title", ""), "snippet": (r.get("body") or "")[:400], "url": r.get("href", "")}
            for r in rows
        ],
    }


# --------------------------------------------------------------- prices -----


async def _yahoo_chart(symbol: str, rng: str, interval: str) -> dict[str, Any]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"

    async def fetch() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=UA) as c:
            r = await c.get(url, params={"range": rng, "interval": interval})
            if r.status_code == 404:
                raise LookupError(f"No symbol called {symbol}")
            r.raise_for_status()
            res = (r.json().get("chart") or {}).get("result") or []
            if not res:
                raise LookupError(f"No data for {symbol}")
            return res[0]

    return await cached(f"yh:{symbol}:{rng}:{interval}", 60 if rng == "5d" else 900, fetch)


def _closes(chart: dict[str, Any]) -> tuple[list[int], list[float]]:
    ts = chart.get("timestamp") or []
    quote = ((chart.get("indicators") or {}).get("quote") or [{}])[0]
    raw = quote.get("close") or []
    pairs = [(t, c) for t, c in zip(ts, raw) if c is not None]
    return [p[0] for p in pairs], [float(p[1]) for p in pairs]


def _fmt(sym: str, v: float) -> str:
    if sym in YIELD_SYMBOLS:
        return f"{v:.2f}%"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 1:
        return f"{v:,.2f}"
    return f"{v:.4f}"


async def get_price(symbol: str) -> dict[str, Any]:
    sym = resolve_symbol(symbol)
    chart = await _yahoo_chart(sym, "5d", "1d")
    meta = chart.get("meta") or {}
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    _, closes = _closes(chart)
    if len(closes) >= 2:
        prev = closes[-2]
    if price is None and closes:
        price = closes[-1]
    if price is None:
        raise LookupError(f"No price for {sym}")
    out: dict[str, Any] = {
        "symbol": sym,
        "name": meta.get("longName") or meta.get("shortName") or sym,
        "price": _fmt(sym, price),
        "currency": "percent (yield)" if sym in YIELD_SYMBOLS else meta.get("currency", ""),
    }
    if prev:
        chg = price - prev
        out["change_today"] = (f"{chg:+.2f} pts" if sym in YIELD_SYMBOLS else f"{chg:+,.2f}") + f" ({chg / prev * 100:+.2f}%)"
    t = meta.get("regularMarketTime")
    if t:
        out["as_of"] = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out["note"] = "Quotes can be delayed about 15 minutes. Educational use only."
    return out


def ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average.

    Seeded with the simple average of the first `period` values, then each
    day: EMA = price * k + previous EMA * (1 - k), with k = 2 / (period + 1).
    Returns a list aligned to values[period-1:].
    """
    if period < 1 or len(values) < period:
        return []
    k = 2 / (period + 1)
    cur = sum(values[:period]) / period
    out = [cur]
    for v in values[period:]:
        cur = v * k + cur * (1 - k)
        out.append(cur)
    return out


def last_cross(fast: list[float], slow: list[float], dates: list[str]) -> dict[str, str] | None:
    """Most recent day the fast EMA crossed the slow one. Lists end on the same day."""
    n = min(len(fast), len(slow))
    f, s, d = fast[-n:], slow[-n:], dates[-n:]
    for i in range(n - 1, 0, -1):
        before, after = f[i - 1] - s[i - 1], f[i] - s[i]
        if before <= 0 < after:
            return {"type": "bullish cross (fast moved above slow)", "date": d[i]}
        if before >= 0 > after:
            return {"type": "bearish cross (fast moved below slow)", "date": d[i]}
    return None


async def get_emas(symbol: str, periods: list[int] | None = None) -> dict[str, Any]:
    sym = resolve_symbol(symbol)
    periods = sorted({int(p) for p in (periods or [20, 50, 200]) if 2 <= int(p) <= 400})
    chart = await _yahoo_chart(sym, "2y", "1d")
    ts, closes = _closes(chart)
    if not closes:
        raise LookupError(f"No history for {sym}")
    dates = [datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d") for t in ts]
    price = closes[-1]
    lines: dict[str, list[float]] = {p: ema(closes, p) for p in periods}
    out: dict[str, Any] = {"symbol": sym, "timeframe": "daily candles", "last_close": _fmt(sym, price), "date": dates[-1], "emas": {}}
    for p, series in lines.items():
        if not series:
            out["emas"][f"EMA{p}"] = "not enough history"
            continue
        val = series[-1]
        slope = "rising" if len(series) > 5 and series[-1] > series[-6] else "falling"
        out["emas"][f"EMA{p}"] = {
            "value": _fmt(sym, val),
            "price_is": "above" if price > val else "below",
            "distance": f"{(price - val) / val * 100:+.1f}%",
            "slope_last_5_days": slope,
        }
    pairs = [(a, b) for a, b in ((20, 50), (50, 200)) if a in lines and b in lines and lines[a] and lines[b]]
    for a, b in pairs:
        c = last_cross(lines[a], lines[b], dates)
        label = f"EMA{a} vs EMA{b}"
        if c:
            if (a, b) == (50, 200):
                c["type"] = ("golden cross" if "bullish" in c["type"] else "death cross") + " (" + c["type"] + ")"
            out.setdefault("crosses", {})[label] = c
        else:
            out.setdefault("crosses", {})[label] = "no cross in the last two years"
    out["note"] = "Moving averages describe the past trend. They don't predict. Educational use only."
    return out


# ------------------------------------------------------------ economics -----


def _parse_fred_csv(text: str) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    reader = csv.reader(io.StringIO(text))
    next(reader, None)
    for row in reader:
        if len(row) >= 2 and row[1] not in ("", "."):
            try:
                rows.append((row[0], float(row[1])))
            except ValueError:
                pass
    return rows


async def get_economic(series: str) -> dict[str, Any]:
    key = series.strip().lower()
    sid, label = FRED_SERIES.get(key, (series.strip().upper(), series.strip().upper()))
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv"

    async def fetch() -> list[tuple[str, float]]:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=UA, follow_redirects=True) as c:
            r = await c.get(url, params={"id": sid})
            r.raise_for_status()
            return _parse_fred_csv(r.text)

    rows = await cached("fred:" + sid, 3600, fetch)
    if not rows:
        raise LookupError(f"FRED has no data for {sid}")
    date, val = rows[-1]
    out: dict[str, Any] = {"series": sid, "what": label, "latest": val, "date": date}
    # One year back, for context.
    year_ago = [r for r in rows if r[0] <= f"{int(date[:4]) - 1}{date[4:]}"]
    if year_ago:
        d0, v0 = year_ago[-1]
        out["a_year_earlier"] = {"value": v0, "date": d0}
    out["recent"] = rows[-6:]
    out["known_series"] = sorted(FRED_SERIES)
    return out


# ----------------------------------------------------------------- weather --

# The hub sets this from config.json ("home_location"), e.g. "Oklahoma City".
SETTINGS: dict[str, Any] = {"home_location": ""}

_WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "icy fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "rain showers",
    81: "rain showers", 82: "violent rain showers", 85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail",
}


async def get_weather(location: str = "", days: int = 3) -> dict[str, Any]:
    """Weather from Open-Meteo (free, no key). Fahrenheit and mph."""
    place = (location or SETTINGS.get("home_location") or "").strip()
    if not place:
        return {"error": "No location given, and home_location isn't set in the hub's config.json. Ask John which city."}
    days = max(1, min(int(days or 3), 7))
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=UA) as client:
        g = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": place.split(",")[0].strip(), "count": 1, "language": "en"},
        )
        g.raise_for_status()
        found = (g.json().get("results") or [None])[0]
        if not found:
            raise LookupError(f"Couldn't find a place called {place!r}")
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": found["latitude"],
                "longitude": found["longitude"],
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "auto",
                "forecast_days": days,
            },
        )
        r.raise_for_status()
        data = r.json()
    cur = data.get("current", {})
    daily = data.get("daily", {})
    return {
        "place": ", ".join(x for x in (found.get("name"), found.get("admin1"), found.get("country_code")) if x),
        "now": {
            "temp_f": cur.get("temperature_2m"),
            "feels_like_f": cur.get("apparent_temperature"),
            "sky": _WMO.get(cur.get("weather_code"), "unknown"),
            "wind_mph": cur.get("wind_speed_10m"),
            "humidity_pct": cur.get("relative_humidity_2m"),
        },
        "days": [
            {
                "date": d,
                "sky": _WMO.get(code, "unknown"),
                "high_f": hi,
                "low_f": lo,
                "rain_chance_pct": rain,
            }
            for d, code, hi, lo, rain in zip(
                daily.get("time", []),
                daily.get("weather_code", []),
                daily.get("temperature_2m_max", []),
                daily.get("temperature_2m_min", []),
                daily.get("precipitation_probability_max", []),
            )
        ],
        "source": "Open-Meteo",
    }


# ------------------------------------------------------ tool registry -------

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                "Current weather and the forecast. Use for any question about weather, temperature, "
                "rain, snow or what to wear. Leave location empty for John's home."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City, e.g. 'Norman' or 'London'. Empty = home."},
                    "days": {"type": "integer", "description": "Days of forecast, 1-7"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": (
                "Get current news headlines from the last week. Use for anything about recent or "
                "current events, 'what's happening', 'latest', 'today', or news on a topic, "
                "company or market. Leave query empty for today's top stories."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic to search, e.g. 'gold prices' or 'Federal Reserve'"},
                    "limit": {"type": "integer", "description": "How many headlines, 1-10"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for facts that may have changed since training, or that you don't know.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_price",
            "description": (
                "Current price and today's change for a stock, ETF, index, future, currency, crypto or bond "
                "yield. Accepts tickers (AAPL, SPY, BTC-USD) or plain names: gold, silver, oil, bitcoin, "
                "ethereum, s&p 500, nasdaq, dollar index, 10 year yield, 30 year yield, homebuilders, reits."
            ),
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_emas",
            "description": (
                "Compute exponential moving averages (default 20, 50 and 200 day) for a symbol from daily "
                "closes, whether price is above or below each, and the latest 20/50 and 50/200 crosses "
                "(golden cross / death cross). Use when John asks about EMAs, trend or crossovers on a chart."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "periods": {"type": "array", "items": {"type": "integer"}, "description": "e.g. [9, 21] or [20, 50, 200]"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_economic",
            "description": (
                "Latest US economic data from FRED: 'mortgage rate', 'home prices', 'median home price', "
                "'housing starts', 'cpi', 'unemployment', 'fed funds rate', '2 year yield', '10 year yield', "
                "'yield curve' (10y minus 2y), 'real yield', 'm2'. Use for housing and macro questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {"series": {"type": "string"}},
                "required": ["series"],
            },
        },
    },
]

FUNCTIONS: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "get_weather": get_weather,
    "search_news": search_news,
    "web_search": web_search,
    "get_price": get_price,
    "get_emas": get_emas,
    "get_economic": get_economic,
}


# Other modules (briefing.py) add their own "what I'm doing" lines here.
EXTRA_DESCRIPTIONS: dict[str, Callable[[dict[str, Any]], str]] = {}


def describe_call(name: str, args: dict[str, Any]) -> str:
    """Short line the app shows while a tool runs."""
    if name in EXTRA_DESCRIPTIONS:
        return EXTRA_DESCRIPTIONS[name](args)
    a = next((str(v) for v in args.values() if v), "")
    return {
        "get_weather": f"Checking the weather in {a}" if a else "Checking the weather",
        "search_news": f"Checking the news: {a}" if a else "Checking today's headlines",
        "web_search": f"Searching the web: {a}",
        "get_price": f"Looking up the price of {a}",
        "get_emas": f"Working out the EMAs for {a}",
        "get_economic": f"Pulling economic data: {a}",
    }.get(name, f"Using {name}")


async def run_tool(name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    fn = FUNCTIONS.get(name)
    if fn is None:
        return {"error": f"There is no tool called {name}"}
    try:
        return await fn(**(args or {}))
    except TypeError as e:
        return {"error": f"Bad arguments for {name}: {e}"}
    except LookupError as e:
        return {"error": str(e)}
    except httpx.HTTPError as e:
        return {"error": f"Couldn't reach the data source ({type(e).__name__}). The PC may be offline."}
    except Exception as e:  # the model should hear about failures, not crash the chat
        log.warning("Tool %s failed: %s", name, e)
        return {"error": f"{name} failed: {e}"}
