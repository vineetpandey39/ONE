# PLANEXIUM: "7 Days, 7 Planets" Shorts Production Kit

Global audience · all on-screen text in English · 9:16 · 30 s each · one unbroken shot per short.

## How each short is built

| Layer | Made by | Why |
|---|---|---|
| Hyper-real simulation (no text) | **Seedance 2.5** (best quality, single 30 s continuous shot, 1080p/4K) | It has the strongest photoreal physics and the longest unbroken shots on Higgsfield. |
| Hook, live meter, sublabels, reveal, "tomorrow" teaser | `render_short.py` + `shorts.json` | AI models can't draw a counter that changes accurately. Burning it in post keeps every number exact. |
| Rising drone and reveal impact | `render_short.py` | It's synced to the reveal second. |

```bash
# 1) Generate the clip from the prompt below (Seedance 2.5, 9:16, 30 s, 1080p, audio off)
# 2) Burn the overlay:
python3 render_short.py mars --bg mars_seedance.mp4 -o out/mars_final.mp4
# Try it with no clip (procedural placeholder planet):
python3 render_short.py mars --demo
```

**Cost (checked on Higgsfield):** Seedance 2.5 at 1080p, 30 s = **480 credits** per short, so about 3,360 for all 7. A cheaper option is Kling 3.0 Pro at 15 s = **22.5 credits**: generate 2 clips, chain them with a start/end frame, and the total is about 45 per short.

**Prompt rules used everywhere:** one continuous camera move, no cuts, NO text, NO labels, NO numbers, NO UI, NO watermark, NO captions. The meter is drawn in post, so any text the model draws will clash with it.

---

## Hook-writing rules (curiosity gap at max)

1. **State the result and hide the cause.** For example, "Something killed it." The viewer has to stay to learn *what*.
2. **Contradict common sense.** A day longer than a year. Rain made of diamonds.
3. **Green = the impossible part.** Only the words that break the brain go green.
4. **The meter promises an ending.** A number that keeps moving makes viewers wait for where it stops.
5. **The reveal pays off only the hook.** Then the "TOMORROW:" teaser opens the next gap and drives follows.

---

## DAY 1 · MERCURY: "ONE DAY HERE LASTS **LONGER THAN A YEAR**"

- **Meter:** Surface temp **+430 °C → −180 °C**. Second meter: Earth days since sunrise **44 → 132**.
- **Reveal (25 s):** 1 DAY = **176** EARTH DAYS. 1 YEAR = **88**.

**Seedance prompt**
```
Ultra-photoreal, IMAX-grade scientific visualization. Single continuous 30-second shot, no cuts, vertical 9:16.
Low camera on the cratered grey surface of Mercury, black airless sky, a huge blinding white Sun high above.
0-5s: harsh noon light, rocks glowing hot, heat shimmer. 5-24s: extreme time-lapse, the Sun slowly sinks to the
horizon, long razor-sharp shadows stretch across craters, light turns from white to deep orange then vanishes,
the ground cools from glowing amber to deep blue-black, thin frost crystals form on rocks under a sky full of
stars. 24-30s: total darkness, frost glittering in starlight, slow push-in. Ray-traced lighting, real lunar-like
regolith textures, physically accurate shadows, cinematic lens, 8K detail.
No text, no labels, no numbers, no UI, no watermark.
```

## DAY 2 · VENUS: "THIS PLANET HAD **OCEANS**... THEN IT **COOKED ITSELF**"

- **Meter:** Surface temp **15 °C → 465 °C**. Second meter: Air pressure **1× → 92×** Earth.
- **Reveal (25 s):** STANDING HERE = BEING **900 m UNDERWATER**.
- ⚠️ Venus once having oceans is a hypothesis. The tease line ("Scientists think...") keeps it honest.

**Seedance prompt**
```
Ultra-photoreal planetary simulation, single continuous 30-second shot, no cuts, vertical 9:16.
Slow orbital descent toward an Earth-like Venus: deep blue oceans, white clouds, sunlit coastlines.
4-12s: the Sun brightens, oceans begin to boil, thick white steam rises and covers the planet.
12-20s: clouds thicken and turn sulfur-yellow, the whole sky becomes a crushing orange haze, lightning inside.
20-30s: camera breaks through to the surface: cracked black basalt glowing red, lava channels, distorted air,
oppressive orange light, volcano on the horizon. Volumetric clouds, physically based atmosphere scattering,
cinematic, hyper-detailed. No text, no labels, no numbers, no UI, no watermark.
```

## DAY 3 · MARS: "MARS DIDN'T DIE. **SOMETHING KILLED IT.**"

- **Meter:** Air pressure (est.) **1,000 → 6 mbar**. Second meter: Magnetic shield **100% → 0%**.
- **Reveal (25 s):** THE KILLER? **THE SUN.**

**Seedance prompt**
```
Ultra-photoreal, NASA-grade planetary simulation, single continuous 30-second shot, no cuts, vertical 9:16.
Ancient blue Mars from orbit: oceans in the northern hemisphere, rivers, thin blue atmospheric rim, white clouds.
3-8s: a faint glowing magnetic shield around the planet flickers and collapses.
8-22s: visible streams of solar wind from the right edge of frame strip the atmosphere away in glowing wisps
trailing into space; clouds thin out, oceans shrink and evaporate, coastlines turn to dry rust-red riverbeds.
22-30s: today's dusty red Mars, thin dust storm, no blue rim, slow push-in. Real Mars topography (Valles Marineris,
Olympus Mons), physically based lighting, cinematic, 8K. No text, no labels, no numbers, no UI, no watermark.
```

## DAY 4 · JUPITER: "KEEP FEEDING JUPITER AND IT **TURNS INTO A STAR**"

- **Meter:** Mass **×1 → ×80**. Second meter: Size **1.00× → 1.10× → 0.95×**. It gets heavier but stops growing, which is real physics.
- **Reveal (24 s):** AT ~80× ITS MASS, **FUSION IGNITES**. WE'D HAVE **TWO SUNS**.

**Seedance prompt**
```
Ultra-photoreal space simulation, single continuous 30-second shot, no cuts, vertical 9:16.
Jupiter fills the frame, Great Red Spot, swirling bands. 4-18s: streams of gas and small bodies spiral into
Jupiter, it grows denser and more compressed, bands blur and heat up, the night side starts to glow deep red
from inside. 18-23s: the core ignites, the planet turns into a small blazing red-orange star with a corona.
23-30s: camera pulls back past Earth: Earth in foreground with two light sources in its sky, the Sun and the
new red star. Volumetric light, realistic gas dynamics, cinematic. No text, no labels, no numbers, no UI, no watermark.
```

## DAY 5 · SATURN: "SATURN'S RINGS MAY BE **YOUNGER THAN THE DINOSAURS**"

- **Meter:** Distance to the death line (Roche limit) **60,000 → 0 km**.
- **Reveal (24 s):** 280,000 km WIDE. IN PLACES ONLY **~10 m THICK**.
- ⚠️ The rings' age is still debated. The hook says "may be".

**Seedance prompt**
```
Ultra-photoreal space simulation, single continuous 30-second shot, no cuts, vertical 9:16.
Ringless Saturn, golden bands. An icy moon drifts closer and closer in orbit (0-17s), stretching into an egg shape
as tidal forces build, cracks spread across its ice. 17-22s: the moon shatters into billions of ice fragments that
smear along its orbit. 22-30s: the debris spreads into thin, glittering rings around Saturn; camera skims edge-on
along the razor-thin ring plane, individual ice chunks sparkling in sunlight. Physically accurate, cinematic,
8K. No text, no labels, no numbers, no UI, no watermark.
```

## DAY 6 · URANUS: "ON THIS PLANET, NIGHT LASTS **42 YEARS**"

- **Meter:** Axial tilt **0° → 98°**.
- **Reveal (24 s):** **42 YEARS** OF DAYLIGHT. THEN **42 YEARS** OF DARKNESS.

**Seedance prompt**
```
Ultra-photoreal space simulation, single continuous 30-second shot, no cuts, vertical 9:16.
An upright pale cyan young Uranus spinning normally. 5-9s: an Earth-sized rocky protoplanet approaches from the left
and slams into it, enormous shockwave, debris cloud. 9-20s: the planet slowly tips over until it lies on its side,
faint rings now vertical. 20-30s: time-lapse orbit around the Sun: one pole faces the Sun in constant daylight while
the other hemisphere sits in deep darkness. Cinematic, realistic, 8K.
No text, no labels, no numbers, no UI, no watermark.
```

## DAY 7 · NEPTUNE: "IT DOESN'T RAIN WATER HERE. IT RAINS **DIAMONDS**."

- **Meter:** Depth **0 → 7,000 km**. Second meter: Wind **2,100 km/h → 0**.
- **Reveal (25 s):** THE BIGGEST DIAMONDS IN THE SOLAR SYSTEM? **NO ONE CAN EVER TOUCH THEM**.
- ⚠️ Diamond rain is supported by lab experiments but is still a theory.

**Seedance prompt**
```
Ultra-photoreal, single continuous 30-second first-person dive, no cuts, vertical 9:16.
Falling into deep-blue Neptune: 0-8s through violent white methane cloud streaks moving at extreme speed, dark storm
vortex. 8-16s: deeper, darker, crushing blue haze, light fades. 16-30s: in dark dense fluid, tiny glittering
diamonds form and fall like rain all around the camera, catching faint blue light, growing larger as they sink.
Physically based volumetrics, cinematic, 8K. No text, no labels, no numbers, no UI, no watermark.
```

---

## Titles, captions, pinned comments

| Day | Title (≤60 chars) | Caption | Pinned comment |
|---|---|---|---|
| 1 | A Day Here Is Longer Than A Year 🤯 | Mercury breaks time itself. #space #mercury #science #shorts | Would you survive a 176-day day? ☀️→🌑 |
| 2 | This Planet Had Oceans... Then It Cooked Itself | What happened to Venus could be a warning. #venus #space #shorts | Could this happen to Earth? 👇 |
| 3 | Mars Didn't Die. Something Killed It. | Watch the air disappear. #mars #nasa #space #shorts | Guess the killer before the end 👀 |
| 4 | What If Jupiter Became A Star? | Keep adding mass... #jupiter #astronomy #shorts | Would two suns be cool or terrifying? |
| 5 | Saturn's Rings Might Be Younger Than Dinosaurs | A moon died to make them. #saturn #space #shorts | Did you know the rings are disappearing? |
| 6 | Night Here Lasts 42 Years | Uranus was knocked on its side. #uranus #space #shorts | What would you do in 42 years of night? 🌑 |
| 7 | It Rains Diamonds Here 💎 | Neptune's hidden treasure. #neptune #space #shorts | Season 2: which planet/topic next? |

**Posting:** same time daily, aimed at the US evening (about 7–9 PM ET). That's about 5:30–7:30 AM IST.
**Loop trick:** the last frame should visually match the first frame, so replays look seamless.
**Series lock-in:** every short ends with a "TOMORROW: ..." teaser that's already in `shorts.json`.
