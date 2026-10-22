"""Origin to Ovation thumbnails: several story-led concepts per episode, never a copy of an earlier episode.

2026-10-23: the Virat Kohli thumbnail repeated Sachin's formula - "THE BOY BEHIND THE ..." in the same white-and-gold
type over the same floodlit stadium - so the second episode looked like the first one already watched. Each episode
now brings its own concepts built on its own story (a number, a contrast, a question), and a concept is refused when
it shows a face or resembles an earlier episode's thumbnail in picture or headline. The Chairman picks; until he
does, the first concept that passes is used.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Average-difference hash on a 9x8 grey thumbnail: 64 bits. Two renders of one layout land within a few bits;
# unrelated compositions sit far apart. 12 bits is "the same picture with small changes".
SIMILAR_BITS = 12


def dhash(image: Path) -> int:
    from PIL import Image
    grey = Image.open(image).convert("L").resize((9, 8))
    pixels = list(grey.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return bits


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text).lower())


def shared_phrase(a: str, b: str, size: int = 3) -> str:
    """The first run of `size` words both headlines share ("the boy behind"), or ""."""
    left = _words(a)
    right = " " + " ".join(_words(b)) + " "
    for i in range(len(left) - size + 1):
        phrase = " ".join(left[i:i + size])
        if f" {phrase} " in right:
            return phrase
    return ""


def earlier_thumbnails(missions_root: Path, current: str) -> list[dict[str, Any]]:
    """Every other episode's final thumbnail and its headline."""
    found = []
    for mission in sorted(Path(missions_root).iterdir()):
        if not mission.is_dir() or mission.name == current:
            continue
        image = mission / "production" / "master-v1" / "thumbnail.png"
        if not image.is_file():
            continue
        meta_path = mission / "production" / "master-v1" / "editorial-metadata.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        headline = meta.get("thumbnail_headline") or _headline_from_prompt(meta.get("thumbnail_prompt", ""))
        found.append({"mission": mission.name, "image": image, "headline": headline})
    return found


def _headline_from_prompt(prompt: str) -> str:
    match = re.search(r"headline(?: only)?:?\s*([A-Z0-9][A-Z0-9 ,.'’→-]{3,})", str(prompt))
    return match.group(1).strip(" .") if match else ""


def resemblance(image: Path, headline: str, earlier: list[dict[str, Any]]) -> list[str]:
    """Why this concept looks like an earlier episode (empty when it does not)."""
    reasons = []
    mine = dhash(image)
    for other in earlier:
        distance = bin(mine ^ dhash(other["image"])).count("1")
        if distance <= SIMILAR_BITS:
            reasons.append(f"picture matches {other['mission']} ({distance}/64 bits apart)")
        phrase = shared_phrase(headline, other["headline"])
        if phrase:
            reasons.append(f"headline repeats '{phrase}' from {other['mission']}")
    return reasons


def choose(concepts: list[dict[str, Any]], choice: str | None) -> dict[str, Any] | None:
    """The Chairman's pick when it passed, otherwise the first concept that passed."""
    passed = [c for c in concepts if not c.get("rejected")]
    picked = next((c for c in passed if choice and c["name"] == choice), None)
    return picked or (passed[0] if passed else None)
