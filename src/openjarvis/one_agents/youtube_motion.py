"""Reusable weekday programming and the existing Motion V3 kinetic director.

No brand, travel topic, browser login or shared YATRA history is inherited.
"""
from __future__ import annotations

import hashlib
import json
import math
import textwrap
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openjarvis.one_agents.production_motion import card_renderer, layout_grammar

LIBRARY = Path(__file__).with_name("production_motion")


def choose_format(day: str, *, override: str | None = None) -> dict:
    catalog = json.loads((LIBRARY / "formats.json").read_text(encoding="utf-8"))
    date = datetime.fromisoformat(day).date()
    weekday = date.strftime("%A")
    family = override or catalog["weekdays"].get(weekday, catalog["weekend"])
    if family not in catalog["formats"]:
        raise ValueError("Unknown shared motion format")
    return {"format_family": family, "format_rules": catalog["formats"][family],
            "format_date": day, "weekday": weekday, "preview_override": bool(override),
            "schedule": "Monday-Friday; cinematic-clean weekends", "library_version": catalog["version"]}


def assignment(root: Path, *, override: str | None = None, day: str | None = None) -> dict:
    path = root / "motion-assignment.json"
    if path.exists():
        prior = json.loads(path.read_text(encoding="utf-8"))
        if override and prior["format_family"] != override:
            raise ValueError("Mission already has another format; explicitly repair the assignment first")
        return prior
    result = choose_format(day or datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat(), override=override)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def library_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in LIBRARY.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        digest.update(path.relative_to(LIBRARY).as_posix().encode())
        digest.update(path.read_bytes())
    digest.update(Path(__file__).read_bytes())
    return digest.hexdigest()


class KineticDirector:
    def __init__(self, root: Path, *, brand: str, selected: dict):
        self.root, self.brand, self.selected = root, brand, selected
        self.used, self.usage, self.receipts = set(), {}, []
        self.renderer = card_renderer.CardRenderer()

    def __enter__(self):
        self.renderer.__enter__()
        return self

    def __exit__(self, *exc):
        self.renderer.__exit__(*exc)

    def spec(self, text: str, *, scene: int, beat: int, seconds: float,
             overlay=False, credit="", note="") -> dict:
        if not text.strip() or len(text) > 120:
            raise ValueError("Supply concise authored motion copy (1-120 characters)")
        lines = textwrap.wrap(text, width=22 if overlay else 16, break_long_words=False, break_on_hyphens=False)
        if len(lines) > 4:
            raise ValueError("Motion copy needs shortening")
        spec = {"template": "lower" if overlay else "statement", "duration": seconds, "overlay": overlay,
                "lines": lines, "size": 82 if overlay else 104, "brand": self.brand,
                "tag": self.brand, "kicker": "Source imagery" if overlay else "Science explained",
                "sub": credit[:120], "note": note, "idx": f"{scene:02d} / {beat:02d}"}
        directed = layout_grammar.direct(spec, {"layout": "evidence", "headline": text},
            video_id=f"{self.brand}:{self.root.name}", scene_id=str(scene), beat_id=str(beat),
            recent=[], used=self.used, usage=self.usage,
            world={"format_family": self.selected["format_family"], "visual_world": "channel-authored",
                   "rules": {"palettes": ["monsoon", "andaman"], "motifs": ["orbit", "soft-particles", "contour"]}})
        return directed

    def scene(self, scene: dict, media: dict, *, number: int, seconds: float, out: Path,
              command) -> int:
        """Frame-exact alternating evidence and typography beats, maximum 4s holds."""
        frames = round(seconds * 30)
        count = max(1, math.ceil(frames / 105))
        copy = scene.get("motion_copy") or [scene["title"], *scene.get("screen_text", "").split("|")]
        copy = list(dict.fromkeys(t.strip() for t in copy if t.strip()))
        if not copy:
            raise ValueError("Authored motion copy is missing")
        paths = []
        assets = media.get("assets") or []
        for index in range(count):
            nframes = round(frames * (index + 1) / count) - round(frames * index / count)
            duration = nframes / 30
            target = out.with_name(f"{out.stem}-beat-{index + 1:02d}.mp4")
            overlay = bool(assets) and (index % 2 == 1 or media["kind"] in {"stock", "obs"})
            text = copy[index % len(copy)]
            credit = media.get("credit", "") if overlay else (
                "Explanatory graphic · Not to scale" if scene.get("illustrative") else "Primary-source science")
            if overlay and media["kind"] == "stock":
                credit = "Envato · Illustrative footage"
            spec = self.spec(text, scene=number, beat=index + 1, seconds=duration,
                             overlay=overlay, credit=credit, note=self.brand)
            if overlay:
                source = Path(assets[index % len(assets)]["path"]).resolve()
                if not source.is_relative_to(self.root.resolve()):
                    raise ValueError("Motion media must belong to this mission")
                if source.suffix.lower() in {".jpg", ".png", ".jpeg", ".webp"}:
                    inputs = ["-loop", "1", "-i", str(source)]
                else:
                    source_seconds = max(1.0, float(assets[index % len(assets)].get("seconds") or 24))
                    offset = ((index // len(assets)) * duration) % source_seconds
                    inputs = ["-stream_loop", "-1", "-ss", f"{offset:.3f}", "-i", str(source)]
                base = ("[0:v]fps=30,scale=1920:1080:force_original_aspect_ratio=increase,"
                        "crop=1920:1080,setsar=1[base]")
                self.renderer.render_over(spec, base, inputs, target)
            else:
                self.renderer.render_clip(spec, target)
            self.receipts.append({"scene": number, "beat": index + 1, "frames": nframes,
                "text": text, "kind": "evidence" if overlay else "motion", "direction": spec["direction"]})
            paths.append(target)
        listing = out.with_suffix(".beats.txt")
        listing.write_text("\n".join("file '" + p.as_posix().replace("'", "'\\''") + "'" for p in paths), encoding="utf-8")
        command(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                 "-c", "copy", "-movflags", "+faststart", str(out)])
        return count

    def save_receipt(self):
        path = self.root / "edit" / "direction-receipt.json"
        path.write_text(json.dumps({**self.selected, "engine": "shared-motion-v3",
            "brand": self.brand, "library_sha256": library_hash(), "beats": self.receipts}, indent=2), encoding="utf-8")
