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
SHOTS = {"hook", "explain", "simpler", "story", "reveal", "realize", "payoff", "cta"}


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
    if not 60 <= words <= 140:
        errs.append(f"{words} spoken words; aim for 90-120 (35-45 s)")
    return errs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--out", help="output folder (default out/<id>)")
    ap.add_argument("--handle", default="@aibyvineet")
    args, audio_args = ap.parse_known_args()

    script_path = Path(args.script)
    script = json.loads(script_path.read_text(encoding="utf-8"))
    errs = validate(script)
    if errs:
        sys.exit("script invalid:\n  " + "\n  ".join(errs))
    out = Path(args.out or HERE / "out" / script["id"])

    subprocess.run([sys.executable, str(HERE / "build_audio.py"), str(script_path), str(out), *audio_args], check=True)
    subprocess.run(["node", str(HERE / "render.js"), str(out), "--handle", args.handle], check=True)
    caption = script.get("post_caption") or script.get("title", "")
    (out / "caption.txt").write_text(caption, encoding="utf-8")
    print(json.dumps({"video": str(out / "reel.mp4"), "caption": str(out / "caption.txt")}))


if __name__ == "__main__":
    main()
