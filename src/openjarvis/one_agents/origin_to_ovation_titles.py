"""Origin to Ovation titles: each episode's own hook, never an earlier episode's sentence with a new name.

2026-10-23: the Virat Kohli title came out as "Virat Kohli: The Boy Behind the Records" - Sachin's "The Boy Behind
100 Centuries" with the name swapped - and it said nothing about the 134 -> 593 comeback its thumbnail sold. A
title is now refused when, with the subject's name taken out, it shares three words in a row with an earlier
episode's title. A thumbnail concept may carry the title written for it, so the picked picture and the title tell
one story. A mission without a title of its own is refused instead of falling back to Sachin's.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openjarvis.one_agents.origin_to_ovation_thumbnails import shared_phrase

YOUTUBE_TITLE_LIMIT = 100
# The first episode's title before seo.json carried it; still what an empty Sachin package means.
SACHIN_TITLE = "Sachin Tendulkar: The Boy Behind 100 International Centuries"


def story_part(title: str, subject: str) -> str:
    """The title without the subject's name, which naturally differs between episodes."""
    names = {w for w in re.findall(r"[a-z0-9]+", str(subject).lower())}
    return " ".join(w for w in re.findall(r"[a-z0-9]+", str(title).lower()) if w not in names)


def earlier_titles(missions_root: Path, current: str) -> list[dict[str, str]]:
    """Every other episode's title and subject."""
    found = []
    for mission in sorted(Path(missions_root).iterdir()):
        if not mission.is_dir() or mission.name == current:
            continue
        seo = mission / "runtime" / "seo.json"
        manifest = mission / "mission.json"
        title = json.loads(seo.read_text(encoding="utf-8-sig")).get("title", "") if seo.is_file() else ""
        if not title:
            continue
        subject = json.loads(manifest.read_text(encoding="utf-8-sig")).get("subject", "") if manifest.is_file() else ""
        found.append({"mission": mission.name, "title": title, "subject": subject})
    return found


def repeats(title: str, subject: str, earlier: list[dict[str, str]]) -> list[str]:
    """Why this title is not its own (empty when it is)."""
    reasons = []
    if not str(title).strip():
        reasons.append("title is empty")
    if len(str(title)) > YOUTUBE_TITLE_LIMIT:
        reasons.append(f"title is {len(title)} characters (YouTube allows {YOUTUBE_TITLE_LIMIT})")
    mine = story_part(title, subject)
    for other in earlier:
        phrase = shared_phrase(mine, story_part(other["title"], other["subject"]))
        if phrase:
            reasons.append(f"title repeats '{phrase}' from {other['mission']}")
    return reasons


def candidates(metadata: dict[str, Any], mission: str) -> list[str]:
    """The titles the episode's plan offers, best first; only Sachin's first episode may use the old default."""
    offered = [t for t in [*metadata.get("title_options", []), metadata.get("title", "")] if str(t).strip()]
    if not offered and mission == "sachin-first-video":
        offered = [SACHIN_TITLE]
    return list(dict.fromkeys(offered))


def pick(titles: list[str], subject: str, earlier: list[dict[str, str]]) -> tuple[str | None, dict[str, list[str]]]:
    """The first title that is its own, and why each refused one was refused."""
    refused = {}
    for title in titles:
        reasons = repeats(title, subject, earlier)
        if not reasons:
            return title, refused
        refused[title] = reasons
    return None, refused
