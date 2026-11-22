# Run the Mars short on your PC (Blender)

Files you need, all in one folder:
- `blender/mars.py` builds the 3D scene and renders the simulation (no text)
- `render_short.py` adds the hook, live meter, reveal and sound
- `shorts.json` holds the text and meter values for all 7 shorts

Requirements: **Blender 4.2+** (tested on 5.3), **Python 3.9+** with `pip install pillow numpy`, and **ffmpeg** on PATH.

## Steps (Windows PowerShell; same idea on Mac/Linux)

```powershell
cd path\to\planexium

# 1) Quick preview first (~1-3 min): 540x960, every 10th frame
blender -b -P blender\mars.py -- --out .\mars_preview\ --preview

# 2) Full render: 1080x1920, 900 frames (uses the GPU automatically if it finds one)
blender -b -P blender\mars.py -- --out .\mars_frames\ --samples 96
#    Faster option (slightly less real):  --engine EEVEE
#    Split across sessions/PCs:           --frames 1 450   and later   --frames 451 900

# 3) Frames -> clip
ffmpeg -framerate 30 -i mars_frames\%04d.png -c:v libx264 -crf 16 -pix_fmt yuv420p mars_clip.mp4

# 4) Burn hook + meter + reveal + sound -> final short
python render_short.py mars --bg mars_clip.mp4 -o out\mars_final.mp4
```

Typical render time for step 2: RTX 3060-class GPU with Cycles takes about 3–8 s per frame, so **1–2 hours**. EEVEE takes **10–20 minutes**. CPU only is very slow, so use `--engine EEVEE` there.

## Prompt to paste into ChatGPT (if it is running the commands for you)

```
I have a folder "planexium" with blender/mars.py, render_short.py and shorts.json.
Blender is installed. Please, on my machine:
1. Check that blender, python (with pillow + numpy) and ffmpeg are on PATH; install pillow/numpy with pip if missing.
2. Run the preview:  blender -b -P blender/mars.py -- --out ./mars_preview/ --preview   and show me 2-3 frames.
3. If I approve, run the full render:  blender -b -P blender/mars.py -- --out ./mars_frames/ --samples 96
4. Make the clip:  ffmpeg -framerate 30 -i mars_frames/%04d.png -c:v libx264 -crf 16 -pix_fmt yuv420p mars_clip.mp4
5. Final short:  python render_short.py mars --bg mars_clip.mp4 -o out/mars_final.mp4
Do not edit the scripts. If a command fails, show me the full error.
```

## Tweaks
- Text, meter numbers and timing: edit `shorts.json` (`*green words*`, `|` = line break).
- Look of the planet: colours are the `color_ramp` values in `mars.py`. The animation timeline is in the comment at the top of the file.
- If no GPU is detected, the log won't print "Cycles on GPU". Use `--engine EEVEE`, or lower `--samples` to 48.
