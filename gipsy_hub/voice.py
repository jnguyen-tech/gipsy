"""
Gipsy's voice: text in, WAV bytes out.

Two speech engines can make the raw voice:
  * Piper  - small, fast, already installed with the hub (CPU).
  * Kokoro - newer, smoother and more natural (optional, see
             install_better_voices.bat). Its British male voices are
             bm_george, bm_lewis, bm_daniel and bm_fable.

On top of the raw voice, every preset can add three simple effects:
  * pitch  - < 1.0 makes the voice deeper (0.88 = 12% lower).
  * warmth - boosts the low "chest" frequencies so it sounds bigger.
  * grit   - a touch of soft distortion, which adds a gravelly edge.
And "pace" sets how fast Gipsy talks (1.0 = normal, 1.1 = 10% faster).

None of these presets copy a real person. "commander" and "marshal" are
Gipsy's own voices, made by reshaping stock voices with the effects above.

How the pitch trick works (no extra processing needed):
  The engine is asked to talk faster than we want, then the WAV is labelled
  with a lower sample rate. The player plays it back slower, which lowers
  the pitch and brings the speed back to normal.
"""

from __future__ import annotations

import io
import logging
import re
import threading
import time
import urllib.request
import wave
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("gipsy")

# Every voice Gipsy can use. Pick one with "voice_preset" in config.json,
# or from Settings > Voice in the app.
PRESETS: dict[str, dict[str, Any]] = {
    "commander": {
        "label": "Commander (Gipsy's own, default)",
        "engine": "piper",
        "voice": "en_GB-alan-medium",
        "pitch": 0.92,
        "pace": 1.08,
        "warmth": 0.55,
        "grit": 0.25,
        "about": "Deep, warm and a little gravelly. Alan's voice reshaped into Gipsy's own. No extra install.",
    },
    "classic": {
        "label": "Classic (the old voice)",
        "engine": "piper",
        # Uses voice / voice_pitch / voice_speed from config.json, like before.
        "legacy": True,
        "about": "Exactly how Gipsy sounded before this update.",
    },
    "northern": {
        "label": "Northern",
        "engine": "piper",
        "voice": "en_GB-northern_english_male-medium",
        "pitch": 0.90,
        "pace": 1.05,
        "warmth": 0.45,
        "grit": 0.20,
        "about": "A Northern English male voice, pitched down. Piper, no extra install.",
    },
    "obadiah": {
        "label": "Obadiah",
        "engine": "piper",
        "voice": "en_GB-semaine-medium",
        "speaker": "obadiah",
        "pitch": 0.95,
        "pace": 1.0,
        "warmth": 0.35,
        "grit": 0.10,
        "about": "A slow, low, serious British male. Piper, no extra install.",
    },
    "marshal": {
        "label": "Marshal (Gipsy's own, best quality)",
        "engine": "kokoro",
        # A blend of two stock voices = a new voice that isn't anyone real.
        "blend": {"bm_george": 0.6, "bm_lewis": 0.4},
        "pitch": 0.88,
        "pace": 1.05,
        "warmth": 0.55,
        "grit": 0.30,
        "about": "Kokoro George + Lewis blended into one deep, commanding voice with gravel. Needs install_better_voices.bat.",
    },
    "george": {
        "label": "George",
        "engine": "kokoro",
        "blend": {"bm_george": 1.0},
        "pitch": 0.92,
        "pace": 1.05,
        "warmth": 0.40,
        "grit": 0.15,
        "about": "Kokoro's mature British male, pitched down a little.",
    },
    "lewis": {
        "label": "Lewis",
        "engine": "kokoro",
        "blend": {"bm_lewis": 1.0},
        "pitch": 0.93,
        "pace": 1.05,
        "warmth": 0.40,
        "grit": 0.15,
        "about": "Kokoro's lower, rounder British male.",
    },
    "daniel": {
        "label": "Daniel",
        "engine": "kokoro",
        "blend": {"bm_daniel": 1.0},
        "pitch": 0.92,
        "pace": 1.05,
        "warmth": 0.40,
        "grit": 0.10,
        "about": "Kokoro's calm, newsreader-style British male.",
    },
    "fable": {
        "label": "Fable",
        "engine": "kokoro",
        "blend": {"bm_fable": 1.0},
        "pitch": 0.92,
        "pace": 1.05,
        "warmth": 0.40,
        "grit": 0.15,
        "about": "Kokoro's storyteller British male.",
    },
}

DEFAULT_PRESET = "commander"

KOKORO_FILES = {
    "model": "kokoro-v1.0.onnx",
    "voices": "voices-v1.0.bin",
}
KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"


class VoiceUnavailable(RuntimeError):
    """The preset needs something that isn't installed yet."""


def kokoro_installed() -> bool:
    try:
        import kokoro_onnx  # noqa: F401  (just checking it is installed)
    except Exception:
        return False
    return True


# ------------------------------------------------------------- effects ----


def shape(pcm16: bytes, rate: int, warmth: float, grit: float) -> bytes:
    """Adds warmth (low boost) and grit (soft distortion) to 16-bit mono audio."""
    if warmth <= 0 and grit <= 0:
        return pcm16
    import numpy as np

    x = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
    if x.size == 0:
        return pcm16
    peak_in = float(np.max(np.abs(x))) or 1.0

    if warmth > 0:
        # Equaliser done with an FFT: boost the lows (chest), dip the
        # harsh 3-6 kHz area a little. Gains are in dB.
        spec = np.fft.rfft(x)
        f = np.fft.rfftfreq(x.size, 1.0 / rate)
        low_db = 7.0 * warmth / (1.0 + (f / 220.0) ** 2)
        harsh_db = -3.0 * warmth * np.exp(-(((f - 4500.0) / 1800.0) ** 2))
        spec *= 10.0 ** ((low_db + harsh_db) / 20.0)
        x = np.fft.irfft(spec, n=x.size).astype(np.float32)

    if grit > 0:
        # tanh "saturation" squashes the peaks a bit, which adds harmonics:
        # it's what makes a voice sound rough and gravelly instead of clean.
        drive = 1.0 + 5.0 * grit
        x = np.tanh(x / peak_in * drive) / np.tanh(drive) * peak_in

    # Back to the same loudness as before, never clipping.
    peak = float(np.max(np.abs(x))) or 1.0
    x = x * min(peak_in / peak, 0.97 / peak)
    return (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def to_wav(pcm16: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm16)
    return buf.getvalue()


# -------------------------------------------------------------- engine ----


class Voice:
    """Loads speech engines once and keeps them in memory.

    Loading a voice takes a second or two, so we never do it per request.
    The last few results are cached, so repeated lines (the kaiju alert,
    voice previews) come back instantly.
    """

    def __init__(self, cfg: dict[str, Any], voices_dir: Path):
        self.cfg = cfg
        self.dir = voices_dir
        self._piper: dict[str, Any] = {}
        self._kokoro: Any = None
        self._styles: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._cache: "OrderedDict[tuple[str, str], bytes]" = OrderedDict()

    # --- presets ---

    @property
    def preset_name(self) -> str:
        name = self.cfg.get("voice_preset") or DEFAULT_PRESET
        return name if name in PRESETS else DEFAULT_PRESET

    def preset(self, name: Optional[str] = None) -> dict[str, Any]:
        name = name or self.preset_name
        if name not in PRESETS:
            raise KeyError(f"No voice preset called {name!r}")
        p = dict(PRESETS[name])
        if p.get("legacy"):
            pitch = float(self.cfg.get("voice_pitch", 0.90))
            p.update(
                voice=self.cfg.get("voice", "en_GB-alan-medium"),
                pitch=pitch,
                pace=1.0 / float(self.cfg.get("voice_speed", 1.0) or 1.0),
                warmth=0.0,
                grit=0.0,
            )
        elif name == self.preset_name:
            # Fine-tune the chosen preset from config.json without editing code.
            for key in ("pitch", "warmth", "grit"):
                v = self.cfg.get(f"voice_{key}_override")
                if v is not None:
                    p[key] = float(v)
        # Talking speed (the slider in the app) applies to every voice, so
        # previews sound as fast as the real thing.
        v = self.cfg.get("voice_pace_override")
        if v is not None:
            p["pace"] = float(v)
        p["name"] = name
        return p

    def available(self, name: str) -> tuple[bool, str]:
        p = PRESETS[name]
        if p["engine"] == "kokoro" and not kokoro_installed():
            return False, "Run install_better_voices.bat to add Kokoro voices."
        return True, ""

    def list(self) -> list[dict[str, Any]]:
        out = []
        for name, p in PRESETS.items():
            ok, why = self.available(name)
            out.append(
                {
                    "id": name,
                    "label": p["label"],
                    "engine": p["engine"],
                    "about": p["about"],
                    "available": ok,
                    "why": why,
                    "current": name == self.preset_name,
                }
            )
        return out

    # --- loading ---

    def _download(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        log.info("Downloading %s (first time only) ...", dest.name)
        part = dest.with_suffix(dest.suffix + ".part")
        urllib.request.urlretrieve(url, part)
        part.replace(dest)

    def _piper_voice(self, name: str):
        if name in self._piper:
            return self._piper[name]
        from piper import PiperVoice

        onnx = self.dir / f"{name}.onnx"
        cfg = self.dir / f"{name}.onnx.json"
        if not (onnx.exists() and cfg.exists()):
            m = re.match(r"^(?P<lang>[a-z]{2})_(?P<region>[A-Z]{2})-(?P<voice>[a-z0-9_]+)-(?P<q>x_low|low|medium|high)$", name)
            if not m:
                raise RuntimeError(f"Voice name {name!r} doesn't look like en_GB-alan-medium")
            base = f"{PIPER_URL}{m['lang']}/{m['lang']}_{m['region']}/{m['voice']}/{m['q']}/{name}"
            for ext, dest in ((".onnx", onnx), (".onnx.json", cfg)):
                self._download(base + ext + "?download=true", dest)
        t = time.perf_counter()
        voice = PiperVoice.load(onnx, use_cuda=bool(self.cfg.get("voice_use_gpu", False)))
        log.info("Piper voice loaded: %s (%.1f s)", name, time.perf_counter() - t)
        self._piper[name] = voice
        return voice

    def _kokoro_engine(self):
        if self._kokoro is not None:
            return self._kokoro
        if not kokoro_installed():
            raise VoiceUnavailable("Kokoro isn't installed yet. Double-click install_better_voices.bat.")
        from kokoro_onnx import Kokoro

        folder = self.dir / "kokoro"
        paths = {}
        for key, filename in KOKORO_FILES.items():
            dest = folder / filename
            if not dest.exists():
                self._download(KOKORO_URL + filename, dest)
            paths[key] = dest
        t = time.perf_counter()
        self._kokoro = Kokoro(str(paths["model"]), str(paths["voices"]))
        log.info("Kokoro loaded (%.1f s)", time.perf_counter() - t)
        return self._kokoro

    def _kokoro_style(self, blend: dict[str, float]):
        key = ",".join(f"{k}:{v}" for k, v in sorted(blend.items()))
        if key not in self._styles:
            k = self._kokoro_engine()
            total = sum(blend.values()) or 1.0
            style = None
            for name, weight in blend.items():
                part = k.get_voice_style(name) * (weight / total)
                style = part if style is None else style + part
            self._styles[key] = style
        return self._styles[key]

    def load(self, name: Optional[str] = None) -> None:
        """Load the engine for a preset and say one word, so the first real
        reply doesn't have to wait for start-up work."""
        self.synthesize("Online.", name, use_cache=False)

    # --- speaking ---

    def _raw(self, text: str, p: dict[str, Any]) -> tuple[bytes, int]:
        pitch = max(0.6, min(1.3, float(p.get("pitch", 1.0))))
        pace = max(0.5, min(2.0, float(p.get("pace", 1.0))))
        if p["engine"] == "kokoro":
            import numpy as np

            k = self._kokoro_engine()
            samples, rate = k.create(
                text,
                voice=self._kokoro_style(p["blend"]),
                speed=max(0.5, min(2.0, pace / pitch)),
                lang=self.cfg.get("kokoro_lang", "en-gb"),
            )
            pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
            return pcm, int(rate)

        from piper import SynthesisConfig

        voice = self._piper_voice(p["voice"])
        base = getattr(voice.config, "length_scale", 1.0) or 1.0
        speaker_id = None
        if p.get("speaker") is not None:
            ids = getattr(voice.config, "speaker_id_map", None) or {}
            speaker_id = ids.get(p["speaker"], p["speaker"] if isinstance(p["speaker"], int) else None)
            if speaker_id is None:
                log.warning("Speaker %r not in %s; using the first one", p["speaker"], p["voice"])
        syn = SynthesisConfig(length_scale=base * pitch / pace, speaker_id=speaker_id)
        pcm = bytearray()
        rate = voice.config.sample_rate
        for chunk in voice.synthesize(text, syn_config=syn):
            rate = chunk.sample_rate
            pcm += chunk.audio_int16_bytes
        return bytes(pcm), int(rate)

    def synthesize(self, text: str, name: Optional[str] = None, use_cache: bool = True) -> bytes:
        p = self.preset(name)
        key = (p["name"] + repr(sorted(p.items())), text)
        if use_cache and key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        with self._lock:
            t = time.perf_counter()
            pcm, rate = self._raw(text, p)
            pcm = shape(pcm, rate, float(p.get("warmth", 0)), float(p.get("grit", 0)))
            pitch = max(0.6, min(1.3, float(p.get("pitch", 1.0))))
            wav = to_wav(pcm, rate * pitch)
            took = time.perf_counter() - t
        seconds = len(pcm) / 2 / (rate * pitch)
        log.info("Voice %s: %.2f s of speech in %.2f s (%d chars)", p["name"], seconds, took, len(text))
        if use_cache:
            self._cache[key] = wav
            while len(self._cache) > 48:
                self._cache.popitem(last=False)
        return wav
