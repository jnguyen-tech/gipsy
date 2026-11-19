"""Offline tests for markets.py (calendar + portfolio). Run: python -m unittest discover tests"""

import asyncio
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import markets  # noqa: E402
import tools  # noqa: E402

ICS = (
    "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261210\r\nSUMMARY:Consumer Price Index for\r\n  November 2026\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261204\r\nSUMMARY:Employment Situation for November 2026\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261205\r\nSUMMARY:Usual Weekly Earnings\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
)


async def fake_cached(key, ttl, fn):
    if key == "bls.ics":
        return markets.parse_ics(ICS)
    if key.startswith("earn:"):
        if key == "earn:2026-12-08":
            return [{"symbol": "ORCL", "name": "Oracle", "time": "time-after-hours"},
                    {"symbol": "XYZ", "name": "Nobody", "time": ""}]
        return []
    return await fn()


async def fake_price(sym):
    return {"symbol": sym, "price": "200.00", "change_today": "+1.00 (+0.50%)"}


async def fake_emas(sym, periods=None):
    return {"emas": {"EMA50": {"price_is": "above"}, "EMA200": {"price_is": "above"}}}


markets.cached = fake_cached
markets.get_price = fake_price
markets.get_emas = fake_emas


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "portfolio.json"
        self.tmp.write_text(json.dumps({"holdings": [{"symbol": "orcl", "shares": 2, "average_cost": 100}], "watchlist": ["GLD"]}))
        markets.PORTFOLIO = self.tmp

    def test_parse_ics_unfolds_lines(self):
        rows = markets.parse_ics(ICS)
        self.assertEqual(rows[0], ("2026-12-10", "Consumer Price Index for November 2026"))

    def test_events_for_the_week(self):
        ev = asyncio.run(markets.market_events(date(2026, 12, 4), date(2026, 12, 10)))
        kinds = [(e["date"], e["kind"]) for e in ev]
        self.assertIn(("2026-12-04", "econ"), kinds)       # jobs report
        self.assertIn(("2026-12-09", "fed"), kinds)        # FOMC
        self.assertIn(("2026-12-10", "econ"), kinds)       # CPI
        earn = [e for e in ev if e["kind"] == "earnings"]
        self.assertEqual([e["symbol"] for e in earn], ["ORCL"])  # XYZ isn't followed
        self.assertEqual(next(e for e in ev if e["kind"] == "fed")["time"], "14:00")
        self.assertEqual(next(e for e in ev if e["date"] == "2026-12-04")["time"], "08:30")
        self.assertNotIn("Usual Weekly", json.dumps(ev))

    def test_holidays_in_tool_but_not_in_briefing_hook(self):
        fixed = markets._fixed_events(date(2026, 11, 23), date(2026, 11, 29))
        self.assertEqual([e["date"] for e in fixed], ["2026-11-26", "2026-11-27"])

    def test_portfolio(self):
        out = asyncio.run(markets.get_portfolio())
        h = out["holdings"][0]
        self.assertEqual(h["symbol"], "ORCL")
        self.assertEqual(h["value"], 400.0)
        self.assertTrue(h["gain"].startswith("+200.00"))
        self.assertEqual(out["watchlist"][0]["symbol"], "GLD")

    def test_no_portfolio_explains_how(self):
        markets.PORTFOLIO = self.tmp.parent / "missing.json"
        self.assertIn("sync", asyncio.run(markets.get_portfolio())["error"])

    def test_tools_are_registered_in_hub(self):
        import gipsy_hub  # noqa: F401
        names = [t["function"]["name"] for t in tools.TOOLS]
        self.assertIn("market_calendar", names)
        self.assertIn("get_portfolio", names)
        self.assertEqual(tools.describe_call("get_portfolio", {}), "Looking at your portfolio")


if __name__ == "__main__":
    unittest.main()
