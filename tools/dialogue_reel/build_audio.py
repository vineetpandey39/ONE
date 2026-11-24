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


def phone_filter(x: np.ndarray) -> np.ndarray:
    """Make an off-screen voice sound like it comes through a phone call."""
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d, "a.wav"), Path(d, "b.wav")
        sf.write(src, x, SR)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af",
                        "highpass=f=320,lowpass=f=3300,acompressor=threshold=0.1:ratio=4,volume=1.4",
                        str(dst)], check=True)
        y, _ = sf.read(dst, dtype="float32")
    return y


# ---------- voice QC: listen back with speech-to-text ----------
DISFLUENT = {"uh", "um", "umm", "hmm", "अं", "उम्म", "हम्म"}


def transcribe(x: np.ndarray) -> str:
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d, "line.wav")
        sf.write(wav, x, SR)
        out = subprocess.run(["curl", "-sS", "-m", "120", "-H", f"xi-api-key: {os.environ.get('ELEVENLABS_API_KEY', '')}",
                              "-F", "model_id=scribe_v1", "-F", "language_code=hin", "-F", f"file=@{wav}",
                              "https://api.elevenlabs.io/v1/speech-to-text"], capture_output=True, text=True).stdout
    try:
        return json.loads(out).get("text", "")
    except json.JSONDecodeError:
        return ""


_DEVA = dict(zip("कखगघचछजझटठडढणतथदधनपफबभमयरलवशषसहंँ",
                 "kkggccjjttddnttddnpfbbmyrlvssshnn"))
assert len(_DEVA) == 33
_NUMBER_WORDS = {"एक", "दो", "तीन", "चार", "पाँच", "पांच", "छह", "सात", "आठ", "नौ", "दस", "ग्यारह", "बारह",
                 "बीस", "तीस", "पचास", "सौ", "हज़ार", "हजार", "लाख", "पंद्रह", "उन्नीस"}


def skeleton(word: str) -> str:
    """Script-independent sound skeleton: 'फ़ोन' and 'phone' both become 'fn'."""
    import re
    w = word.lower()
    if re.search(r"[\u0900-\u097F]", w):
        out = "".join(_DEVA.get(ch, "") for ch in w.replace("\u093c", ""))
    else:
        w = re.sub(r"c(?=[eiy])", "s", w)            # police -> polise, cyber -> syber
        w = w.replace("ck", "k").replace("mb", "nb").replace("mp", "np")
        for a2, b2 in (("ph", "f"), ("sh", "s"), ("ch", "C"), ("th", "t"), ("kh", "k"), ("gh", "g"),
                       ("bh", "b"), ("dh", "d"), ("w", "v"), ("z", "j"), ("q", "k"), ("x", "ks"), ("c", "k"), ("C", "c")):
            w = w.replace(a2, b2)
        out = re.sub(r"[aeiouh0-9]", "", w)
    out = out.replace("h", "")
    return re.sub(r"(.)\1+", r"\1", out)


def voice_score(tts: str, heard: str, keyword: str | None) -> tuple[float, list[str]]:
    """Share of the script's words that were heard (compared by sound, not spelling)."""
    import difflib
    import re
    words = lambda t: re.findall(r"[\w\u0900-\u097F]+", t.lower())
    said = [w for w in words(tts) if w not in _NUMBER_WORDS and len(skeleton(w)) >= 2]
    got_sk = [skeleton(w) for w in words(heard)]
    got_sk += [a2 + b2 for a2, b2 in zip(got_sk, got_sk[1:])]          # 'notebook lm' vs 'नोटबुकएलएम'
    hit = sum(1 for w in said if difflib.get_close_matches(skeleton(w), got_sk, n=1, cutoff=0.6)) / max(1, len(said))
    issues = []
    if hit < 0.6:
        issues.append(f"only {hit:.0%} of words heard")
    if any(w in DISFLUENT for w in words(heard)):
        issues.append("hesitation (uh/um) in the voice")
    if keyword and not re.search(rf"(?<![\w]){re.escape(keyword)}(?![\w])", heard, re.IGNORECASE):
        issues.append(f"CTA keyword {keyword!r} not heard")
    return hit - 0.3 * any("hesitation" in i for i in issues) - (1.0 if any("keyword" in i for i in issues) else 0), issues


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
    ap.add_argument("--no-voice-qc", action="store_true", help="skip the speech-to-text check of each line")
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
            x = pitch(synth_elevenlabs(text, vid, ch.get("eleven_speed", 1.0)), ch.get("eleven_pitch", 1.0))
        else:
            x = pitch(synth_kokoro(kokoro, text, ch["voice"], ch.get("speed", 1.0)), ch.get("pitch", 1.0))
        return phone_filter(x) if ch.get("phone") else x

    qc_on = a.tts == "elevenlabs" and not a.no_voice_qc
    qc_report = []

    cache_dir = out_dir / "tts_cache"
    cache_dir.mkdir(exist_ok=True)

    def synth_cached(who: str, ch: dict, text: str, take: int) -> np.ndarray:
        import hashlib
        key = hashlib.sha1(json.dumps([a.tts, who, ch, text, take], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        f = cache_dir / f"{key}.wav"
        if f.exists():
            return sf.read(f, dtype="float32")[0]
        x = synth(who, ch, text)
        sf.write(f, x, SR)
        return x

    def synth_checked(line: dict, ch: dict) -> np.ndarray:
        """Synthesise, listen back, and retry (TTS is not deterministic) until it is clean."""
        keyword = (line.get("cta_card") or {}).get("keyword")
        best = None
        for attempt in range(3 if qc_on else 1):
            x = synth_cached(line["who"], ch, line["tts"], attempt)
            if not qc_on:
                return x
            heard = transcribe(x)
            score, issues = voice_score(line["tts"], heard, keyword)
            if best is None or score > best[0]:
                best = (score, x, issues, heard)
            if not issues:
                break
            print(f"   voice QC retry ({', '.join(issues)}): heard {heard!r}", flush=True)
        qc_report.append({"line": line["caption"], "heard": best[3], "issues": best[2]})
        if keyword and any("keyword" in i for i in best[2]):
            raise SystemExit(f"voice QC: CTA keyword {keyword!r} still not heard in: {best[3]!r}. "
                             "Write the keyword in Latin letters inside tts, e.g. 'कमेंट करो, SAFE.'")
        return best[1]

    clips, t = [], LEAD_IN
    for i, line in enumerate(script["lines"]):
        ch = script["characters"][line["who"]]
        audio = synth_checked(line, ch)
        if i:
            t += SNAP_GAP if line.get("shot") == "simpler" else GAP
        clips.append((t, audio))
        line["start"], line["end"] = round(t, 3), round(t + len(audio) / SR, 3)
        t = line["end"]
        print(f"[{line['start']:6.2f}-{line['end']:6.2f}] {line['who']}: {line['caption']}", flush=True)

    if qc_report:
        (out_dir / "voice_qc.json").write_text(json.dumps(qc_report, ensure_ascii=False, indent=1), encoding="utf-8")
        left = [r for r in qc_report if r["issues"]]
        print(f"voice QC: {len(qc_report) - len(left)}/{len(qc_report)} lines clean"
              + "".join(f"\n   ! {r['line']}: {', '.join(r['issues'])}" for r in left), flush=True)
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
        ov = line.get("overlay") or {}
        if ov.get("type") == "quiz" and ov.get("stage") == "reveal":
            s = int((line["start"] + 0.2) * SR); sfx[s:s + len(p)] += p[: n - s]
        if ov.get("type") == "chat":
            msgs, d = ov.get("msgs", []), line["end"] - line["start"]
            for k, m in enumerate(msgs):
                s = int((line["start"] + m.get("at", k / len(msgs) * 0.85 + 0.05) * d) * SR); sfx[s:s + len(p)] += 0.6 * p[: n - s]
        if line.get("shot") in ("simpler", "payoff", "hook", "verdict", "result"):
            s = max(0, int((line["start"] - 0.25) * SR))
            sfx[s:s + len(w)] += w[: n - s]
        for op in line.get("board", []):
            if op["op"] in ("circle", "stamp"):
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
                "board_title": script.get("board_title", ""), "lines": script["lines"], "amp": amp, "shape": shape,
                "location": script.get("location", "classroom"), "board_style": script.get("board_style", ""),
                "quiz": script.get("quiz", {})}
    (out_dir / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False), encoding="utf-8")
    print(f"total {total:.2f}s, {frames} frames", flush=True)


if __name__ == "__main__":
    main()
