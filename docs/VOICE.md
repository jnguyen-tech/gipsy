# Gipsy's voice

Gipsy talks with its **own** voice: deep, warm, a little gravelly, British and
commanding. It's made on your PC by taking a stock voice and reshaping it.

> **Why not copy a famous actor's voice?** Cloning a real person's voice
> without their permission isn't fair to them (it's their identity and their
> job), and in many places it's against the law. That matters even more for a
> project on your LinkedIn and resume. Every voice here is either a stock voice
> its makers released for anyone to use, or a blend/reshape of those, so it
> sounds like nobody real.

## The voices

| Preset | Engine | What it sounds like | Install |
|---|---|---|---|
| `commander` (default) | Piper | Alan, pitched down 8%, warmer, with some gravel, talking 8% faster | nothing |
| `marshal` | Kokoro | Gipsy's best voice: George + Lewis blended into one new voice, deep and gravelly | `install_better_voices.bat` |
| `george`, `lewis`, `daniel`, `fable` | Kokoro | Kokoro's four British male voices, slightly deeper | `install_better_voices.bat` |
| `northern` | Piper | A Northern English male, pitched down | nothing |
| `obadiah` | Piper | A slow, low, serious British male | nothing |
| `classic` | Piper | Exactly the old voice | nothing |

New Piper voices download by themselves the first time you pick them (about
60 MB each). Kokoro downloads about 340 MB the first time.

## Step by step

### 1. Update the hub
Download the new code (the ZIP from GitHub, like before) and copy it over
`D:\gipsy-main\gipsy-main`. Your `config.json`, voices and tasks stay, because
they aren't in the ZIP.

Then double-click **`install_hub.bat`** again.
*Why:* it reinstalls the Python libraries from `requirements.txt`. This update
pins PyAV below version 19 (version 19 broke hearing), so this step fixes
"Hearing failed" for good.

### 2. (Optional) Add the Kokoro voices
Double-click **`install_better_voices.bat`**.
*Why:* Kokoro is a newer speech engine that sounds much more natural than
Piper. It's a separate step because it's a bigger download, and Gipsy works
fine without it. When it finishes it makes sample clips (next step) for you.

### 3. Listen to every voice
Close the Gipsy Hub window, then double-click **`make_voice_samples.bat`**.
*Why:* it says the same line in every voice and saves one WAV per voice in
`gipsy_hub\voice_samples\`, then opens the folder. It also prints how fast
each voice is on your PC ("speed 12x" means 12 seconds of speech per second
of work; anything above about 3x is fine for live replies).

### 4. Pick one
Start the hub (`start_hub.bat`), open the app, go to **Settings > Voice**.
Tap ▶ to hear a voice, tap the row to make it Gipsy's voice. It's saved on
the PC, so your iPhone and laptop switch too.

You can also set `"voice_preset": "marshal"` in `config.json` and restart.

### 5. Talking speed
Settings > Voice > **Talking speed** slider (80% to 150%). It's saved on the
PC as `voice_pace_override` in `config.json`, so every device uses it and
previews play at that speed too. Pitch stays the same, because the hub changes
pitch and speed separately.

### 6. Fine-tune (optional)
In `config.json`, these change the chosen voice without touching code
(`null` = use the preset's value):

| Setting | What it does | Try |
|---|---|---|
| `voice_pitch_override` | below 1.0 is deeper | 0.82 (huge) to 0.95 (natural) |
| `voice_pace_override` | above 1.0 talks faster | 1.0 to 1.2 |
| `voice_warmth_override` | boosts the low "chest" sound | 0 to 1 |
| `voice_grit_override` | gravel: soft distortion that adds roughness | 0 to 0.6 (above that it sounds like a radio) |

Restart the hub after editing.

## Why Gipsy felt slow, and what changed

A spoken reply has four steps: **hear** (Whisper) → **think** (qwen3 on the
graphics card) → **speak** (Piper/Kokoro on the CPU) → **play**. The hub now
prints how long each step takes in its window, for example:

```
First words from qwen3:8b after 0.6 s
Voice commander: 2.40 s of speech in 0.18 s (41 chars)
Heard (0.9 s): 'Hey Gipsy what's on this week'
```

so you can see which step is slow on your PC. What this update changes:

* **Gipsy starts talking sooner.** Before, the app waited for a whole
  sentence before asking for audio. Now the first piece can stop at a comma,
  so the first words come out while qwen3 is still writing the rest.
* **The brain is loaded when the hub starts.** The hub asks Ollama to load
  `qwen3:8b` into the graphics card right away (`preload_model`), so the first
  question doesn't wait 5-10 seconds for it. `keep_alive` (15 minutes by
  default) is how long it stays loaded after your last question; set it to
  `"1h"` if you talk to Gipsy on and off.
* **The voice is warmed up at start.** The voice engine says one word when
  the hub starts, so the first real reply doesn't pay the start-up cost.
* **Faster speaking pace.** The new presets talk 5-8% faster than the old voice.
* **Repeated lines are instant.** The last 48 lines are cached (the kaiju
  alert, previews).

**Why the voice runs on the CPU, not the RTX 3060:** while Gipsy is talking,
the graphics card is busy running qwen3, and its 12 GB of memory is mostly
full of the model. The CPU is free at that moment, and Piper/Kokoro are small
enough to run faster than real time on your Ryzen 5. Putting the voice on the
GPU would fight qwen3 for memory for very little gain. (If you ever want to
try, `voice_use_gpu: true` makes Piper use CUDA, but that needs
`onnxruntime-gpu` installed instead of `onnxruntime`.)

**Why not XTTS?** XTTS is mostly built for cloning voices from a recording,
its licence doesn't allow commercial use, and it's much slower. Kokoro gives
better quality for Gipsy at a fraction of the cost.

## If something goes wrong

* **Gipsy doesn't hear me:** Settings > **Test microphone**. It listens for
  one phrase and tells you which part failed: Windows blocking the mic, the
  mic being too quiet (it shows your loudest level against what Gipsy needs),
  or the PC not understanding the words.

* **"Hearing failed: ..."** The app now shows the hub's real reason. The hub
  window also prints the full error. Re-run `install_hub.bat` first.
* **A Kokoro voice is greyed out in Settings:** run `install_better_voices.bat`.
* **The voice stopped after picking a Kokoro preset:** the hub falls back to
  `commander` if Kokoro can't load, and the reason shows in the app's status
  line and in the hub window.
