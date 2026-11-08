"""ARES SEO contract for Origin to Ovation biographies.

The package keeps the episode's unique story promise while making the exact
subject query discoverable.  It does not claim that metadata alone caused a
view lift; analytics are recorded separately after enough traffic exists.
"""
from __future__ import annotations

import re
from typing import Any

from openjarvis.one_agents.youtube_seo import _query_seed, _valid_tags, _viewer_facing

MAX_DESCRIPTION = 5000
MIN_TAGS = 15
MAX_TAGS = 25
MIN_CHAPTERS = 5
MAX_CHAPTERS = 8


def primary_query(subject: str, metadata: dict[str, Any]) -> str:
    value = str(metadata.get("primary_query") or f"{subject} biography")
    return " ".join(re.sub(r"[^\w%₹+.'-]+", " ", value, flags=re.UNICODE).strip().split())


def secondary_queries(subject: str, metadata: dict[str, Any]) -> list[str]:
    primary = primary_query(subject, metadata)
    sport = _query_seed(metadata.get("sport") or "sports")
    supplied = [_query_seed(q) for q in metadata.get("secondary_queries", []) if str(q).strip()]
    grounded = [f"{subject} life story", f"{subject} career", f"{subject} documentary",
                f"{subject} journey", f"{sport} biography"]
    return [q for q in dict.fromkeys(supplied + grounded) if q and q != primary][:6]


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
        *secondary_queries(subject, metadata),
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
    lead = _viewer_facing(str(metadata.get("description_lead") or ""),
                          f"{query}: this video follows the documented journey behind {title}.")
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
        "secondary_queries": secondary_queries(subject, metadata),
        "tags": ranked_tags(subject, metadata, title), "hashtags": hashtags(subject, metadata),
        "chapters": selected_chapters, "original_chapter_count": len(chapters), "sources": sources, "seo_owner": "ARES",
        "strategy": "unique_story_promise_plus_subject_search_intent_v2",
        "seo_schema_version": "1.2",
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
    package["seo_strategy_audit"] = strategy_audit(package)
    package["seo_audit"] = {"status": "passed", "checks": {
        "unique_story_title": True, "primary_query_in_first_200_chars": True,
        "concise_chapters": True, "tag_budget": True, "three_hashtags": True,
        "shared_strategy_passed": True,
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
    if not strategy_audit(package)["ok"]:
        errors.append("shared SEO strategy audit failed")
    return errors


def strategy_audit(package: dict[str, Any]) -> dict[str, Any]:
    tags = list(package.get("tags") or [])
    lead = str(package.get("description") or "").split("CHAPTERS\n", 1)[0]
    checks = {
        "natural_primary_query": 2 <= len(str(package.get("primary_query") or "").split()) <= 9,
        "four_secondary_queries": len(package.get("secondary_queries") or []) >= 4,
        "clean_tag_set": MIN_TAGS <= len(tags) <= MAX_TAGS and not any(
            re.search(r"(?:\s|^)(and|or|with|for|to|from|&)$", str(tag)) for tag in tags),
        "viewer_facing_copy": not bool(re.match(
            r"^(explain|show|cover|discuss|break down|compare|describe)\b", lead.strip(), re.I)),
    }
    return {"ok": all(checks.values()), "checks": checks}
