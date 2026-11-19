"""
Gipsy Hub: the small server that runs on John's PC next to Ollama.

The Gipsy apps (iPhone + Windows) talk only to this hub. It does three jobs:
  1. /api/chat  - streams replies from Ollama (qwen3:8b daily, qwen3:14b deep)
  2. /api/tts   - turns text into speech with Piper (deep British male voice)
  3. /api/stt   - turns recorded speech into text with faster-whisper

Chat can also use tools (tools.py: news, web search, prices, EMAs, economic
data) and a markets knowledge pack (knowledge.py + knowledge/*.md, RAG).

Ollama itself stays private on 127.0.0.1:11434. Only this hub listens on the
network (port 8765), so your phone reaches it over Wi-Fi or Tailscale.

Run:  python gipsy_hub.py          (see README.md for setup)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from knowledge import KnowledgePack
import markets
import briefing
import voice as voice_mod
import tools as _tools_module
from tools import TOOLS, describe_call, run_tool

# Market calendar + portfolio tools live in markets.py.
TOOLS += markets.TOOLS
_tools_module.FUNCTIONS.update(markets.FUNCTIONS)
for _name, _line in markets.DESCRIBE.items():
    _tools_module.EXTRA_DESCRIPTIONS[_name] = lambda args, _line=_line: _line

HERE = Path(__file__).resolve().parent
# Where config.json, downloaded voices and hub.log live. Next to this file by
# default; the Docker image sets GIPSY_DATA_DIR=/data so they survive updates.
DATA_DIR = Path(os.environ.get("GIPSY_DATA_DIR") or HERE)
DATA_DIR.mkdir(parents=True, exist_ok=True)
IN_DOCKER = os.environ.get("GIPSY_IN_DOCKER") == "1"
log = logging.getLogger("gipsy")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

# ---------------------------------------------------------------- config ----

DEFAULT_CONFIG: dict[str, Any] = {
    "host": "0.0.0.0",
    "port": 8765,
    # Shared secret the apps send in the X-Gipsy-Key header. Empty = no check.
    "api_key": "",
    # In Docker this comes from GIPSY_OLLAMA_URL (http://host.docker.internal:11434).
    "ollama_url": os.environ.get("GIPSY_OLLAMA_URL") or "http://127.0.0.1:11434",
    "daily_model": "qwen3:8b",
    "deep_model": "qwen3:14b",
    "context_length": 16384,
    "keep_alive": "15m",
    # Gipsy's voice. See voice.py for the list (or GET /api/voices):
    # "commander" (default, Piper), "marshal" (best, needs Kokoro), "classic"...
    "voice_preset": "commander",
    # Optional fine-tuning of the chosen preset. null = use the preset's value.
    # pitch < 1 is deeper, pace > 1 talks faster, warmth/grit go from 0 to 1.
    "voice_pitch_override": None,
    "voice_pace_override": None,
    "voice_warmth_override": None,
    "voice_grit_override": None,
    # Run Piper on the graphics card (needs onnxruntime-gpu). The CPU is
    # idle while qwen3 runs on the GPU, so CPU is usually the better choice.
    "voice_use_gpu": False,
    # Used only by the "classic" preset (the voice from before).
    "voice": "en_GB-alan-medium",
    "voice_pitch": 0.90,
    "voice_speed": 1.0,
    # Whisper model for speech-to-text. base.en is fast on CPU; small.en is
    # more accurate. "cpu" keeps the GPU free for the LLM.
    "whisper_model": "base.en",
    "whisper_device": "cpu",
    # Load the daily model into the graphics card when the hub starts, so
    # your first question doesn't wait for it.
    "preload_model": True,
    # "Hey Gipsy, there's a kaiju" easter egg. Gipsy says this line in its own
    # voice, then plays your battle song. Point kaiju_song_path at an audio
    # file you own (mp3/m4a/wav), e.g. D:\\Music\\battle-song.mp3.
    # kaiju_song_rate < 1.0 slows it down (0.85 = slowed). Use 1.0 if your
    # file is already a slowed version. A kaiju_song_url plays at its own speed.
    "kaiju_line": "Kaiju on the scanner. Suit up, John. Either we stop it here, or it stops us.",
    "kaiju_song_path": "",
    # Or a link (YouTube, Spotify...) the app opens instead of a local file.
    # Used only when kaiju_song_path is empty.
    "kaiju_song_url": "",
    "kaiju_song_rate": 0.85,
    # Let the model call tools (news, web search, prices, EMAs, FRED data).
    "tools_enabled": True,
    "max_tool_rounds": 4,
    # Markets knowledge pack (knowledge/*.md) searched for every question.
    "knowledge_enabled": True,
    "embed_model": "nomic-embed-text",
    "knowledge_results": 3,
    # How close a section must be to count (embeddings, 0-1). Lower = more notes.
    "knowledge_min_score": 0.55,
    # This week's tasks (briefing.py). Add iCal (.ics) feeds here: Google
    # Calendar's "secret address in iCal format", your school's calendar feed
    # (Canvas/Schoology/Classroom), Outlook or iCloud published calendars.
    # kind: "school", "appointment" or "calendar".
    "timezone": "America/Chicago",
    "calendars": [],
    "market_events_enabled": True,
    "system_prompt": (
        "You are Gipsy, a friendly robot desk companion built by John. "
        "You run fully offline on John's own PC. You speak with calm, dry "
        "British wit. Keep answers short and conversational (one to four "
        "sentences) unless John asks for detail. Your replies may be read "
        "aloud, so avoid markdown tables, code blocks and emoji unless asked."
    ),
    # City for weather questions when John doesn't name one, e.g. "Oklahoma City".
    "home_location": "",
    # House rules added to every chat (kept separate so updates reach old configs).
    "behaviour_prompt": (
        "Rules: Never say you did something (set a reminder or alarm, sent a message, "
        "saved a file) unless a tool actually did it in this chat. You can add items to "
        "John's to-do list with add_task; you cannot set timed reminders or alarms, so say "
        "so and offer add_task instead. For weather, call get_weather; for other live facts, "
        "call web_search or search_news instead of saying you don't have the data. If John's "
        "message is unclear or looks like a speech-to-text mistake, ask what he meant; "
        "never just repeat your previous answer."
    ),
    # Sampling for the daily (non-thinking) model. These are Qwen3's suggested
    # settings; presence_penalty stops it repeating itself.
    "model_options": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 1.0},
    # Added after system_prompt on every chat. {now} becomes the PC's date/time.
    "tools_prompt": (
        "It is now {now}. Your built-in knowledge stops well before today, so for "
        "anything current (news, prices, 'today', 'latest', recent events, who holds "
        "a job now) call a tool instead of guessing, and briefly say where the "
        "information came from. If a tool fails, say so plainly. "
        "You are also John's patient markets tutor: TradingView, chart reading, EMAs "
        "and how gold, silver, bonds and yields, the dollar, crypto and housing relate. "
        "Explain simply, use small examples, and check he understood. This is "
        "education only: never tell John to buy or sell anything, never predict a "
        "price, and mention that live quotes can be delayed."
    ),
}


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    path = DATA_DIR / "config.json"
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    else:
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        log.info("Wrote default config to %s", path)
    return cfg


CFG = load_config()

# This week's tasks: calendars + to-do list (+ market events when markets.py is present).
_tools_module.SETTINGS["home_location"] = CFG.get("home_location", "")
briefing.init(CFG)
briefing.install_tools(_tools_module)
try:
    import markets  # noqa: E402

    briefing.register_market_source(markets.market_events)
except ImportError:
    pass
VOICES_DIR = DATA_DIR / "voices"
KNOWLEDGE = KnowledgePack(HERE / "knowledge", CFG["ollama_url"], CFG.get("embed_model", "nomic-embed-text"))

# ------------------------------------------------------------------ auth ----


def check_key(x_gipsy_key: Optional[str] = Header(default=None)) -> None:
    want = CFG.get("api_key") or ""
    if want and x_gipsy_key != want:
        raise HTTPException(status_code=401, detail="Wrong or missing X-Gipsy-Key")


app = FastAPI(title="Gipsy Hub", version="1.1")

# Lets the optional browser build of the app talk to the hub too.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ------------------------------------------------------------------- TTS ----

VOICE = voice_mod.Voice(CFG, VOICES_DIR)
_voice_lock = asyncio.Lock()
# What went wrong while loading the voice / Whisper, shown in /api/health.
PROBLEMS: dict[str, str] = {}

_MD = re.compile(r"[*_`#>|~]+")
_THINK = re.compile(r"<think>.*?</think>", re.S)


def clean_for_speech(text: str) -> str:
    text = _THINK.sub("", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](url) -> label
    text = _MD.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def synthesize_wav(text: str, preset: Optional[str] = None) -> bytes:
    """Text -> WAV in Gipsy's voice (see voice.py for presets and effects)."""
    return VOICE.synthesize(text, preset)


def save_config_value(key: str, value: Any) -> None:
    """Change one setting in config.json and keep everything else."""
    path = DATA_DIR / "config.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data[key] = value
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    CFG[key] = value


class TtsIn(BaseModel):
    text: str
    preset: Optional[str] = None  # try another voice without switching to it


@app.post("/api/tts", dependencies=[Depends(check_key)])
async def tts(body: TtsIn) -> Response:
    text = clean_for_speech(body.text)
    if not text:
        raise HTTPException(400, "Nothing to say")
    if body.preset and body.preset not in voice_mod.PRESETS:
        raise HTTPException(400, f"No voice called {body.preset}")
    try:
        async with _voice_lock:
            wav = await asyncio.to_thread(synthesize_wav, text, body.preset)
    except voice_mod.VoiceUnavailable as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        log.exception("Voice failed")
        raise HTTPException(500, f"Voice failed: {type(e).__name__}: {e}")
    return Response(content=wav, media_type="audio/wav")


@app.get("/api/voices", dependencies=[Depends(check_key)])
async def voices() -> dict[str, Any]:
    return {"current": VOICE.preset_name, "pace": VOICE.preset().get("pace", 1.0), "voices": VOICE.list()}


class VoicePick(BaseModel):
    preset: str


@app.post("/api/voice", dependencies=[Depends(check_key)])
async def pick_voice(body: VoicePick) -> dict[str, Any]:
    if body.preset not in voice_mod.PRESETS:
        raise HTTPException(400, f"No voice called {body.preset}")
    ok, why = VOICE.available(body.preset)
    if not ok:
        raise HTTPException(409, why)
    save_config_value("voice_preset", body.preset)
    log.info("Voice changed to %s", body.preset)
    return {"current": body.preset}


class PaceIn(BaseModel):
    pace: Optional[float] = None  # 1.0 = normal, 1.25 = 25% faster; null = preset's own


@app.post("/api/voice/pace", dependencies=[Depends(check_key)])
async def set_pace(body: PaceIn) -> dict[str, Any]:
    """Talking speed from the app's slider, saved in config.json."""
    pace = None if body.pace is None else round(max(0.7, min(1.6, body.pace)), 2)
    save_config_value("voice_pace_override", pace)
    log.info("Talking speed set to %s", pace if pace is not None else "the voice's default")
    return {"pace": VOICE.preset().get("pace", 1.0)}


# ------------------------------------------------------------------- STT ----

_whisper = None
_whisper_lock = threading.Lock()


def get_whisper():
    """Load Whisper once. If the fast settings don't work on this PC, fall
    back to safer ones instead of failing."""
    global _whisper
    with _whisper_lock:
        if _whisper is not None:
            return _whisper
        from faster_whisper import WhisperModel

        device = CFG.get("whisper_device", "cpu")
        tries = [(device, "int8" if device == "cpu" else "float16")]
        if tries[0] != ("cpu", "int8"):
            tries.append(("cpu", "int8"))
        tries.append(("cpu", "float32"))
        last: Optional[Exception] = None
        for dev, compute in tries:
            try:
                _whisper = WhisperModel(CFG["whisper_model"], device=dev, compute_type=compute)
                log.info("Whisper loaded: %s on %s (%s)", CFG["whisper_model"], dev, compute)
                PROBLEMS.pop("hearing", None)
                return _whisper
            except Exception as e:
                log.warning("Whisper on %s/%s didn't load: %s", dev, compute, e)
                last = e
        raise RuntimeError(f"Whisper couldn't load ({type(last).__name__}: {last})")


def read_wav_16k(path: str):
    """Read a 16-bit WAV into the float array Whisper wants (16 kHz mono).

    Doing this ourselves avoids the audio decoder library, which is the most
    common thing to break on Windows. Returns None for non-WAV files, so
    Whisper can try them itself.
    """
    import numpy as np

    try:
        with wave.open(path, "rb") as w:
            rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError):
        return None
    if width != 2 or not raw:
        return None
    x = np.frombuffer(raw[: len(raw) // (2 * ch) * 2 * ch], dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if rate != 16000 and x.size:
        n = int(round(x.size * 16000 / rate))
        x = np.interp(np.linspace(0, x.size - 1, n), np.arange(x.size), x).astype(np.float32)
    return x


def transcribe_file(path: str) -> str:
    audio = read_wav_16k(path)
    source = audio if audio is not None else path
    model = get_whisper()
    opts = dict(language="en", beam_size=1, initial_prompt="Hey Gipsy.")  # nudges the spelling
    try:
        segments, _ = model.transcribe(source, vad_filter=True, **opts)
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception as e:
        # The silence filter needs onnxruntime; try once without it.
        log.warning("Whisper with silence filter failed (%s); retrying without it", e)
        segments, _ = model.transcribe(source, vad_filter=False, **opts)
        return " ".join(s.text.strip() for s in segments).strip()


_stt_lock = asyncio.Lock()


@app.post("/api/stt", dependencies=[Depends(check_key)])
async def stt(audio: UploadFile = File(...)) -> dict[str, str]:
    data = await audio.read()
    if len(data) < 1000:
        return {"text": ""}
    suffix = Path(audio.filename or "clip.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        t = time.perf_counter()
        async with _stt_lock:
            text = await asyncio.to_thread(transcribe_file, tmp)
    except Exception as e:
        # Print the full error in the hub window AND tell the app why.
        log.exception("Hearing failed")
        reason = f"{type(e).__name__}: {e}"
        PROBLEMS["hearing"] = reason
        raise HTTPException(500, reason[:400])
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    log.info("Heard (%.1f s): %r", time.perf_counter() - t, text)
    return {"text": text}


# ------------------------------------------------------------------ chat ----


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    messages: list[ChatMessage]
    model: Optional[str] = None  # "daily", "deep" or an exact Ollama tag
    think: Optional[bool] = None  # show qwen3's reasoning (slower)


def resolve_model(name: Optional[str]) -> str:
    if not name or name == "daily":
        return CFG["daily_model"]
    if name == "deep":
        return CFG["deep_model"]
    return name


def system_messages() -> list[dict[str, Any]]:
    text = CFG["system_prompt"]
    if CFG.get("tools_enabled", True) or CFG.get("knowledge_enabled", True):
        now = datetime.now().astimezone().strftime("%A %d %B %Y, %I:%M %p %Z")
        text += "\n\n" + CFG.get("tools_prompt", "").replace("{now}", now)
    if CFG.get("behaviour_prompt"):
        text += "\n\n" + CFG["behaviour_prompt"]
    return [{"role": "system", "content": text}]


async def knowledge_for(messages: list[dict[str, Any]]) -> tuple[Optional[str], list[str]]:
    """RAG step: find lesson sections that match John's latest message."""
    if not CFG.get("knowledge_enabled", True):
        return None, []
    users = [m["content"] for m in messages if m["role"] == "user"]
    if not users:
        return None, []
    # Small talk ("Hello", "Sounds good", "what's the weather") skips the notes:
    # the latest message has to mention something the lessons are about.
    if not KNOWLEDGE.is_on_topic(users[-1]):
        return None, []
    # Include the previous question too, so "and what about silver?" still works.
    query = users[-1] if len(users) < 2 else users[-2][-200:] + "\n" + users[-1]
    k = int(CFG.get("knowledge_results", 3))
    cut = float(CFG["knowledge_min_score"]) if KNOWLEDGE.use_vectors else None
    hits = await KNOWLEDGE.search(query, k=k, min_score=cut)
    if not hits:
        hits = await KNOWLEDGE.search(users[-1], k=k, min_score=cut)
    if not hits:
        return None, []
    return KNOWLEDGE.as_context(hits), [c.title for _, c in hits]


async def stream_ollama(body: ChatIn) -> AsyncIterator[bytes]:
    """Re-emit Ollama's stream as simple NDJSON events for the apps:
    {"type":"thinking","text":...} {"type":"token","text":...}
    {"type":"tool","name":...,"text":...}  (a tool or the knowledge pack is in use)
    {"type":"done","model":...}    {"type":"error","text":...}

    Tool loop: send the chat with the tool list. If the model answers with
    tool calls instead of text, run them, append the results as "tool"
    messages and ask again, up to max_tool_rounds times.
    """
    model = resolve_model(body.model)
    think = body.think if body.think is not None else (model == CFG["deep_model"])
    history = [m.model_dump() for m in body.messages[-30:]]
    messages: list[dict[str, Any]] = system_messages()

    def ev(kind: str, **kw: Any) -> bytes:
        return (json.dumps({"type": kind, **kw}) + "\n").encode()

    yield ev("start", model=model, think=think)
    t0 = time.perf_counter()
    first_word: Optional[float] = None

    try:
        notes, titles = await knowledge_for(history)
    except Exception as e:
        log.warning("Knowledge search failed: %s", e)
        notes, titles = None, []
    if notes:
        yield ev("tool", name="knowledge", text="Reading my notes: " + "; ".join(t.split(" > ")[-1] for t in titles))
        messages += history[:-1] + [{"role": "system", "content": notes}] + history[-1:]
    else:
        messages += history

    use_tools = bool(CFG.get("tools_enabled", True))
    rounds = int(CFG.get("max_tool_rounds", 4))
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=5)) as client:
            for round_no in range(rounds + 1):
                payload: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "stream": True,
                    "think": think,
                    "keep_alive": CFG["keep_alive"],
                    "options": {
                        **({} if think else (CFG.get("model_options") or {})),
                        "num_ctx": CFG["context_length"],
                    },
                }
                # Last round: no tools, so the model has to answer in words.
                if use_tools and round_no < rounds:
                    payload["tools"] = TOOLS
                calls: list[dict[str, Any]] = []
                content = ""
                async with client.stream("POST", f"{CFG['ollama_url']}/api/chat", json=payload) as r:
                    if r.status_code != 200:
                        msg = (await r.aread()).decode(errors="ignore")[:300]
                        if "tools" in payload and "does not support tools" in msg:
                            log.warning("%s can't use tools; answering without them", model)
                            use_tools = False
                            continue
                        yield ev("error", text=f"Ollama said {r.status_code}: {msg}")
                        return
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        msg = chunk.get("message") or {}
                        if msg.get("thinking"):
                            yield ev("thinking", text=msg["thinking"])
                        if msg.get("content"):
                            if first_word is None:
                                first_word = time.perf_counter() - t0
                                log.info("First words from %s after %.1f s", model, first_word)
                            content += msg["content"]
                            yield ev("token", text=msg["content"])
                        if msg.get("tool_calls"):
                            calls += msg["tool_calls"]
                        if chunk.get("done"):
                            break
                if not calls:
                    log.info("Reply finished in %.1f s (%d chars)", time.perf_counter() - t0, len(content))
                    yield ev("done", model=model)
                    return
                messages.append({"role": "assistant", "content": content, "tool_calls": calls})
                for call in calls:
                    fn = call.get("function") or {}
                    name = fn.get("name", "")
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except ValueError:
                            args = {}
                    yield ev("tool", name=name, text=describe_call(name, args))
                    log.info("Tool %s %s", name, args)
                    result = await run_tool(name, args)
                    messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, ensure_ascii=False)[:6000]})
            yield ev("done", model=model)
    except httpx.ConnectError:
        yield ev("error", text="I can't reach Ollama on this PC. Is the Ollama app running?")
    except Exception as e:  # keep the app informed instead of hanging
        yield ev("error", text=f"Hub error: {e}")


@app.post("/api/chat", dependencies=[Depends(check_key)])
async def chat(body: ChatIn) -> StreamingResponse:
    return StreamingResponse(stream_ollama(body), media_type="application/x-ndjson")


# ------------------------------------------------------------- kaiju alert --


@app.get("/api/kaiju", dependencies=[Depends(check_key)])
async def kaiju() -> dict[str, Any]:
    song = Path(CFG.get("kaiju_song_path") or "")
    return {
        "line": CFG.get("kaiju_line", ""),
        "has_song": bool(CFG.get("kaiju_song_path")) and song.is_file(),
        "song_ext": song.suffix.lower() or ".mp3",
        "rate": float(CFG.get("kaiju_song_rate", 1.0)),
        "song_url": CFG.get("kaiju_song_url", ""),
    }


@app.get("/api/kaiju/song", dependencies=[Depends(check_key)])
async def kaiju_song() -> FileResponse:
    song = Path(CFG.get("kaiju_song_path") or "")
    if not song.is_file():
        raise HTTPException(404, "Set kaiju_song_path in config.json to an audio file")
    return FileResponse(song)


# ------------------------------------------------- tools and knowledge ----


@app.get("/api/knowledge/search", dependencies=[Depends(check_key)])
async def knowledge_search(q: str, k: int = 3) -> dict[str, Any]:
    """Try the RAG search yourself: /api/knowledge/search?q=what is a golden cross"""
    hits = await KNOWLEDGE.search(q, k=k, min_score=0)
    return {
        "mode": "embeddings" if KNOWLEDGE.use_vectors else "keywords",
        "results": [{"score": round(s, 3), "section": c.title, "text": c.text[:300]} for s, c in hits],
    }


@app.get("/api/tools/{name}", dependencies=[Depends(check_key)])
async def tool_test(name: str, q: str = "") -> dict[str, Any]:
    """Run one tool by hand, e.g. /api/tools/get_price?q=gold"""
    first = {"search_news": "query", "web_search": "query", "get_price": "symbol",
             "get_emas": "symbol", "get_economic": "series", "market_calendar": "days"}.get(name, "query")
    return await run_tool(name, {first: q} if q else {})


# ------------------------------------------------------------- this week ----


@app.get("/api/week", dependencies=[Depends(check_key)])
async def week(days: int = 7, start: str = "") -> dict[str, Any]:
    return await briefing.week_agenda(days, start)


class TaskIn(BaseModel):
    title: str
    due: str = ""
    kind: str = "task"


@app.get("/api/tasks", dependencies=[Depends(check_key)])
async def tasks_list(include_done: bool = False) -> list[dict[str, Any]]:
    return await briefing.list_tasks(include_done)


@app.post("/api/tasks", dependencies=[Depends(check_key)])
async def tasks_add(body: TaskIn) -> dict[str, Any]:
    try:
        return await briefing.add_task(body.title, body.due, body.kind)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/tasks/{task_id}/done", dependencies=[Depends(check_key)])
async def tasks_done(task_id: str) -> dict[str, Any]:
    try:
        return await briefing.complete_task(task_id)
    except LookupError as e:
        raise HTTPException(404, str(e))


@app.delete("/api/tasks/{task_id}", dependencies=[Depends(check_key)])
async def tasks_delete(task_id: str) -> dict[str, bool]:
    return {"deleted": await briefing.delete_task(task_id)}


class CalendarIn(BaseModel):
    name: str = ""
    url: str
    kind: str = "calendar"  # "school", "appointment" or "calendar"


@app.get("/api/calendars", dependencies=[Depends(check_key)])
async def calendars_list() -> list[dict[str, Any]]:
    """Linked calendars. Links are masked: an iCal link is as good as a password."""
    return [briefing.public_calendar(c) for c in briefing.all_calendars()]


@app.post("/api/calendars", dependencies=[Depends(check_key)])
async def calendars_add(body: CalendarIn) -> dict[str, Any]:
    try:
        return await briefing.link_calendar(body.name, body.url, body.kind)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/calendars/{cal_id}", dependencies=[Depends(check_key)])
async def calendars_delete(cal_id: str) -> dict[str, bool]:
    return {"deleted": await briefing.unlink_calendar(cal_id)}


# ---------------------------------------------------------------- health ----


@app.get("/api/health", dependencies=[Depends(check_key)])
async def health() -> dict[str, Any]:
    models: list[str] = []
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{CFG['ollama_url']}/api/tags")
            ollama_ok = r.status_code == 200
            models = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return {
        "name": "Gipsy Hub",
        "ollama": ollama_ok,
        "models": models,
        "daily_model": CFG["daily_model"],
        "deep_model": CFG["deep_model"],
        "voice": VOICE.preset_name,
        "voice_engine": voice_mod.PRESETS[VOICE.preset_name]["engine"],
        # Anything that failed to load, e.g. {"hearing": "..."}. Empty = all good.
        "problems": dict(PROBLEMS),
        "tools": [t["function"]["name"] for t in TOOLS] if CFG.get("tools_enabled", True) else [],
        "knowledge_sections": len(KNOWLEDGE.chunks),
        "knowledge_mode": "embeddings" if KNOWLEDGE.use_vectors else "keywords",
    }


async def preload_model() -> None:
    """Ask Ollama to load the daily model now (an empty request just loads it)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5)) as client:
            t = time.perf_counter()
            await client.post(
                f"{CFG['ollama_url']}/api/generate",
                json={"model": CFG["daily_model"], "keep_alive": CFG["keep_alive"]},
            )
            log.info("%s is loaded and ready (%.1f s)", CFG["daily_model"], time.perf_counter() - t)
    except Exception as e:
        log.warning("Couldn't preload %s: %s", CFG["daily_model"], e)


@app.on_event("startup")
async def warm_up() -> None:
    # Load the voice + Whisper in the background so the first request is fast.
    async def _load() -> None:
        try:
            await asyncio.to_thread(VOICE.load)
            PROBLEMS.pop("voice", None)
        except Exception as e:
            PROBLEMS["voice"] = f"{type(e).__name__}: {e}"
            log.warning("Voice %s didn't load: %s", VOICE.preset_name, e)
            if voice_mod.PRESETS[VOICE.preset_name]["engine"] != "piper":
                log.warning("Falling back to the commander voice for now.")
                CFG["voice_preset"] = voice_mod.DEFAULT_PRESET
        try:
            await asyncio.to_thread(get_whisper)
        except Exception as e:
            PROBLEMS["hearing"] = f"{type(e).__name__}: {e}"
            log.exception("Whisper (hearing) didn't load")

    asyncio.create_task(_load())
    if CFG.get("preload_model", True):
        asyncio.create_task(preload_model())
    if CFG.get("knowledge_enabled", True):
        asyncio.create_task(KNOWLEDGE.build_index())


if __name__ == "__main__":
    import socket
    import sys

    if sys.stdout is None:  # started hidden with pythonw: log to a file
        sys.stdout = sys.stderr = open(DATA_DIR / "hub.log", "a", encoding="utf-8", buffering=1)
        logging.getLogger().handlers[0].setStream(sys.stderr)

    import uvicorn

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        lan_ip = "127.0.0.1"
    print()
    print("  GIPSY HUB is starting")
    print(f"  On this PC:      http://127.0.0.1:{CFG['port']}")
    if IN_DOCKER:
        # Inside a container the address above is the container's own, so
        # point at the PC instead (Docker forwards the port).
        print("  On your Wi-Fi:   http://<this PC's Wi-Fi IP>:%d   (run ipconfig to see it)" % CFG["port"])
    else:
        print(f"  On your Wi-Fi:   http://{lan_ip}:{CFG['port']}")
    print("  On Tailscale:    http://<this PC's 100.x address>:%d" % CFG["port"])
    print(f"  Ollama:          {CFG['ollama_url']}")
    print()
    uvicorn.run(app, host=CFG["host"], port=int(CFG["port"]), log_level="warning")
