"""Small-talk shouldn't pull in lesson notes; weather needs a place.
Run from gipsy_hub/:   python -m unittest discover tests
"""

import asyncio
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import tools  # noqa: E402
from knowledge import KnowledgePack  # noqa: E402


class ChatQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.k = KnowledgePack(HERE / "knowledge", "http://127.0.0.1:9", "none")
        cls.k.use_vectors = False

    def test_small_talk_skips_notes(self):
        for msg in ["Hello.", "Sounds good.", "What's the weather today?", "set a reminder", "hey gipsy, kaiju incoming"]:
            self.assertFalse(self.k.is_on_topic(msg), msg)

    def test_market_questions_use_notes(self):
        for msg in ["what is a golden cross", "and what about silver?", "what does a candle mean", "how do bond yields affect gold"]:
            self.assertTrue(self.k.is_on_topic(msg), msg)

    def test_one_common_word_is_not_a_match(self):
        self.assertEqual(asyncio.run(self.k.search("What's the weather today?")), [])

    def test_weather_tool_is_offered_and_needs_a_place(self):
        self.assertIn("get_weather", [t["function"]["name"] for t in tools.TOOLS])
        tools.SETTINGS["home_location"] = ""
        out = asyncio.run(tools.run_tool("get_weather", {}))
        self.assertIn("home_location", out["error"])


if __name__ == "__main__":
    unittest.main()
