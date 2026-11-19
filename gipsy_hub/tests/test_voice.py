"""Offline tests for voice.py (no voice models needed) and the WAV reader
Whisper uses. Run from gipsy_hub/:   python -m unittest discover tests
"""

import io
import math
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import voice  # noqa: E402


def tone(rate=22050, seconds=0.5, hz=180.0, amp=0.5) -> bytes:
    n = int(rate * seconds)
    return b"".join(struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * hz * i / rate))) for i in range(n))


class FakeVoice(voice.Voice):
    """Pretends to be an engine: returns a tone as long as the text."""

    def __init__(self, cfg):
        super().__init__(cfg, Path(tempfile.gettempdir()))
        self.calls = []

    def _raw(self, text, p):
        self.calls.append((text, p["name"]))
        return tone(seconds=0.2), 22050


class VoiceTests(unittest.TestCase):
    def test_every_preset_is_complete(self):
        for name, p in voice.PRESETS.items():
            self.assertIn(p["engine"], ("piper", "kokoro"), name)
            self.assertTrue(p["label"] and p["about"], name)
            if not p.get("legacy"):
                for key in ("pitch", "pace", "warmth", "grit"):
                    self.assertIn(key, p, name)
                self.assertTrue(p.get("voice") or p.get("blend"), name)

    def test_shape_keeps_length_and_never_clips(self):
        raw = tone(amp=0.9)
        out = voice.shape(raw, 22050, warmth=1.0, grit=1.0)
        self.assertEqual(len(out), len(raw))
        peak = max(abs(v) for (v,) in struct.iter_unpack("<h", out))
        self.assertLessEqual(peak, 32767)
        self.assertGreater(peak, 20000)  # still about as loud

    def test_shape_off_is_untouched(self):
        raw = tone()
        self.assertIs(voice.shape(raw, 22050, 0, 0), raw)

    def test_pitch_lowers_sample_rate_label(self):
        v = FakeVoice({"voice_preset": "commander"})
        wav = v.synthesize("Hello John.")
        with wave.open(io.BytesIO(wav)) as w:
            self.assertEqual(w.getframerate(), int(22050 * voice.PRESETS["commander"]["pitch"]))

    def test_cache_and_overrides(self):
        v = FakeVoice({"voice_preset": "commander", "voice_pitch_override": 0.8})
        v.synthesize("Kaiju on the scanner.")
        v.synthesize("Kaiju on the scanner.")
        self.assertEqual(len(v.calls), 1)  # second time came from the cache
        self.assertEqual(v.preset()["pitch"], 0.8)
        # overrides only apply to the chosen preset, not to previews
        self.assertEqual(v.preset("northern")["pitch"], voice.PRESETS["northern"]["pitch"])

    def test_classic_uses_old_settings(self):
        v = FakeVoice({"voice_preset": "classic", "voice": "en_GB-alan-medium", "voice_pitch": 0.9, "voice_speed": 1.0})
        p = v.preset()
        self.assertEqual((p["voice"], p["pitch"], p["pace"], p["grit"]), ("en_GB-alan-medium", 0.9, 1.0, 0.0))

    def test_unknown_preset_falls_back(self):
        v = FakeVoice({"voice_preset": "nope"})
        self.assertEqual(v.preset_name, voice.DEFAULT_PRESET)


class WavReaderTests(unittest.TestCase):
    def test_resamples_to_16k_mono(self):
        import gipsy_hub

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        with wave.open(path, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(48000)
            mono = tone(rate=48000, seconds=1.0)
            w.writeframes(b"".join(mono[i : i + 2] * 2 for i in range(0, len(mono), 2)))
        x = gipsy_hub.read_wav_16k(path)
        self.assertEqual(x.dtype.name, "float32")
        self.assertAlmostEqual(x.size, 16000, delta=2)
        self.assertIsNone(gipsy_hub.read_wav_16k(__file__))  # not a WAV


class EndpointTests(unittest.TestCase):
    def setUp(self):
        import gipsy_hub
        from fastapi.testclient import TestClient

        self.hub = gipsy_hub
        self.client = TestClient(gipsy_hub.app)  # no "with": skips warm-up
        self._raw = gipsy_hub.VOICE._raw
        gipsy_hub.VOICE._raw = lambda text, p: (tone(seconds=0.1), 22050)
        self._saved = gipsy_hub.CFG.get("voice_preset")
        # Don't touch the real config.json while testing.
        self._save = gipsy_hub.save_config_value
        gipsy_hub.save_config_value = lambda k, v: gipsy_hub.CFG.__setitem__(k, v)

    def tearDown(self):
        self.hub.VOICE._raw = self._raw
        self.hub.save_config_value = self._save
        self.hub.CFG["voice_preset"] = self._saved

    def test_voices_tts_and_pick(self):
        r = self.client.get("/api/voices")
        self.assertEqual(r.status_code, 200)
        ids = [v["id"] for v in r.json()["voices"]]
        self.assertIn("commander", ids)
        r = self.client.post("/api/tts", json={"text": "Hello **John**.", "preset": "northern"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content[:4], b"RIFF")
        self.assertEqual(self.client.post("/api/tts", json={"text": "x", "preset": "nope"}).status_code, 400)
        self.assertEqual(self.client.post("/api/voice", json={"preset": "northern"}).status_code, 200)
        self.assertEqual(self.hub.VOICE.preset_name, "northern")
        self.assertIn("problems", self.client.get("/api/health").json())

    def test_hearing_error_reaches_the_app(self):
        real = self.hub.transcribe_file

        def broken(path):
            raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")

        self.hub.transcribe_file = broken
        try:
            r = self.client.post("/api/stt", files={"audio": ("clip.wav", b"RIFF" + b"\0" * 2000, "audio/wav")})
        finally:
            self.hub.transcribe_file = real
        self.assertEqual(r.status_code, 500)
        self.assertIn("metadata_errors", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
