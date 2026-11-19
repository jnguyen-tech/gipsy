"""
Makes one sample clip per Gipsy voice so you can listen and pick a favourite.

Run:  make_voice_samples.bat   (or: python voice_samples.py)
The clips land in the voice_samples folder next to this file, and the
folder opens when it's done. Voices you haven't installed are skipped.

It also prints how fast each voice is on your PC. "Speed" is seconds of
speech made per second of work: 10x means a 5-second sentence takes 0.5 s.
Anything above about 3x is fast enough for live replies.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

import voice

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("GIPSY_DATA_DIR") or HERE)
OUT = DATA / "voice_samples"
LINE = (
    "Gipsy online. All systems are green, John. "
    "Your week has three deadlines and one appointment. "
    "Shall I walk you through them, or are we fighting something first?"
)


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    cfg_path = DATA / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    v = voice.Voice(cfg, DATA / "voices")
    OUT.mkdir(exist_ok=True)
    print(f"\n  Making voice samples in {OUT}\n")
    for i, (name, p) in enumerate(voice.PRESETS.items(), start=1):
        ok, why = v.available(name)
        if not ok:
            print(f"  -- {name:10} skipped: {why}")
            continue
        try:
            v.load(name)  # first load can download the voice
            t = time.perf_counter()
            wav = v.synthesize(LINE, name, use_cache=False)
            took = time.perf_counter() - t
        except Exception as e:
            print(f"  !! {name:10} failed: {type(e).__name__}: {e}")
            continue
        seconds = (len(wav) - 44) / 2 / voice_rate(wav)
        dest = OUT / f"{i:02d}-{name}.wav"
        dest.write_bytes(wav)
        print(f"  OK {name:10} {seconds:4.1f} s of speech in {took:4.2f} s  (speed {seconds / took:4.1f}x)  -> {dest.name}")
    print("\n  Listen, then pick one in the app: Settings > Voice.")
    print('  Or set "voice_preset" in config.json and restart the hub.\n')
    if sys.platform == "win32":
        os.startfile(OUT)  # opens the folder in Explorer


def voice_rate(wav: bytes) -> int:
    import io
    import wave

    with wave.open(io.BytesIO(wav)) as w:
        return w.getframerate()


if __name__ == "__main__":
    main()
