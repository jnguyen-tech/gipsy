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
import io
import json
import logging
import os
import re
import tempfile
import urllib.request
import wave
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from knowledge import KnowledgePack
from tools import TOOLS, describe_call, run_tool

HERE = Path(__file__).resolve().parent
log = logging.getLogger("gipsy")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

# ---------------------------------------------------------------- config ----

DEFAULT_CONFIG: dict[str, Any] = {
    "host": "0.0.0.0",
    "port": 8765,
    # Shared secret the apps send in the X-Gipsy-Key header. Empty = no check.
    "api_key": "",
    "ollama_url": "http://127.0.0.1:11434",
    "daily_model": "qwen3:8b",
    "deep_model": "qwen3:14b",
    "context_length": 16384,
    "keep_alive": "15m",
    # Piper voice. en_GB-alan-medium is a calm British male.
    "voice": "en_GB-alan-medium",
    # < 1.0 lowers the pitch (deeper). 0.90 is a good "big robot" setting.
    "voice_pitch": 0.90,
    # > 1.0 speaks slower. Applied before the pitch trick.
    "voice_speed": 1.0,
    # Whisper model for speech-to-text. base.en is fast on CPU; small.en is
    # more accurate. "cpu" keeps the GPU free for the LLM.
    "whisper_model": "base.en",
    "whisper_device": "cpu",
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
    "system_prompt": (
        "You are Gipsy, a friendly robot desk companion built by John. "
        "You run fully offline on John's own PC. You speak with calm, dry "
        "British wit. Keep answers short and conversational (one to four "
        "sentences) unless John asks for detail. Your replies may be read "
        "aloud, so avoid markdown tables, code blocks and emoji unless asked."
    ),
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
    path = HERE / "config.json"
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    else:
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        log.info("Wrote default config to %s", path)
    return cfg


CFG = load_config()
VOICES_DIR = HERE / "voices"
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

_voice = None
_voice_lock = asyncio.Lock()


def _voice_paths(name: str) -> tuple[Path, Path]:
    return VOICES_DIR / f"{name}.onnx", VOICES_DIR / f"{name}.onnx.json"


def ensure_voice(name: str) -> Path:
    """Download the Piper voice from Hugging Face the first time."""
    onnx, cfg = _voice_paths(name)
    if onnx.exists() and cfg.exists():
        return onnx
    m = re.match(r"^(?P<lang>[a-z]{2})_(?P<region>[A-Z]{2})-(?P<voice>[a-z0-9_]+)-(?P<q>x_low|low|medium|high)$", name)
    if not m:
        raise RuntimeError(f"Voice name {name!r} doesn't look like en_GB-alan-medium")
    VOICES_DIR.mkdir(exist_ok=True)
    code = f"{m['lang']}_{m['region']}"
    base = (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
        f"{m['lang']}/{code}/{m['voice']}/{m['q']}/{name}"
    )
    for ext, dest in ((".onnx", onnx), (".onnx.json", cfg)):
        log.info("Downloading voice file %s%s ...", name, ext)
        part = dest.with_suffix(dest.suffix + ".part")
        urllib.request.urlretrieve(base + ext + "?download=true", part)
        part.replace(dest)
    return onnx


def get_voice():
    global _voice
    if _voice is None:
        from piper import PiperVoice

        _voice = PiperVoice.load(ensure_voice(CFG["voice"]))
        log.info("Piper voice loaded: %s", CFG["voice"])
    return _voice


_MD = re.compile(r"[*_`#>|~]+")
_THINK = re.compile(r"<think>.*?</think>", re.S)


def clean_for_speech(text: str) -> str:
    text = _THINK.sub("", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](url) -> label
    text = _MD.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def synthesize_wav(text: str) -> bytes:
    """Piper -> 16-bit mono WAV bytes, pitched down for a deeper voice.

    Pitch trick: we make Piper speak faster by the pitch factor, then label
    the WAV with a lower sample rate. Played back, the voice is deeper but
    at the normal speed, with zero extra processing.
    """
    from piper import SynthesisConfig

    voice = get_voice()
    pitch = float(CFG.get("voice_pitch", 1.0))
    speed = float(CFG.get("voice_speed", 1.0))
    base = getattr(voice.config, "length_scale", 1.0) or 1.0
    syn = SynthesisConfig(length_scale=base * speed * pitch)
    pcm = bytearray()
    rate = voice.config.sample_rate
    for chunk in voice.synthesize(text, syn_config=syn):
        rate = chunk.sample_rate
        pcm += chunk.audio_int16_bytes
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate * pitch))
        w.writeframes(bytes(pcm))
    return buf.getvalue()


class TtsIn(BaseModel):
    text: str


@app.post("/api/tts", dependencies=[Depends(check_key)])
async def tts(body: TtsIn) -> Response:
    text = clean_for_speech(body.text)
    if not text:
        raise HTTPException(400, "Nothing to say")
    async with _voice_lock:
        wav = await asyncio.to_thread(synthesize_wav, text)
    return Response(content=wav, media_type="audio/wav")


# ------------------------------------------------------------------- STT ----

_whisper = None


def get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel

        device = CFG.get("whisper_device", "cpu")
        compute = "int8" if device == "cpu" else "float16"
        _whisper = WhisperModel(CFG["whisper_model"], device=device, compute_type=compute)
        log.info("Whisper loaded: %s on %s", CFG["whisper_model"], device)
    return _whisper


def transcribe_file(path: str) -> str:
    segments, _ = get_whisper().transcribe(
        path,
        language="en",
        beam_size=1,
        vad_filter=True,
        # Nudges Whisper to spell the wake word the same way every time.
        initial_prompt="Hey Gipsy.",
    )
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
        async with _stt_lock:
            text = await asyncio.to_thread(transcribe_file, tmp)
    finally:
        os.unlink(tmp)
    log.info("Heard: %r", text)
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
    return [{"role": "system", "content": text}]


async def knowledge_for(messages: list[dict[str, Any]]) -> tuple[Optional[str], list[str]]:
    """RAG step: find lesson sections that match John's latest message."""
    if not CFG.get("knowledge_enabled", True):
        return None, []
    users = [m["content"] for m in messages if m["role"] == "user"]
    if not users:
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
                    "options": {"num_ctx": CFG["context_length"]},
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
                            content += msg["content"]
                            yield ev("token", text=msg["content"])
                        if msg.get("tool_calls"):
                            calls += msg["tool_calls"]
                        if chunk.get("done"):
                            break
                if not calls:
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
             "get_emas": "symbol", "get_economic": "series"}.get(name, "query")
    return await run_tool(name, {first: q} if q else {})


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
        "voice": CFG["voice"],
        "tools": [t["function"]["name"] for t in TOOLS] if CFG.get("tools_enabled", True) else [],
        "knowledge_sections": len(KNOWLEDGE.chunks),
        "knowledge_mode": "embeddings" if KNOWLEDGE.use_vectors else "keywords",
    }


@app.on_event("startup")
async def warm_up() -> None:
    # Load the voice + whisper in the background so the first request is fast.
    async def _load() -> None:
        for fn in (get_voice, get_whisper):
            try:
                await asyncio.to_thread(fn)
            except Exception as e:
                log.warning("Warm-up of %s failed: %s", fn.__name__, e)

    asyncio.create_task(_load())
    if CFG.get("knowledge_enabled", True):
        asyncio.create_task(KNOWLEDGE.build_index())


if __name__ == "__main__":
    import socket
    import sys

    if sys.stdout is None:  # started hidden with pythonw: log to a file
        sys.stdout = sys.stderr = open(HERE / "hub.log", "a", encoding="utf-8", buffering=1)
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
    print(f"  On your Wi-Fi:   http://{lan_ip}:{CFG['port']}")
    print("  On Tailscale:    http://<this PC's 100.x address>:%d" % CFG["port"])
    print()
    uvicorn.run(app, host=CFG["host"], port=int(CFG["port"]), log_level="warning")
