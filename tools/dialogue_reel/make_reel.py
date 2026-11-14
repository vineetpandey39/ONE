"""One command: script JSON -> validated -> audio -> render -> reel.mp4 + caption.txt.

  python3 make_reel.py scripts/ep02_prompt.json                       # Kokoro voices
  python3 make_reel.py scripts/ep02_prompt.json --tts elevenlabs \\
      --music assets/music/track.mp3 --sfx-dir assets/sfx               # PC: ElevenLabs + Envato

This is the entry point an agent (KAIROS) calls; publishing is a separate step.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHOTS = {"hook", "explain", "simpler", "story", "reveal", "realize", "payoff", "cta", "follow"}


def validate(script: dict) -> list[str]:
    errs = []
    for k in ("id", "board_title", "characters", "lines"):
        if k not in script:
            errs.append(f"missing '{k}'")
    if errs:
        return errs
    ids: set[str] = set()
    words = 0
    for i, ln in enumerate(script["lines"], 1):
        if ln.get("who") not in script["characters"]:
            errs.append(f"line {i}: unknown speaker {ln.get('who')!r}")
        if ln.get("shot") not in SHOTS:
            errs.append(f"line {i}: unknown shot {ln.get('shot')!r}")
        for k in ("caption", "tts"):
            if not str(ln.get(k, "")).strip():
                errs.append(f"line {i}: empty {k}")
        tts = str(ln.get("tts", ""))
        letters = [c for c in tts if c.isalpha()]
        deva = sum("\u0900" <= c <= "\u097f" for c in letters)
        if letters and deva / len(letters) < 0.8:
            errs.append(f"line {i}: tts must be Devanagari (voice pronunciation depends on it): {tts[:40]!r}")
        n = len(str(ln.get("caption", "")).split())
        words += n
        if n > 20:
            errs.append(f"line {i}: {n} words (max 20)")
        for op in ln.get("board", []):
            if op.get("op") == "write":
                ids.add(op.get("id"))
                if len(op.get("text", "")) > 40:
                    errs.append(f"line {i}: board text too long: {op['text']!r}")
            elif op.get("op") in ("strike", "circle"):
                if op.get("target") not in ids:
                    errs.append(f"line {i}: {op['op']} targets unknown id {op.get('target')!r}")
            else:
                errs.append(f"line {i}: unknown board op {op.get('op')!r}")
            if not 0 <= float(op.get("at", -1)) <= 1:
                errs.append(f"line {i}: board 'at' must be 0..1")
    errs += validate_seo(script)
    if not 60 <= words <= 140:
        errs.append(f"{words} spoken words; aim for 90-120 (35-45 s)")
    return errs


def validate_seo(script: dict) -> list[str]:
    """Instagram/YouTube discoverability checks on the post copy."""
    errs = []
    cap = script.get("post_caption", "")
    seo = script.get("seo", {})
    if not cap:
        return ["missing post_caption"]
    if len(cap) > 2200:
        errs.append(f"post_caption {len(cap)} chars (Instagram max 2200)")
    tags = [w for w in cap.split() if w.startswith("#")]
    if not 3 <= len(tags) <= 5:
        errs.append(f"{len(tags)} hashtags; use 3-5 relevant ones")
    first = cap.splitlines()[0].lower()
    kws = [k.lower() for k in seo.get("keywords", [])]
    if kws and not any(k.split()[0] in first for k in kws):
        errs.append("first caption line should carry the main search keyword")
    for k in ("alt_text", "cover_text", "pinned_comment", "youtube", "file_name"):
        if k not in seo:
            errs.append(f"seo.{k} missing")
    yt = seo.get("youtube", {})
    if len(yt.get("title", "")) > 100:
        errs.append("youtube title over 100 chars")
    return errs


def _cover_font() -> str:
    """Poppins ExtraBold as TTF for ffmpeg (fontsource ships woff2)."""
    ttf = HERE / "out" / ".fonts" / "poppins-800.ttf"
    if not ttf.exists():
        from fontTools.ttLib import TTFont  # pip install fonttools brotli
        ttf.parent.mkdir(parents=True, exist_ok=True)
        f = TTFont(HERE / "node_modules/@fontsource/poppins/files/poppins-latin-800-normal.woff2")
        f.flavor = None
        f.save(ttf)
    return str(ttf)


def make_cover(video: Path, dst: Path, title: str, sub: str = "") -> None:
    """Wide opening frame (both characters) + title card, inside the 3:4 grid-safe area."""
    esc = lambda t: t.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\u2019")
    ft = _cover_font()
    vf = (f"eq=brightness=-0.05,drawbox=x=24:y=300:w=672:h=240:color=0x202838@0.9:t=fill,"
          f"drawtext=fontfile={ft}:text='{esc(title)}':fontsize=62:fontcolor=white:x=(w-tw)/2:y=345,"
          f"drawtext=fontfile={ft}:text='{esc(sub)}':fontsize=38:fontcolor=0xFF7A1A:x=(w-tw)/2:y=455")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.15", "-i", str(video), "-frames:v", "1",
                    "-vf", vf, str(dst)], check=True)


def package(script: dict, out: Path) -> dict:
    """caption.txt, seo.json and a keyword-named copy of the video for upload."""
    seo = script.get("seo", {})
    (out / "caption.txt").write_text(script.get("post_caption") or script.get("title", ""), encoding="utf-8")
    (out / "seo.json").write_text(json.dumps({"post_caption": script.get("post_caption"), **seo},
                                             ensure_ascii=False, indent=2), encoding="utf-8")
    video = out / "reel.mp4"
    if seo.get("cover_text") and video.exists():
        make_cover(video, out / "cover.jpg", *seo["cover_text"][:2])
    if seo.get("file_name") and video.exists():
        named = out / seo["file_name"]
        named.write_bytes(video.read_bytes())
        video = named
    return {"video": str(video), "cover": str(out / "cover.jpg"), "caption": str(out / "caption.txt"),
            "seo": str(out / "seo.json")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--out", help="output folder (default out/<id>)")
    ap.add_argument("--handle", default="@aibyvineet")
    ap.add_argument("--package-only", action="store_true", help="skip audio+render; only write caption/seo files")
    args, audio_args = ap.parse_known_args()

    script_path = Path(args.script)
    script = json.loads(script_path.read_text(encoding="utf-8"))
    errs = validate(script)
    if errs:
        sys.exit("script invalid:\n  " + "\n  ".join(errs))
    out = Path(args.out or HERE / "out" / script["id"])

    if not args.package_only:
        subprocess.run([sys.executable, str(HERE / "build_audio.py"), str(script_path), str(out), *audio_args], check=True)
        subprocess.run(["node", str(HERE / "render.js"), str(out), "--handle", args.handle], check=True)
    print(json.dumps(package(script, out)))


if __name__ == "__main__":
    main()
