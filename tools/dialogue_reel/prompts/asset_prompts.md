# Asset prompts for the PC tools (ChatGPT image / Leonardo / Envato)

The reel itself renders from code, so characters stay identical every day.
These prompts are for everything around it.

## 1. Window backdrop -> `assets/backdrop.jpg` (Leonardo or ChatGPT image)

> Wide night-time Indian city skyline seen from a 6th-floor window, dusk blue sky
> fading to soft lavender near the horizon, mid-rise apartment blocks with warm
> yellow lit windows, a few water tanks and a distant metro line, low-poly 3D
> render style, flat-shaded facets, soft glow, no people, no text, no logos,
> 16:9, 2048 px wide.

## 2. Profile picture / cover frame (ChatGPT image)

Keep it matching the in-reel models (same colours and shapes):

> Low-poly 3D render, flat-shaded facets, cozy night study room with a
> whiteboard. Left: "ONE", a small teal faceted orb robot (about the size of a
> football) with a dark glossy face visor, two tall rectangular cyan LED eyes, a
> tiny LED smile, a thin antenna topped by a glowing amber bulb, stubby teal
> feet, holding a wooden pointer stick, sitting on a stack of colourful books.
> Right: "VINEET", a young Indian guy, warm brown skin, short black hair with a
> spiky quiff, blue hoodie with white drawstrings, black headphones resting
> around his neck with orange caps, curious expression, sitting at a wooden desk
> with a mug and pen pot. Warm desk light, cool blue window light, city bokeh
> outside. No text, no logos.

Reel cover: same scene + big bold text area at top (add the text in Canva):
"<TOPIC> kya hai? 5 saal wala version".

## 3. Envato

- Music: search "lo-fi chill hip hop loop" / "playful pizzicato", 80–95 BPM, no
  vocals. Save to `assets/music/` and pass `--music`.
- SFX: "whoosh swish short" -> `assets/sfx/whoosh.wav`; "pop click ui" ->
  `assets/sfx/pop.wav`. Pass `--sfx-dir assets/sfx`.

## 4. ElevenLabs

- VINEET: your cloned voice (Hinglish, multilingual v2) -> `ELEVEN_VOICE_VINEET`.
- ONE: a light, friendly, slightly high young voice from the library ->
  `ELEVEN_VOICE_ONE` (add `"eleven_pitch": 1.08` on ONE in the script if it needs
  to sound more "mascot").
- Run: `ELEVENLABS_API_KEY=... python3 make_reel.py scripts/ep02_prompt.json --tts elevenlabs --music ... --sfx-dir assets/sfx`
