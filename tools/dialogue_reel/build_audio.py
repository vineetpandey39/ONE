"""Script JSON -> voice lines, SFX, music bed, and a frame-accurate timeline.

Usage: python3 build_audio.py scripts/ep01_ai_agent.json out_dir [kokoro_dir]

Prototype voices come from Kokoro (free, local). Swapping in ElevenLabs later
only changes ``synth``; everything downstream reads timeline.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 24000
FPS = 30
GAP = 0.22          # breath between lines
SNAP_GAP = 0.08     # "Nahi. Aur simple." comes in hot
LEAD_IN = 0.35
TAIL = 1.4


def synth(kokoro, text: str, voice: str, speed: float) -> np.ndarray:
    samples, sr = kokoro.create(text, voice=voice, speed=speed, lang="hi")
    assert sr == SR, sr
    return trim(np.asarray(samples, dtype=np.float32))


def trim(x: np.ndarray, thr: float = 0.01) -> np.ndarray:
    idx = np.where(np.abs(x) > thr)[0]
    if len(idx) == 0:
        return x
    a, b = max(0, idx[0] - int(0.03 * SR)), min(len(x), idx[-1] + int(0.06 * SR))
    return x[a:b]


def pitch(x: np.ndarray, factor: float) -> np.ndarray:
    """Raise pitch without changing duration (ffmpeg asetrate + atempo)."""
    if abs(factor - 1.0) < 1e-3:
        return x
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d, "a.wav"), Path(d, "b.wav")
        sf.write(src, x, SR)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af",
                        f"asetrate={int(SR * factor)},aresample={SR},atempo={1 / factor:.5f}",
                        str(dst)], check=True)
        y, _ = sf.read(dst, dtype="float32")
    return y


def whoosh(dur: float = 0.38) -> np.ndarray:
    n = int(dur * SR)
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n).astype(np.float32)
    # Sweep a one-pole low-pass cutoff upward for the "swish".
    out = np.zeros(n, dtype=np.float32)
    y = 0.0
    for i in range(n):
        a = 0.02 + 0.5 * (i / n) ** 2
        y += a * (noise[i] - y)
        out[i] = y
    env = np.sin(np.linspace(0, np.pi, n)) ** 2
    return 0.5 * out * env / (np.abs(out).max() + 1e-9)


def pop(dur: float = 0.09) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    f = 900 - 500 * t / dur
    return (0.25 * np.sin(2 * np.pi * f * t) * np.exp(-t * 40)).astype(np.float32)


def music_bed(total: float) -> np.ndarray:
    """Soft lo-fi pad: Am - F - C - G, 2s per chord, plus gentle plucks."""
    n = int(total * SR)
    t = np.arange(n) / SR
    chords = [[220.0, 261.63, 329.63], [174.61, 220.0, 261.63],
              [130.81, 196.0, 261.63], [196.0, 246.94, 293.66]]
    out = np.zeros(n, dtype=np.float32)
    seg = 2.0
    for k in range(int(total / seg) + 1):
        a, b = int(k * seg * SR), min(n, int((k + 1) * seg * SR))
        if a >= n:
            break
        tt = t[a:b] - k * seg
        env = np.minimum(1, tt / 0.4) * np.minimum(1, (seg - tt) / 0.4)
        for f in chords[k % 4]:
            out[a:b] += 0.05 * env * (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt))
        for j, f in enumerate(chords[k % 4]):  # pluck arpeggio
            s = a + int((0.25 + j * 0.5) * SR)
            m = min(n - s, int(0.5 * SR))
            if m > 0:
                pt = np.arange(m) / SR
                out[s:s + m] += 0.06 * np.sin(2 * np.pi * 2 * f * pt) * np.exp(-pt * 9)
    return out


def main() -> None:
    script_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    kdir = Path(sys.argv[3] if len(sys.argv) > 3 else os.environ.get("KOKORO_DIR", "."))
    out_dir.mkdir(parents=True, exist_ok=True)
    script = json.loads(script_path.read_text(encoding="utf-8"))

    from kokoro_onnx import Kokoro
    kokoro = Kokoro(str(kdir / "kokoro.int8.onnx"), str(kdir / "voices.bin"))

    clips, t = [], LEAD_IN
    for i, line in enumerate(script["lines"]):
        ch = script["characters"][line["who"]]
        audio = pitch(synth(kokoro, line["tts"], ch["voice"], ch.get("speed", 1.0)), ch.get("pitch", 1.0))
        if i:
            t += SNAP_GAP if line.get("shot") == "simpler" else GAP
        clips.append((t, audio))
        line["start"], line["end"] = round(t, 3), round(t + len(audio) / SR, 3)
        t = line["end"]
        print(f"[{line['start']:6.2f}-{line['end']:6.2f}] {line['who']}: {line['caption']}", flush=True)

    total = t + TAIL
    n = int(total * SR)
    voice = np.zeros(n, dtype=np.float32)
    for start, audio in clips:
        s = int(start * SR)
        voice[s:s + len(audio)] += audio[: n - s]

    sfx = np.zeros(n, dtype=np.float32)
    w, p = whoosh(), pop()
    for line in script["lines"]:
        if line.get("shot") in ("simpler", "payoff", "hook"):
            s = max(0, int((line["start"] - 0.25) * SR))
            sfx[s:s + len(w)] += w[: n - s]
        for op in line.get("board", []):
            if op["op"] in ("circle",):
                s = int((line["start"] + op["at"] * (line["end"] - line["start"])) * SR)
                sfx[s:s + len(p)] += p[: n - s]

    bed = music_bed(total)
    # Duck the music under speech.
    speech_env = np.convolve(np.abs(voice), np.ones(int(0.25 * SR)) / int(0.25 * SR), mode="same")
    duck = 1.0 - 0.55 * np.clip(speech_env / (speech_env.max() + 1e-9) * 6, 0, 1)
    mix = 0.95 * voice + 0.6 * sfx + bed * duck
    fade = int(0.8 * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)
    mix /= max(1.0, np.abs(mix).max() / 0.95)
    sf.write(out_dir / "audio.wav", mix, SR)

    # Per-frame mouth amplitude per speaker, normalised 0..1.
    frames = int(np.ceil(total * FPS))
    hop = SR // FPS
    amp = {who: [0.0] * frames for who in script["characters"]}
    peak = max(float(np.abs(a).max()) for _, a in clips) or 1.0
    for (start, audio), line in zip(clips, script["lines"]):
        f0 = int(start * FPS)
        for k in range(int(len(audio) / hop)):
            rms = float(np.sqrt(np.mean(audio[k * hop:(k + 1) * hop] ** 2)))
            if f0 + k < frames:
                amp[line["who"]][f0 + k] = round(min(1.0, rms / peak * 4.0), 3)

    timeline = {"fps": FPS, "duration": round(total, 3), "frames": frames,
                "board_title": script.get("board_title", ""), "lines": script["lines"], "amp": amp}
    (out_dir / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False), encoding="utf-8")
    print(f"total {total:.2f}s, {frames} frames", flush=True)


if __name__ == "__main__":
    main()
