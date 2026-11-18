"""Offline tests for Gipsy Hub's tools, knowledge pack and tool loop.

Run from gipsy_hub/:   python -m unittest discover tests
No internet, Ollama, Piper or Whisper needed: a fake Ollama is started on a
local port, and market data is replaced by made-up numbers.
"""

import asyncio
import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402

import gipsy_hub  # noqa: E402
import tools  # noqa: E402
from knowledge import KnowledgePack, split_markdown  # noqa: E402

# ------------------------------------------------------------ fake Ollama --

fake = FastAPI()
SEEN: list[dict] = []


@fake.post("/api/chat")
async def fake_chat(req: Request):
    body = await req.json()
    SEEN.append(body)
    last = body["messages"][-1]

    def lines():
        if last["role"] == "user" and "gold" in last["content"].lower() and "tools" in body:
            call = {"function": {"name": "get_price", "arguments": {"symbol": "gold"}}}
            yield json.dumps({"message": {"role": "assistant", "content": "", "tool_calls": [call]}, "done": False}) + "\n"
            yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n"
            return
        if last["role"] == "tool":
            price = json.loads(last["content"])["price"]
            for word in ["Gold ", "is ", f"{price}."]:
                yield json.dumps({"message": {"role": "assistant", "content": word}, "done": False}) + "\n"
        else:
            yield json.dumps({"message": {"role": "assistant", "content": "Hello John."}, "done": False}) + "\n"
        yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@fake.post("/api/embed")
async def fake_embed(req: Request):
    return StreamingResponse(iter(["not json"]), status_code=404)  # "model not installed"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = free_port()
server = uvicorn.Server(uvicorn.Config(fake, host="127.0.0.1", port=PORT, log_level="error"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(100):
    if server.started:
        break
    time.sleep(0.05)

# ------------------------------------------------------- fake market data --

DAYS = 400
CLOSES = [100 - i * 0.1 for i in range(250)] + [75 + i * 0.5 for i in range(DAYS - 250)]  # fall, then rally
FAKE_CHART = {
    "meta": {"regularMarketPrice": CLOSES[-1], "currency": "USD", "shortName": "Gold", "regularMarketTime": 1_763_000_000},
    "timestamp": [1_700_000_000 + i * 86400 for i in range(DAYS)],
    "indicators": {"quote": [{"close": CLOSES}]},
}


async def fake_yahoo(symbol, rng, interval):
    return FAKE_CHART


tools._yahoo_chart = fake_yahoo


def run(coro):
    return asyncio.run(coro)


async def collect(body):
    return [json.loads(b) async for b in gipsy_hub.stream_ollama(body)]


class ToolTests(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(tools.resolve_symbol("Gold"), "GC=F")
        self.assertEqual(tools.resolve_symbol("the price of bitcoin"), "BTC-USD")
        self.assertEqual(tools.resolve_symbol("10 year yield"), "^TNX")
        self.assertEqual(tools.resolve_symbol("aapl"), "AAPL")

    def test_ema_matches_worked_example(self):
        # The example in knowledge/moving-averages.md
        self.assertEqual(tools.ema([10, 11, 12, 13, 9], 3), [11, 12, 10.5])

    def test_get_price(self):
        out = run(tools.get_price("gold"))
        self.assertEqual(out["symbol"], "GC=F")
        self.assertIn("change_today", out)

    def test_get_emas_finds_golden_cross(self):
        out = run(tools.get_emas("gold"))
        self.assertEqual(set(out["emas"]), {"EMA20", "EMA50", "EMA200"})
        self.assertEqual(out["emas"]["EMA20"]["price_is"], "above")
        self.assertIn("golden cross", out["crosses"]["EMA50 vs EMA200"]["type"])

    def test_rss_parse(self):
        xml = """<rss><channel><item><title>Fed holds rates - Reuters</title><source>Reuters</source>
        <pubDate>Tue, 18 Nov 2026 14:00:00 GMT</pubDate><link>https://x</link></item></channel></rss>"""
        items = tools._parse_rss(xml, 5)
        self.assertEqual(items[0]["title"], "Fed holds rates")
        self.assertEqual(items[0]["published"], "2026-11-18 14:00 UTC")

    def test_fred_parse(self):
        rows = tools._parse_fred_csv("observation_date,MORTGAGE30US\n2026-11-06,6.1\n2026-11-13,.\n")
        self.assertEqual(rows, [("2026-11-06", 6.1)])

    def test_unknown_tool_is_an_error_not_a_crash(self):
        self.assertIn("error", run(tools.run_tool("nope", {})))
        self.assertIn("error", run(tools.run_tool("get_price", {"wrong": 1})))


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.kp = KnowledgePack(HERE / "knowledge", f"http://127.0.0.1:{PORT}")

    def test_sections_loaded(self):
        self.assertGreater(len(self.kp.chunks), 30)
        for c in self.kp.chunks:
            self.assertLess(len(c.text.split()), 450, c.title)

    def test_split(self):
        chunks = split_markdown("x", "# Doc\n\nintro\n\n## One\nalpha\n\n## Two\nbeta\n")
        self.assertEqual([c.title for c in chunks], ["Doc > One", "Doc > Two"])

    def test_keyword_search_falls_back_without_embeddings(self):
        run(self.kp.build_index())
        self.assertFalse(self.kp.use_vectors)
        cases = {
            "what is a golden cross": "Crossovers",
            "how do I add an EMA on tradingview": "EMAs on TradingView",
            "why do bond prices fall when yields rise": "Bonds",
            "how do mortgage rates affect housing": "Housing",
            "gold silver ratio": "Silver",
        }
        for q, want in cases.items():
            hits = run(self.kp.search(q))
            self.assertTrue(hits, q)
            self.assertTrue(any(want.lower() in c.title.lower() for _, c in hits), (q, [c.title for _, c in hits]))

    def test_small_talk_gets_no_notes(self):
        self.assertEqual(run(self.kp.search("hey how are you")), [])


class ChatLoopTests(unittest.TestCase):
    def setUp(self):
        gipsy_hub.CFG["ollama_url"] = f"http://127.0.0.1:{PORT}"
        gipsy_hub.KNOWLEDGE.ollama_url = gipsy_hub.CFG["ollama_url"]
        SEEN.clear()

    def test_tool_call_round_trip(self):
        body = gipsy_hub.ChatIn(messages=[{"role": "user", "content": "What's gold at?"}])
        evs = run(collect(body))
        kinds = [e["type"] for e in evs]
        self.assertIn("tool", kinds)
        self.assertEqual(kinds[-1], "done")
        text = "".join(e["text"] for e in evs if e["type"] == "token")
        self.assertTrue(text.startswith("Gold is "), text)
        self.assertEqual(len(SEEN), 2)
        self.assertIn("tools", SEEN[0])
        sys_prompt = SEEN[0]["messages"][0]["content"]
        self.assertIn("It is now", sys_prompt)
        self.assertNotIn("{now}", sys_prompt)

    def test_knowledge_is_injected(self):
        body = gipsy_hub.ChatIn(messages=[{"role": "user", "content": "Explain the death cross on EMAs"}])
        evs = run(collect(body))
        self.assertEqual(evs[1]["name"], "knowledge")
        msgs = SEEN[0]["messages"]
        self.assertEqual(msgs[-1]["role"], "user")
        self.assertIn("knowledge pack", msgs[-2]["content"])

    def test_plain_chat(self):
        body = gipsy_hub.ChatIn(messages=[{"role": "user", "content": "hi"}])
        evs = run(collect(body))
        self.assertEqual("".join(e["text"] for e in evs if e["type"] == "token"), "Hello John.")


if __name__ == "__main__":
    unittest.main()
