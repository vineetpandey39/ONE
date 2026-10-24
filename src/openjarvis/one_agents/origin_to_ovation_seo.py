"""ARES SEO contract for Origin to Ovation biographies.

The package keeps the episode's unique story promise while making the exact
subject query discoverable.  It does not claim that metadata alone caused a
view lift; analytics are recorded separately after enough traffic exists.
"""
from __future__ import annotations

import re
from typing import Any

from openjarvis.one_agents.youtube_seo import _valid_tags

MAX_DESCRIPTION = 5000
MIN_TAGS = 15
MAX_TAGS = 25
MIN_CHAPTERS = 5
MAX_CHAPTERS = 8


def primary_query(subject: str, metadata: dict[str, Any]) -> str:
    return str(metadata.get("primary_query") or f"{subject} biography").strip()


def concise_chapters(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep measured timestamps while reducing a 15-beat board to 5–8 useful sections."""
    if len(chapters) <= MAX_CHAPTERS:
        return chapters
    count = MAX_CHAPTERS
    indices = sorted({round(i * (len(chapters) - 1) / (count - 1)) for i in range(count)})
    return [chapters[i] for i in indices]


def ranked_tags(subject: str, metadata: dict[str, Any], title: str) -> list[str]:
    supplied = [str(tag) for tag in metadata.get("tags", []) if str(tag).strip()]
    sport = str(metadata.get("sport") or "sports").strip()
    candidates = [
        primary_query(subject, metadata), subject, title,
        f"{subject} story", f"{subject} journey", f"{subject} career",
        f"{subject} documentary", f"{subject} childhood", f"{subject} records",
        f"{subject} life story", f"{subject} success story",
        f"{sport} biography", f"{sport} documentary", f"{sport} history",
        "sports biography", "athlete biography", "Origin to Ovation", *supplied,
        *metadata.get("secondary_queries", []),
    ]
    return _valid_tags(candidates, limit=450)[:MAX_TAGS]


def hashtags(subject: str, metadata: dict[str, Any]) -> list[str]:
    offered = metadata.get("hashtags") or []
    clean = ["#" + re.sub(r"[^A-Za-z0-9_]", "", str(x).lstrip("#")) for x in offered]
    clean = [x for x in clean if 3 <= len(x) <= 30]
    compact_subject = re.sub(r"[^A-Za-z0-9]", "", subject)
    defaults = [f"#{compact_subject}", "#SportsBiography", "#OriginToOvation"]
    return list(dict.fromkeys(clean + defaults))[:3]


def build(*, subject: str, title: str, metadata: dict[str, Any], chapters: list[dict[str, Any]],
          sources: list[dict[str, Any]], voice_name: str) -> dict[str, Any]:
    query = primary_query(subject, metadata)
    lead = str(metadata.get("description_lead") or
               f"{query}: follow the documented journey behind {title}.").strip()
    if query.lower() not in lead[:200].lower():
        lead = f"{query} - {lead}"
    selected_chapters = concise_chapters(chapters)
    chapter_text = "\n".join(f"{c['timestamp']} {c['title']}" for c in selected_chapters)
    source_text = "\n".join(str(record["url"]) for record in sources)
    hash_list = " ".join(hashtags(subject, metadata))
    description = (
        lead + "\n\n" +
        "This cinematic biography follows the verified turning points, setbacks, records and legacy behind the journey. "
        f"Third-person narration by {voice_name}; original CGI reconstructions, no athlete voice clone or invented dialogue.\n\n"
        "CHAPTERS\n" + chapter_text + "\n\nSOURCES\n" + source_text +
        "\n\nWhich sporting journey should we explore next? Subscribe to Origin to Ovation.\n\n" + hash_list
    )
    package = {
        "title": title, "description": description, "primary_query": query,
        "secondary_queries": list(metadata.get("secondary_queries", [])),
        "tags": ranked_tags(subject, metadata, title), "hashtags": hashtags(subject, metadata),
        "chapters": selected_chapters, "original_chapter_count": len(chapters), "sources": sources, "seo_owner": "ARES",
        "strategy": "unique_story_promise_plus_subject_search_intent_v1",
        "post_publish_learning": {
            "minimum_wait": "Wait for processed traffic-source and retention data; never infer causation from a few views.",
            "compare": ["impressions", "ctr_by_traffic_source", "youtube_search_terms", "intro_30s",
                        "average_view_duration", "average_percentage_viewed", "suggested_video_sources"],
            "decision": "Record the metadata change, timestamp, before/after window, hypothesis and one next-video test.",
        },
    }
    errors = audit(package, subject)
    if errors:
        raise ValueError("ARES Origin to Ovation SEO blocked: " + "; ".join(errors))
    package["seo_audit"] = {"status": "passed", "checks": {
        "unique_story_title": True, "primary_query_in_first_200_chars": True,
        "concise_chapters": True, "tag_budget": True, "three_hashtags": True,
    }}
    return package


def audit(package: dict[str, Any], subject: str) -> list[str]:
    errors = []
    title = str(package.get("title", ""))
    description = str(package.get("description", ""))
    query = str(package.get("primary_query", ""))
    tags = package.get("tags") or []
    chapters = package.get("chapters") or []
    if not title or len(title) > 100 or subject.lower() not in title.lower():
        errors.append("title must contain the subject and fit YouTube's 100-character limit")
    if not query or query.lower() not in description[:200].lower():
        errors.append("primary query must appear naturally in the first 200 description characters")
    if len(description) > MAX_DESCRIPTION:
        errors.append("description exceeds 5000 characters")
    if int(package.get("original_chapter_count", len(chapters))) >= MIN_CHAPTERS and not MIN_CHAPTERS <= len(chapters) <= MAX_CHAPTERS:
        errors.append("use 5-8 concise chapters")
    if len(tags) < MIN_TAGS or len(tags) > MAX_TAGS:
        errors.append("use 15–25 relevant tags")
    if len(set(map(str.lower, tags))) != len(tags):
        errors.append("tags must be distinct")
    if len(package.get("hashtags") or []) != 3:
        errors.append("use exactly three hashtags")
    if package.get("seo_owner") != "ARES":
        errors.append("SEO package must be owned by ARES")
    return errors
