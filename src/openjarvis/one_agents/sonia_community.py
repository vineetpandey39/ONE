"""Sonia Travel Vlogs' daily YouTube Community image poll, as ONE's agents see it.

The work itself lives with the LAO tools (C:\\Users\\pc\\Documents\\LAO\\sonia-community\\community_poll.py), beside
the Envato photo package and Sonia's own Chrome profile; this module only loads it and builds IRIS's brief from
Sanjeevani's latest scored travel stories. IRIS (floor head, local only) writes the brief; ECHO runs the post.
The Chairman approved one public poll a day with no per-post approval (2026-10-09).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

TOOL_DIR = Path(os.environ.get("SONIA_COMMUNITY_DIR") or r"C:\Users\pc\Documents\LAO\sonia-community")
TASK_MARKER = "[sonia-community-poll]"
RANKING_MAX_AGE_HOURS = 72.0


def load() -> Any:
    path = TOOL_DIR / "community_poll.py"
    if not path.is_file():
        raise RuntimeError(f"community poll tool not found: {path}")
    if str(TOOL_DIR) not in sys.path:
        sys.path.insert(0, str(TOOL_DIR))
    spec = importlib.util.spec_from_file_location("community_poll", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["community_poll"] = module
    spec.loader.exec_module(module)
    return module


def latest_story_ranking(outputs: Path, *, now: float | None = None,
                         max_age_hours: float = RANKING_MAX_AGE_HOURS) -> list[dict[str, Any]]:
    """Destinations from the newest IRIS story ranking (written on every Sonia video run), freshest stories first.

    Eligible stories lead; stories that only failed the video gates (one outlet, a recent repeat) still make good
    poll material. Older than three days, nothing: a poll must not dress up stale news as this week's."""
    now = now or time.time()
    files = sorted(outputs.glob("*-yatra-story-ranking.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    files = [p for p in files if not p.name.startswith("dryrun") and now - p.stat().st_mtime <= max_age_hours * 3600]
    if not files:
        return []
    data = json.loads(files[0].read_text(encoding="utf-8"))
    rows = sorted(data.get("ranking") or [], key=lambda r: (r.get("verdict") != ["eligible"], -float(r.get("score") or 0)))
    return [{"destination": r.get("destination"), "title": r.get("title")} for r in rows if r.get("destination")]


def brief_for(today: date, outputs: Path, *, discover=None) -> dict[str, Any]:
    """Today's brief. `discover` (Sanjeevani travel discovery) runs only when no recent ranking exists."""
    news = latest_story_ranking(outputs)
    source = "story_ranking"
    if not news and discover is not None:
        try:
            news = [{"destination": c.get("destination"), "title": c.get("title")} for c in discover()]
            source = "travel_discovery"
        except Exception as exc:  # noqa: BLE001 - a poll without news still has six other formats' worth of ideas
            source = f"none ({type(exc).__name__})"
    brief = load().build_brief(today, news)
    brief["news_source"] = source
    return brief
