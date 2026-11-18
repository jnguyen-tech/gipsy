"""Offline tests for this week's tasks (briefing.py).

Run from gipsy_hub/:   python -m unittest discover tests
"""

import asyncio
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import briefing  # noqa: E402

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:1
DTSTART:20261119T150000Z
DTEND:20261119T160000Z
SUMMARY:Dentist
LOCATION:Main St
END:VEVENT
BEGIN:VEVENT
UID:2
DTSTART;VALUE=DATE:20261120
SUMMARY:Chem lab report due
END:VEVENT
BEGIN:VEVENT
UID:3
DTSTART:20261116T140000Z
DTEND:20261116T150000Z
RRULE:FREQ=WEEKLY;BYDAY=MO,WE
SUMMARY:Calc study group
END:VEVENT
BEGIN:VEVENT
UID:4
DTSTART;VALUE=DATE:20261205
SUMMARY:Too far away
END:VEVENT
END:VCALENDAR
"""


def run(coro):
    return asyncio.run(coro)


class BriefingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        briefing.TASKS_FILE = Path(self.tmp.name) / "tasks.json"
        briefing.init({"timezone": "America/Chicago", "calendars": [{"name": "School", "url": "https://x/s.ics", "kind": "school"}]})
        briefing._ics_cache.clear()
        briefing._ics_cache["https://x/s.ics"] = (1e18, ICS)  # never expires: no network
        briefing.CALENDARS_FILE = Path(self.tmp.name) / "calendars.json"
        self._sources = list(briefing._market_sources)
        briefing._market_sources.clear()  # tests add the ones they need

    def tearDown(self):
        briefing._market_sources[:] = self._sources
        self.tmp.cleanup()

    def test_parse_ics_expands_recurring_and_local_time(self):
        evs = briefing.parse_ics(ICS, date(2026, 11, 18), date(2026, 11, 24), "School", "school")
        titles = [(e["date"], e["time"], e["title"]) for e in evs]
        self.assertIn(("2026-11-19", "09:00", "Dentist"), titles)  # 15:00Z = 09:00 Central
        self.assertIn(("2026-11-20", "", "Chem lab report due"), titles)
        self.assertIn(("2026-11-18", "08:00", "Calc study group"), titles)  # Wednesday repeat
        self.assertIn(("2026-11-23", "08:00", "Calc study group"), titles)  # next Monday
        self.assertNotIn("Too far away", [t[2] for t in titles])

    def test_due_dates(self):
        ref = date(2026, 11, 18)  # a Wednesday
        self.assertEqual(briefing.parse_due("tomorrow", ref), "2026-11-19")
        self.assertEqual(briefing.parse_due("friday", ref), "2026-11-20")
        self.assertEqual(briefing.parse_due("next friday", ref), "2026-11-27")
        self.assertEqual(briefing.parse_due("monday", ref), "2026-11-23")
        self.assertEqual(briefing.parse_due("11/30", ref), "2026-11-30")
        self.assertEqual(briefing.parse_due("", ref), "")
        with self.assertRaises(ValueError):
            briefing.parse_due("someday", ref)

    def test_tasks_and_week(self):
        run(briefing.add_task("Read chapter 5", "2026-11-21", "school"))
        run(briefing.add_task("Old essay", "2026-11-01"))
        run(briefing.add_task("Buy SD card"))

        async def market(start, end):
            return [{"date": "2026-11-19", "time": "08:30", "title": "CPI report", "kind": "econ", "symbol": ""}]

        briefing.register_market_source(market)
        wk = run(briefing.week_agenda(7, "2026-11-18"))
        self.assertEqual(wk["start"], "2026-11-18")
        self.assertEqual(len(wk["days"]), 7)
        thu = next(d for d in wk["days"] if d["date"] == "2026-11-19")
        self.assertEqual([i["title"] for i in thu["items"]], ["CPI report", "Dentist"])  # by time
        sat = next(d for d in wk["days"] if d["date"] == "2026-11-21")
        self.assertEqual(sat["items"][0]["title"], "Read chapter 5")
        self.assertEqual([t["title"] for t in wk["overdue"]], ["Old essay"])
        self.assertEqual([t["title"] for t in wk["undated"]], ["Buy SD card"])
        self.assertEqual(wk["problems"], [])

        done = run(briefing.complete_task("chapter 5"))
        self.assertTrue(done["done"])
        wk = run(briefing.week_agenda(7, "2026-11-18"))
        sat = next(d for d in wk["days"] if d["date"] == "2026-11-21")
        self.assertEqual(sat["items"], [])

    def test_broken_calendar_is_reported_not_fatal(self):
        briefing.init({"calendars": [{"name": "Broken", "url": "https://x/broken.ics"}]})
        briefing._ics_cache["https://x/broken.ics"] = (1e18, b"not a calendar")
        wk = run(briefing.week_agenda(3, "2026-11-18"))
        self.assertTrue(any("Broken" in p for p in wk["problems"]))

    def test_tools_registered(self):
        import tools

        briefing.install_tools(tools)
        names = [t["function"]["name"] for t in tools.TOOLS]
        for n in ("get_week_agenda", "add_task", "complete_task"):
            self.assertIn(n, names)
        self.assertEqual(tools.describe_call("get_week_agenda", {}), "Checking your week")

    def test_cancelled_events_are_skipped(self):
        cal = ICS.replace(b"SUMMARY:Dentist", b"SUMMARY:Dentist\r\nSTATUS:CANCELLED")
        evs = briefing.parse_ics(cal, date(2026, 11, 18), date(2026, 11, 24), "School", "school")
        self.assertNotIn("Dentist", [e["title"] for e in evs])

    def test_link_calendar_from_the_app(self):
        briefing._ics_cache["https://x/canvas.ics"] = (1e18, ICS)
        briefing._ics_cache["https://x/login"] = (1e18, b"<html>please log in</html>")
        good = run(briefing.link_calendar("Canvas", "webcal://x/canvas.ics", "school"))
        self.assertTrue(good["ok"], good)
        self.assertNotIn("canvas.ics", good["url"])  # never echo the secret link
        bad = run(briefing.link_calendar("Oops", "https://x/login"))
        self.assertFalse(bad["ok"])
        with self.assertRaises(ValueError):
            run(briefing.link_calendar("", "not a link"))
        cals = [briefing.public_calendar(c) for c in briefing.all_calendars()]
        self.assertEqual([c["name"] for c in cals], ["School", "Canvas", "Oops"])
        self.assertEqual([c["removable"] for c in cals], [False, True, True])
        wk = run(briefing.week_agenda(7, "2026-11-18"))
        self.assertIn("Canvas", wk["calendars"])
        self.assertTrue(run(briefing.unlink_calendar(good["id"])))
        self.assertFalse(run(briefing.unlink_calendar("nope")))

    def test_several_market_sources_and_no_duplicates(self):
        async def a(start, end):
            return [{"date": "2026-11-26", "time": "", "title": "US stock market closed: Thanksgiving", "kind": "holiday"}]

        briefing.register_market_source(briefing.builtin_market_events)
        briefing.register_market_source(a)
        wk = run(briefing.week_agenda(7, "2026-11-23"))
        thu = next(d for d in wk["days"] if d["date"] == "2026-11-26")
        self.assertEqual([i["title"] for i in thu["items"]], ["US stock market closed: Thanksgiving"])
        fri = next(d for d in wk["days"] if d["date"] == "2026-11-27")
        self.assertIn("early", fri["items"][0]["title"])


class MarketCalendarTests(unittest.TestCase):
    def test_2026_holidays_match_the_exchange(self):
        want = {
            date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
            date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
            date(2026, 11, 26), date(2026, 12, 25),
        }
        self.assertEqual(set(briefing.market_holidays(2026)), want)

    def test_weekend_rules(self):
        self.assertNotIn(date(2021, 12, 31), briefing.market_holidays(2022))  # Sat New Year's
        self.assertIn(date(2027, 12, 24), briefing.market_holidays(2027))  # Sat Christmas
        self.assertNotIn(date(2027, 12, 24), briefing.market_early_closes(2027))
        self.assertIn(date(2027, 7, 5), briefing.market_holidays(2027))
        self.assertIn(date(2026, 11, 27), briefing.market_early_closes(2026))
        self.assertIn(date(2026, 12, 24), briefing.market_early_closes(2026))

    def test_options_expiry(self):
        ev = run(briefing.builtin_market_events(date(2026, 11, 1), date(2026, 12, 31)))
        got = {(e["date"], e["title"]) for e in ev}
        self.assertIn(("2026-11-20", "Monthly options expiration"), got)
        self.assertIn(("2026-12-18", "Quadruple witching: quarterly options and futures expire"), got)
        # April 2025: third Friday was Good Friday, so expiry moved to Thursday the 17th.
        apr = run(briefing.builtin_market_events(date(2025, 4, 1), date(2025, 4, 30)))
        self.assertIn("2025-04-17", [e["date"] for e in apr if e["kind"] == "options"])


if __name__ == "__main__":
    unittest.main()
