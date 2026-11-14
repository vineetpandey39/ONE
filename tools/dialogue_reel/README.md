# Dialogue Reel (prototype)

Two-character explainer reels for @aibyvineet: VINEET asks, the ONE mascot
explains on a whiteboard, VINEET keeps saying "Nahi. Aur simple." until the
final desi analogy lands. A script-driven auto-director moves the camera with
the narration.

```
scripts/<ep>.json  ->  build_audio.py  ->  out/<ep>/audio.wav + timeline.json
                                       ->  render.js (three.js in headless Chromium + ffmpeg)
                                       ->  out/<ep>/reel.mp4  (720x1280, 30 fps)
```

## Run

```bash
npm install
pip install kokoro-onnx soundfile          # needs kokoro.int8.onnx + voices.bin in KOKORO_DIR

# one command (validates the script, builds audio, renders, writes caption.txt)
python3 make_reel.py scripts/ep02_prompt.json --kokoro-dir $KOKORO_DIR

# on the PC: ElevenLabs voices + Envato music/SFX
ELEVENLABS_API_KEY=... ELEVEN_VOICE_VINEET=... ELEVEN_VOICE_ONE=... \
  python3 make_reel.py scripts/ep02_prompt.json --tts elevenlabs \
  --music assets/music/track.mp3 --sfx-dir assets/sfx

# step by step / quick look
python3 build_audio.py scripts/ep01_ai_agent.json out/ep01 --kokoro-dir $KOKORO_DIR
node render.js out/ep01 --stills 0,300,900
```

New episodes: `prompts/dialogue_writer.md` is the writer prompt for ChatGPT /
Claude / the local model; its JSON output goes in `scripts/`.
Asset prompts for Leonardo / ChatGPT / Envato / ElevenLabs: `prompts/asset_prompts.md`.

## Script format

Each line has `who` (VINEET / ONE), `caption` (Roman Hinglish, shown on screen),
`tts` (Devanagari, what the voice reads), `shot` and optional `board` ops.

| shot | camera behaviour |
|---|---|
| `hook` | wide -> push-in to VINEET |
| `explain` / `story` | ONE close-up, then pans across the board following each word being written |
| `simpler` | hard cut punch-in on VINEET + shake + whoosh, then whip to the full board for the strike-through |
| `reveal` | board tracking, pull back for the circle |
| `realize` | over-the-shoulder, slow dolly into VINEET |
| `payoff` | quick push on ONE |
| `cta` | wide, then VINEET turns to camera |

Board ops: `write` (id, text, x, y, size, color, at), `strike` (target, at),
`circle` (target, at). `at` is 0..1 through the line.

## Placeholders to swap later

- Characters are code-built low-poly models (stay identical every episode); an optional painted window backdrop loads from `assets/backdrop.jpg`.
- Kokoro voices -> ElevenLabs (VINEET's cloned voice) by replacing `synth()` in build_audio.py.
- Render runs on CPU (SwiftShader, ~1 s/frame with bloom + depth of field); a GPU machine is much faster.
- Publishing as an Instagram Reel (media_type=REELS) still needs `publish_reel` in the floors `aibyvineet_publish` module.
