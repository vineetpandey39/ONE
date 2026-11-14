"""Script JSON -> voice lines, SFX, music bed, and a frame-accurate timeline.

Usage:
  python3 build_audio.py scripts/ep01_ai_agent.json out/ep01 --kokoro-dir DIR
  python3 build_audio.py scripts/ep01_ai_agent.json out/ep01 --tts elevenlabs \
      --music assets/music/lofi.mp3 --sfx-dir assets/sfx

Voices: ``kokoro`` (free, local, default) or ``elevenlabs`` (ELEVENLABS_API_KEY
plus a voice id per character: ``eleven_voice_id`` in the script, or the
ELEVEN_VOICE_<WHO> env var, e.g. ELEVEN_VOICE_VINEET for the cloned voice).
Music/SFX: any file ffmpeg reads (Envato downloads as-is). ``--sfx-dir`` may hold
whoosh.*, pop.* -- each one found replaces the synthetic version.
Everything downstream reads timeline.json, so the renderer never changes.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
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
TAIL = 2.2


def synth_kokoro(kokoro, text: str, voice: str, speed: float) -> np.ndarray:
    samples, sr = kokoro.create(text, voice=voice, speed=speed, lang="hi")
    assert sr == SR, sr
    return trim(np.asarray(samples, dtype=np.float32))


def synth_elevenlabs(text: str, voice_id: str, speed: float) -> np.ndarray:
    """ElevenLabs multilingual v2 as raw 24 kHz PCM (no decode step needed)."""
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key or not voice_id:
        raise SystemExit("elevenlabs needs ELEVENLABS_API_KEY and a voice id per character")
    body = json.dumps({
        "text": text, "model_id": os.environ.get("ELEVEN_MODEL", "eleven_turbo_v2_5"),
        **({"language_code": lang} if (lang := os.environ.get("ELEVEN_LANG", "hi")) else {}),
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.75, "style": 0.2,
                           "use_speaker_boost": True, "speed": speed},
    }).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=pcm_{SR}",
        data=body, headers={"xi-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        pcm = np.frombuffer(r.read(), dtype="<i2").astype(np.float32) / 32768.0
    return trim(pcm)


def load_audio(path: Path) -> np.ndarray:
    """Any file ffmpeg reads (mp3/wav/m4a from Envato) -> mono float32 at SR."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def find(dir_: Path | None, stem: str) -> Path | None:
    if not dir_ or not dir_.is_dir():
        return None
    return next((p for p in sorted(dir_.iterdir()) if p.stem.lower() == stem), None)


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
    ap = argparse.ArgumentParser()
    ap.add_argument("script"); ap.add_argument("out_dir")
    ap.add_argument("kokoro_dir_pos", nargs="?", help=argparse.SUPPRESS)
    ap.add_argument("--tts", default=os.environ.get("REEL_TTS", "kokoro"), choices=["kokoro", "elevenlabs"])
    ap.add_argument("--kokoro-dir", default=os.environ.get("KOKORO_DIR", "."))
    ap.add_argument("--music", help="music bed file (e.g. an Envato track); default: built-in lo-fi pad")
    ap.add_argument("--music-gain", type=float, default=0.18)
    ap.add_argument("--sfx-dir", help="folder with whoosh.* / pop.* to replace the synthetic SFX")
    a = ap.parse_args()
    script_path, out_dir = Path(a.script), Path(a.out_dir)
    kdir = Path(a.kokoro_dir_pos or a.kokoro_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    script = json.loads(script_path.read_text(encoding="utf-8"))

    if a.tts == "kokoro":
        from kokoro_onnx import Kokoro
        kokoro = Kokoro(str(kdir / "kokoro.int8.onnx"), str(kdir / "voices.bin"))

    def synth(who: str, ch: dict, text: str) -> np.ndarray:
        if a.tts == "elevenlabs":
            vid = ch.get("eleven_voice_id") or os.environ.get(f"ELEVEN_VOICE_{who.upper()}", "")
            return pitch(synth_elevenlabs(text, vid, ch.get("eleven_speed", 1.0)), ch.get("eleven_pitch", 1.0))
        return pitch(synth_kokoro(kokoro, text, ch["voice"], ch.get("speed", 1.0)), ch.get("pitch", 1.0))

    clips, t = [], LEAD_IN
    for i, line in enumerate(script["lines"]):
        ch = script["characters"][line["who"]]
        audio = synth(line["who"], ch, line["tts"])
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
    sfx_dir = Path(a.sfx_dir) if a.sfx_dir else None
    w = load_audio(f) * 0.8 if (f := find(sfx_dir, "whoosh")) else whoosh()
    p = load_audio(f) * 0.6 if (f := find(sfx_dir, "pop")) else pop()
    for line in script["lines"]:
        if line.get("shot") in ("simpler", "payoff", "hook"):
            s = max(0, int((line["start"] - 0.25) * SR))
            sfx[s:s + len(w)] += w[: n - s]
        for op in line.get("board", []):
            if op["op"] in ("circle",):
                s = int((line["start"] + op["at"] * (line["end"] - line["start"])) * SR)
                sfx[s:s + len(p)] += p[: n - s]

    if a.music:
        track = load_audio(Path(a.music))
        reps = int(np.ceil(n / len(track)))
        bed = np.tile(track, reps)[:n]
        bed = bed / (np.abs(bed).max() + 1e-9) * a.music_gain
    else:
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
    # Per-frame mouth data per speaker: "open" (loudness, fast attack / soft
    # release, closes in pauses) and "shape" (spectral centroid: 0 = round "oo",
    # 1 = wide "ee"), so the mouth changes form, not only size.
    amp = {who: [0.0] * frames for who in script["characters"]}
    shape = {who: [0.5] * frames for who in script["characters"]}
    peak = max(float(np.abs(a).max()) for _, a in clips) or 1.0
    freqs = np.fft.rfftfreq(hop, 1 / SR)
    for (start, audio), line in zip(clips, script["lines"]):
        f0 = int(start * FPS)
        prev = 0.0
        for k in range(int(len(audio) / hop)):
            seg = audio[k * hop:(k + 1) * hop]
            rms = float(np.sqrt(np.mean(seg ** 2)))
            level = min(1.0, rms / peak * 4.0)
            level = 0.0 if level < 0.08 else level
            prev = level if level > prev else prev * 0.55 + level * 0.45
            mag = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
            cen = float((freqs * mag).sum() / (mag.sum() + 1e-9))
            if f0 + k < frames:
                amp[line["who"]][f0 + k] = round(prev, 3)
                shape[line["who"]][f0 + k] = round(float(np.clip((cen - 600) / 2400, 0, 1)), 3)

    timeline = {"fps": FPS, "duration": round(total, 3), "frames": frames,
                "board_title": script.get("board_title", ""), "lines": script["lines"], "amp": amp, "shape": shape}
    (out_dir / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False), encoding="utf-8")
    print(f"total {total:.2f}s, {frames} frames", flush=True)


if __name__ == "__main__":
    main()
