"""LYRA's topic-independent YouTube package builder for Sonia Travel Vlogs.

Everything topic-specific comes from YATRA's production plan (the ChatGPT packaging block,
the script, the scene plan, the claim ledger) and from one local-model call for the wording
that has to be written fresh (chapter names, intro, tags, thumbnail hooks). Every model
answer is validated, and each field has a deterministic fallback, so a missing or confused
model can only make the package plainer - never wrong, and never about another destination.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from openjarvis.one_agents import local_llm
from openjarvis.one_agents.youtube_channels import ChannelProfile, SONIA


_KV = re.compile(r"^([a-z0-9_]+):\s*(.+)$", re.M)
_CUE = re.compile(r"\[(\d{1,2}):(\d{2})\s*[–—-]\s*[^\]]*\]\s*\n(.*?)(?=\n\s*\[\d{1,2}:\d{2}|\Z)", re.S)
_URL = re.compile(r"https?://[^\s)>\]]+")
_WORD = re.compile(r"[a-z0-9]+")
# Hook words that carry no fact, so a thumbnail may use them even if the brief never says them.
_HOOK_OK = {"new", "now", "rule", "rules", "why", "how", "what", "this", "that", "dont", "don", "t", "miss", "stop",
            "before", "you", "your", "go", "read", "first", "wait", "watch", "update", "alert", "guide", "know",
            "need", "must", "real", "truth", "mistake", "mistakes", "check", "safe", "plan", "trip", "is", "it", "a"}
_GENERIC_THUMBNAIL_HOOKS = {"WHAT'S NEW?", "WHATS NEW?", "BIG UPDATE", "MUST WATCH", "NEW UPDATE"}

LLM = Callable[[str, dict], dict]

# Metadata locales chosen for Sonia's Indian core audience plus large travel-search markets.
# YouTube automatic dubbing is a separate Studio feature; this list controls title/description only.
GLOBAL_METADATA_LOCALES = list(SONIA.locales)
TRAVEL_PLAYLIST_ID = SONIA.playlist_id
TRAVEL_PLAYLIST_URL = SONIA.playlist_url
CHANNEL_SUBSCRIBE_URL = SONIA.subscribe_url


def fallback_hashtags(title: str, channel: ChannelProfile = SONIA) -> list[str]:
    """Three truthful deterministic hashtags when the wording model is unavailable."""
    title_words = re.findall(r"[A-Za-z0-9]+", _title_head(title))[:3]
    title_tag = "#" + "".join(word[:1].upper() + word[1:] for word in title_words)
    if not re.fullmatch(r"#[A-Za-z][A-Za-z0-9]{1,29}", title_tag):
        title_tag = "#TravelUpdate" if channel == SONIA else "#VideoGuide"
    channel_tag = "#" + re.sub(r"[^A-Za-z0-9]", "", channel.display_name)
    if not re.fullmatch(r"#[A-Za-z][A-Za-z0-9]{1,29}", channel_tag):
        channel_tag = "#TravelGuide" if channel == SONIA else "#YouTubeGuide"
    result = list(dict.fromkeys([
        title_tag, "#TravelGuide" if channel == SONIA else "#Explained", channel_tag,
    ]))
    while len(result) < 3:
        result.append("#TravelTips" if channel == SONIA else "#WatchNow")
    return result[:3]


def repair_description_hashtags(package: dict[str, Any], channel: ChannelProfile = SONIA) -> dict[str, Any]:
    """Repair only the hashtag line and its audit; preserve every other saved field."""
    description = str(package.get("description") or "")
    if len(re.findall(r"(?<!\w)#\w+", description)) != 3:
        lines = [line for line in description.splitlines()
                 if not re.fullmatch(r"\s*(?:#[A-Za-z][A-Za-z0-9_]{1,39}\s*)+", line)]
        description = "\n".join(lines).rstrip() + "\n\n" + " ".join(
            fallback_hashtags(str(package.get("recommended_title") or ""), channel))
        package["description"] = description[:5000]
    package["description_audit"] = description_audit(
        str(package.get("description") or ""), str(package.get("primary_query") or ""),
        list(package.get("tags") or []), channel)
    return package


def llm_options(temperature: float, num_ctx: int) -> dict:
    return local_llm.options(temperature, num_ctx)


def ollama_json(system: str, payload: dict) -> dict:
    """Short structured metadata: small fast models first, CPU only, next model on failure."""
    return local_llm.run("short", system, payload, temperature=0.2, num_ctx=12288)


def parse_packaging(text: str) -> dict[str, str]:
    return {k: v.strip() for k, v in _KV.findall(text or "")}


def script_cues(script: str) -> list[tuple[int, int, str]]:
    return [(int(m), int(s), " ".join(body.split())) for m, s, body in _CUE.findall(script or "")]


# A scene block starts at "1:" or, as the first English plan wrote it (Air France, 2026-10-08), "scene_01:". With only
# the first form understood, the whole plan was one block, so 19 of 20 chapters lost their on-screen text and were
# named after the narration's first words.
SCENE_HEADER = re.compile(r"(?mi)^\s*(?:scene[_ ]?)?\d+[.:]\s*$")


def scene_purposes(scene_plan: str) -> list[str]:
    """One purpose line per scene block, in order."""
    purposes: list[str] = []
    for block in re.split(SCENE_HEADER, scene_plan or ""):
        m = re.search(r"(?m)^\s*purpose:\s*(.+)$", block)
        if m:
            purposes.append(m.group(1).strip())
    return purposes


def scene_screen_texts(scene_plan: str) -> list[str]:
    """The viewer-facing on_screen_text of each scene block, in order ('' where a scene has none)."""
    texts: list[str] = []
    for block in re.split(SCENE_HEADER, scene_plan or ""):
        if not re.search(r"(?m)^\s*-?\s*(purpose|on_screen_text|time(?:code)?):", block):
            continue
        m = re.search(r"(?m)^\s*-?\s*on_screen_text:\s*\"?(.+?)\"?\s*$", block)
        texts.append(m.group(1).strip() if m else "")
    return texts


def narration_timeline(plan_path: Path | None) -> list[float]:
    """Measured start second of every narration segment (the voice as recorded), or [] if unknown.

    The script's [m:ss] cues are guesses made before the voice existed; the Vietnam video's chapters came out every
    30 s and ended at 4:00 on a 12:39 video (2026-10-06). The narration manifest records where each scene really starts.
    """
    if not plan_path:
        return []
    manifest = Path(plan_path).parent / "narration" / "narration.segments.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    segments = data.get("segments", data) if isinstance(data, dict) else data
    starts = [float(s.get("start")) for s in segments if isinstance(s, dict) and s.get("start") is not None]
    return starts if starts and starts == sorted(starts) and starts[0] == 0.0 else []


def _words(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def _clean(text: str, limit: int) -> str:
    return re.sub(r"[<>]", "", " ".join(str(text).split()))[:limit].strip()


def clean_title(text: str, limit: int = 100) -> str:
    """Strip source-feed quoting/Markdown and publisher suffixes from a public title."""
    value = _clean(text, limit + 40).strip(" \t\r\n\"'`*_#")
    value = re.sub(r"\s+-\s+(?:Brand Spur|YouTube)$", "", value, flags=re.I)
    return value[:limit].rstrip(" \t\r\n-|:;,.")


def _cut_words(text: str, limit: int) -> str:
    """At most `limit` characters, cut at a word boundary (never mid-word)."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit + 1].rsplit(" ", 1)[0].rstrip(" ,.;:-|•")
    return cut if len(cut) >= 3 else text[:limit]


_KEEP_UPPER = {"IRCTC", "USA", "UK", "UAE", "TDAC", "OTP", "ETA", "EU", "UN", "GST", "PNR"}


def _title_case(part: str) -> str:
    if not part.isupper():
        return part
    return " ".join(w if w in _KEEP_UPPER or any(c.isdigit() for c in w) else w.capitalize() for w in part.split())


def _screen_label(screen_text: str) -> str:
    """'ITINERARY | FLIGHTS | STAY | VISA' -> 'Itinerary, Flights, Stay, Visa' (whole parts only, up to 48 chars).

    One part alone ('Flight', 'Package') was too thin to tell chapters apart."""
    parts = [_title_case(p.strip(" \"'")) for p in re.split(r"\s*\|\s*", screen_text or "") if p.strip(" \"'")]
    label = ""
    for part in parts:
        joined = f"{label}, {part}" if label else part
        if len(joined) > 48:
            break
        label = joined
    return re.sub(r"[<>]", "", label or (_cut_words(parts[0], 48) if parts else ""))


def _fallback_label(screen_text: str, narration: str, index: int) -> str:
    """Viewer-facing words only. The plan's `purpose` is a director's note ('open on vietnam/cambodia beauty,
    establish chen...') and once became every chapter title of the Vietnam video; it is never used here."""
    label = _screen_label(screen_text)
    if label:
        return label
    words = re.sub(r"[<>]", "", narration or "").split()
    return _cut_words(" ".join(words[:7]), 48) if words else f"Part {index + 1}"


def chapter_labels(cues: list, screen_texts: list[str], title: str, llm: LLM | None,
                   search_terms: list[str] | None = None, *, topic: str = "travel") -> tuple[list[tuple[int, str]], str]:
    n = len(cues)
    search_terms = [x for x in (search_terms or []) if x]
    if llm and n:
        try:
            grouped = n >= 5
            out = llm(
                f"You create search-friendly YouTube chapters for a {topic} video. Group adjacent scenes into 5 to 8 "
                "meaningful viewer-intent sections; do not make one chapter per narration scene. Base titles on the "
                "provided target search queries when that query is truthfully covered by the grouped scenes. Each "
                "title must be 2 to 7 words, natural language, specific, and useful as a YouTube search phrase. "
                "Do not copy the narration's opening words and do not use clickbait or colons. Return JSON "
                "{\"chapters\": [{\"start_index\": 0, \"title\": \"...\"}, ...]}; start_index is zero-based, "
                "strictly increasing, and the first value must be 0. For videos with fewer than 5 scenes, return "
                "one chapter per scene in the same format.",
                {"video_title": title, "target_search_queries": search_terms,
                 "scenes": [{"on_screen": screen_texts[i] if i < len(screen_texts) else "",
                                                   "narration": cues[i][2][:260]} for i in range(n)]})
            raw = out.get("chapters", [])
            chapters = [(int(x["start_index"]), _cut_words(_clean(x["title"], 200), 60)) for x in raw]
            indices = [i for i, _ in chapters]
            labels = [label for _, label in chapters]
            expected_count = range(5, min(8, n) + 1) if grouped else [n]
            if (len(chapters) in expected_count and indices[0] == 0 and indices == sorted(set(indices))
                    and indices[-1] < n and all(3 <= len(x) <= 60 for x in labels)
                    and len(set(labels)) == len(labels)):
                return chapters, "model-grouped" if grouped else "model"
        except Exception:  # noqa: BLE001 - fall through to the deterministic labels
            pass
    labels = [_fallback_label(screen_texts[i] if i < len(screen_texts) else "", cues[i][2], i) for i in range(n)]
    seen: dict[str, int] = {}
    for i, label in enumerate(labels):  # duplicate chapter names read as a mistake; keep each distinct
        seen[label] = seen.get(label, 0) + 1
        if seen[label] > 1:
            labels[i] = f"{label} ({seen[label]})"
    if n >= 5:
        count = min(6, n)
        indices = sorted({round(i * (n - 1) / (count - 1)) for i in range(count)})
    else:
        indices = list(range(n))
    return [(i, labels[i]) for i in indices], "fallback-grouped" if n >= 5 else "fallback"


def _valid_tags(tags: list[str], limit: int = 500) -> list[str]:
    """Return unique tags that fit YouTube's exact comma-separated budget."""
    out = []
    for tag in tags:
        tag = _cut_words(_clean(tag, 200), 45).lower().strip(" ,.-")  # never cut mid-word ("...availab")
        if len(tag) < 3 or tag in out:
            continue
        candidate = out + [tag]
        # The Data API counts spaces inside a tag as two characters and also
        # counts the commas separating tags.
        api_chars = sum(len(t) + t.count(" ") for t in candidate) + max(0, len(candidate) - 1)
        if api_chars <= limit:
            out.append(tag)
    return out


def _title_head(text: str) -> str:
    """The searchable head of a title: the part before '|' or a dash aside ('… | What to Check' -> '…')."""
    return re.split(r"\s+[|—–]\s+|\s*\|\s*", str(text or ""))[0].strip()


def _ranked_tags(meta: dict, title: str, packaging: dict, channel: ChannelProfile = SONIA) -> list[str]:
    """Build broad but truthful query coverage, ordered strongest-first."""
    candidates = [
        meta.get("primary_query", ""),
        _title_head(title),
        *meta.get("tags", []),
        *meta.get("secondary_queries", []),
        # Titles are sentences; only their heads are queries ('… | 8' and '… — is this' were tags on 2026-10-06).
        *[_title_head(packaging.get(k, "")) for k in ("title_a_searchable", "title_b_intriguing", "title_c_hybrid")],
        channel.display_name.lower(),
    ]
    return _valid_tags([t for t in candidates if isinstance(t, str) and t.strip()])


def metadata_from_model(record: dict, packaging: dict, llm: LLM | None,
                        channel: ChannelProfile = SONIA) -> tuple[dict, str]:
    """Wording that has to be written fresh: intro, tags, queries, hashtags, destination, thumbnail hooks."""
    # An English video (a story from outside India) gets English searches and an English pinned comment.
    english = str(record.get("language") or (channel.default_audio_language if channel != SONIA else "")).lower() == "en"
    searches = "natural English searches" if english else "natural Hindi/Hinglish searches"
    comment_language = "English" if english else "Hinglish"
    title = record.get("video_title") or ""
    fallback_words = [w for w in re.findall(r"[A-Za-z]{4,}", _title_head(title))
                      if w.lower() not in {"what", "this", "that", "with", "from", "your", "before", "check", "need"}][:6]
    fallback_hashes = fallback_hashtags(title, channel)
    fallback = {
        "destination": "", "intro": [packaging.get("core_promise") or title,
                                     "Watch for the practical context, key distinctions, and the details worth checking before you plan."],
        "description_points": [],
        "tags": [_cut_words(_title_head(title).lower(), 45)] + [w.lower() for w in fallback_words] + [channel.display_name.lower()],
        "primary_query": title.split("|")[0].strip(), "secondary_queries": [],
        "hashtags": fallback_hashes[:3], "comment": "",
        "thumbnail_variants": [],
    }
    if channel != SONIA:
        fallback["intro"][1] = "Explore the evidence, the key distinctions and the questions still open in this video."
    if not llm:
        return fallback, "fallback"
    corpus = " ".join([title, packaging.get("core_promise", ""), packaging.get("audience", ""),
                       packaging.get("thumbnail_concept_a", ""), packaging.get("thumbnail_concept_b", ""),
                       str(record.get("claim_ledger", ""))[:3000]])
    identity = ("You write YouTube metadata for the travel channel Sonia Travel Vlogs, for Indian viewers. "
                if channel == SONIA else
                f"You write YouTube metadata for {channel.display_name}, a {channel.topic} channel for {channel.audience}. ")
    tag_direction = ("characters; mix exact topic, long-tail Indian traveller intent, destination/year, acronyms and full "
                     if channel == SONIA else "characters; mix exact topic, relevant viewer questions, acronyms and full ")
    variant_direction = (
        "(exactly 3 objects with keys name, left_usp (one concrete hero visual idea, no text), sonia_expression "
        "(2 to 3 words), text (a 1 to 3 word hook in capitals using only words found in the title or brief). "
        "Prefer zero or very little text: the visual must communicate the story before the words do. Do not use "
        "generic hooks such as WHAT'S NEW, BIG UPDATE or MUST WATCH when a topic-specific place, number or change "
        "is available)."
        if channel.thumbnail_mode == "portrait" else
        "(exactly 3 objects with keys name, left_usp (one truthful focal visual, no portrait), "
        "text (a 2 to 4 word hook in capitals using only words found in the title or brief)).")
    try:
        out = llm(
            identity + "Use ONLY facts "
            "present in the input; never add dates, prices, rules or places that are not there. Return JSON with keys: "
            "destination (string, the place the video is about), intro (array of exactly 2 short paragraphs, plain "
            "English; first paragraph is a specific search-friendly hook and viewer promise, second creates curiosity "
            "and explains the practical payoff; do not put disclaimers in either paragraph), description_points "
            "(array of 4 to 6 short viewer-facing takeaways that "
            "truthfully describe what the video answers; naturally use relevant search language without repeating "
            "the same keyword), tags (20 to 30 highly relevant lowercase search phrases, each under 45 "
            + tag_direction
            + f"forms, {searches}, and only likely misspellings; never use unrelated trending "
            "terms, competitor names or claims absent from the input), "
            "primary_query (the one search phrase people type), secondary_queries (4 to 6 phrases), hashtags (exactly "
            "3, each starting with #, no spaces), comment (one engaging question for a pinned comment, in simple "
            f"{comment_language}, ends with a reminder to verify official sources if the video states rules), thumbnail_variants "
            + variant_direction,
            {"video_title": title, "audience": packaging.get("audience"), "core_promise": packaging.get("core_promise"),
               "thumbnail_concept_a": packaging.get("thumbnail_concept_a"),
               "thumbnail_concept_b": packaging.get("thumbnail_concept_b"), "claims": str(record.get("claim_ledger", ""))[:3000]})
    except Exception:  # noqa: BLE001
        return fallback, "fallback"
    result = dict(fallback)
    dest = _clean(out.get("destination", ""), 40)
    if dest:
        result["destination"] = dest
    intro = [_clean(p, 600) for p in out.get("intro", []) if isinstance(p, str)]
    if len(intro) == 2 and all(len(p) > 30 for p in intro):
        result["intro"] = intro
    points = [_clean(p, 140) for p in out.get("description_points", []) if isinstance(p, str) and p.strip()]
    if 4 <= len(points) <= 6:
        result["description_points"] = points
    tags = _valid_tags([t for t in out.get("tags", []) if isinstance(t, str)])
    if len(tags) >= 5:
        result["tags"] = tags
    for key, limit in (("primary_query", 80), ("comment", 300)):
        if isinstance(out.get(key), str) and out[key].strip():
            result[key] = _clean(out[key], limit)
    queries = [_clean(q, 80) for q in out.get("secondary_queries", []) if isinstance(q, str) and q.strip()]
    if queries:
        result["secondary_queries"] = queries[:6]
    tags_h = [h for h in out.get("hashtags", []) if isinstance(h, str) and re.fullmatch(r"#\w{2,30}", h)]
    if len(tags_h) == 3:
        result["hashtags"] = tags_h
    allowed = _words(corpus) | _HOOK_OK
    variants = []
    for v in out.get("thumbnail_variants", []):
        text = _clean((v or {}).get("text", ""), 28).upper()
        words = text.split()
        if ((v or {}).get("left_usp") and 1 <= len(words) <= 3 and _words(text) <= allowed
                and text not in _GENERIC_THUMBNAIL_HOOKS):
            variants.append({"name": _clean(v.get("name", "Variant"), 30), "left_usp": _clean(v["left_usp"], 160),
                             "sonia_expression": _clean(v.get("sonia_expression", "curious"), 40), "text": text})
    if len(variants) >= 1:
        result["thumbnail_variants"] = variants[:3]
    return result, "model"


def description_audit(description: str, primary_query: str, tags: list[str],
                      channel: ChannelProfile = SONIA) -> dict[str, Any]:
    """Mechanical metadata checks that ARES can enforce before upload.

    This is not a prediction of views. It covers YouTube's description guidance
    and the controllable portion of vidIQ's SEO checklist without keyword
    stuffing or inventing search volume.
    """
    first_200 = description[:200].casefold()
    query = " ".join(primary_query.casefold().split())
    chapter_count = len(re.findall(r"(?m)^\d{1,2}:\d{2}\s+", description))
    tag_chars = sum(len(tag) + tag.count(" ") for tag in tags) + max(0, len(tags) - 1)
    checks = {
        "unique_description_over_300_chars": len(description) >= 300,
        "primary_query_in_first_200_chars": bool(query and query in first_200),
        "viewer_payoff_before_fold": "this video" in first_200 or "you'll" in first_200 or "you will" in first_200,
        "chapters_present": chapter_count >= 3 and bool(re.search(r"(?m)^0:00\s+", description)),
        "search_grouped_chapters": 3 <= chapter_count <= 8,
        "official_sources_present": "OFFICIAL SOURCES\n" in description,
        "related_playlist_present": not channel.playlist_url or channel.playlist_url in description,
        "subscribe_link_present": not channel.subscribe_url or channel.subscribe_url in description,
        "three_hashtags": len(re.findall(r"(?<!\w)#\w+", description)) == 3,
        "five_or_more_tags": len(tags) >= 5,
        "tag_budget_over_200_chars": tag_chars >= 200,
    }
    return {"ok": all(checks.values()), "checks": checks, "chapter_count": chapter_count,
            "description_chars": len(description), "tag_budget_chars": tag_chars,
            "note": "Metadata readiness only; views still depend on topic, thumbnail, title, retention and audience response."}


THUMBNAIL_PROMPT = (
    "Create a high-CTR, mobile-first YouTube travel thumbnail background for Sonia Travel Vlogs. Use the attached "
    "approved Sonia portrait as the only human subject and preserve her real identity, facial structure and skin "
    "tone. Softly remove only temporary acne/blemishes while preserving natural pores, permanent marks and every "
    "identity feature; never airbrush, reshape, age-shift or retouch her into someone else. Do not copy "
    "another creator's exact branding.\n\nSTORY: {video_title}\nDESTINATION: {destination}\nTRUTHFUL VISUAL: "
    "{left_usp}\nSONIA EXPRESSION: {sonia_expression}\n\nCOMPOSITION: 16:9. Sonia as a large close-up on the RIGHT, "
    "32 to 34 percent of the frame, eyes unobstructed, clean shoulder cutout, natural high-energy expression. Use "
    "three strict zones: LEFT 0-38 percent is a low-detail, high-contrast hook zone; CENTRE 38-66 percent contains "
    "one large, unobstructed hero proof of the story ({left_usp}); RIGHT 66-100 percent contains Sonia. The hero "
    "proof must remain fully recognizable at phone size and must not sit behind the future hook text or Sonia. "
    "Use one dominant background and at most one supporting cue. No collage, no secondary people, no tiny objects, "
    "no repeated landmarks, no decorative clutter. The image must tell one visual sentence before any text is added.\n\n"
    "LIGHTING HIERARCHY: give the cleanest key light and strongest local contrast to exactly three things: Sonia's "
    "face, the primary story object ({left_usp}), and the recognizable {destination} landmark. Keep sky, streets, "
    "water, terminal and other scenery about one stop dimmer and slightly less saturated so they remain contextual, "
    "not competitive. Use balanced early-evening exposure, one controlled red or yellow cue, a restrained soft rim "
    "light around Sonia, crisp eyes and natural skin. Never place a sun disc, blown highlight, orange flare or bright "
    "halo directly behind Sonia's face or hair; never fake spotlight beams or glowing outlines.\n\nTEXT: "
    "Do not render any text inside the image. Keep the LOWER-LEFT portion of the LEFT 0-38 percent clean and "
    "low-detail for this later overlay: {thumbnail_text}. Never place the destination landmark, aircraft, document, "
    "main story object or other USP inside that lower-left text-safe area.\n\n"
    "EVIDENCE SAFETY: do not fabricate a visa, passport stamp, government seal, amount, date or document text, and "
    "do not imply Sonia personally visited {destination}.\n\nTECHNICAL: 1280x720 composition, ultra-sharp focal "
    "subject, no watermark, no logo, no border, no small text, no distorted hands or faces, keep the bottom-right "
    "timestamp zone free. Output one polished thumbnail background for final text compositing."
)


ORIGINAL_THUMBNAIL_PROMPT = (
    "Generate a brand-new 16:9 YouTube thumbnail background from this text brief only. "
    "This is a fresh text-to-image request, not an image edit: no reference image is expected or required. "
    "Do not invoke a reference-image, portrait, face-swap, or image-edit workflow. "
    "STORY: {video_title}\nSUBJECT: {destination}\nTRUTHFUL VISUAL: {left_usp}\n"
    "One dominant subject on the right, clear space on the left for later text: {thumbnail_text}. "
    "Do not render text, logos or watermarks. Do not present an artist concept as a real observation "
    "or fabricate evidence. Cinematic lighting, strong contrast, readable at small sizes, 1280x720."
)


# Title and description language on YouTube: "English (United States)", not plain "English".
METADATA_LANGUAGE = "en-US"
PAYOFF = re.compile(r"this video|you'll|you will", re.I)
# Hosts that aggregate or re-host a story are not "official sources".
_NOT_OFFICIAL = re.compile(r"news\.google\.|youtube\.com|youtu\.be|bing\.com|facebook\.com|instagram\.com|x\.com/|twitter\.com",
                           re.I)


def _plain(text: str) -> str:
    """Model prose without Markdown: the 2026-10-13 Singapore description shipped **bold** asterisks."""
    text = re.sub(r"(\*\*|__|\*|`)", "", str(text))
    return re.sub(r"^\s*#+\s*", "", text).strip()


def official_source_urls(record: dict[str, Any], limit: int = 8) -> list[str]:
    """The official pages the plan itself names: the claim ledger, then the scene plan and browser-capture plan.

    Only the claim ledger used to be read. On 2026-10-13 Singapore's ledger listed what was verified without links,
    while the Firefly, Changi, ICA and Malaysia Airlines pages sat in scene_plan and browser_capture_plan, so the
    description lost its OFFICIAL SOURCES section (while still telling viewers to "verify the official sources
    above") and the upload gate blocked the video."""
    found: list[str] = []
    seen: set[str] = set()
    for key in ("claim_ledger", "scene_plan", "browser_capture_plan"):
        value = record.get(key, "")
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        for url in _URL.findall(text):
            url = url.rstrip(".,;'\"}{]")
            norm = re.sub(r"^https?://(www\.)?", "", url).rstrip("/").lower()
            if _NOT_OFFICIAL.search(url) or norm in seen:
                continue
            seen.add(norm)
            found.append(url)
    return found[:limit]


def build_package(record: dict[str, Any], *, master: Path, plan_path: Path, portrait_library: Path | None = None,
                  llm: LLM | None = ollama_json, channel: ChannelProfile = SONIA) -> dict[str, Any]:
    """Build with one shared implementation and explicit per-channel identity.

    Omitted channel preserves the Sonia contract. An explicitly different brand
    never falls through to Sonia's portrait, playlist or subscribe links.
    """
    channel.validate_record(record)
    if channel.thumbnail_mode == "portrait" and portrait_library is None:
        raise ValueError("Portrait channels require their own approved portrait library")
    if channel.thumbnail_mode == "original" and portrait_library is not None:
        raise ValueError("Original-image channels must not receive a portrait library")
    english = str(record.get("language") or (channel.default_audio_language if channel != SONIA else "")).lower() == "en"
    # English is sent as en-US (the Chairman, 2026-10-13: "English (United States)" over plain "English" gives
    # viewers outside India a better chance of being shown the video). Hindi audio stays "hi".
    spoken = channel.metadata_language if english else ("hi" if channel == SONIA else channel.default_audio_language)
    packaging = parse_packaging(record.get("packaging", ""))
    title = clean_title(record.get("video_title") or packaging.get("recommended_title", ""))
    if not title:
        raise RuntimeError("The production plan has no video_title to build an SEO package from")
    cues = script_cues(record.get("full_script", ""))
    # Chapter times come from the recorded voice when it matches the script scene for scene.
    starts = narration_timeline(plan_path)
    timing = "script"
    if starts and len(starts) == len(cues):
        cues = [(int(t // 60), int(t % 60), cues[i][2]) for i, t in enumerate(starts)]
        timing = "narration"
    meta, meta_source = metadata_from_model(record, packaging, llm, channel)
    search_terms = [meta.get("primary_query", ""), *meta.get("secondary_queries", []),
                    *meta.get("tags", []), title]
    chapter_plan, label_source = chapter_labels(
        cues, scene_screen_texts(record.get("scene_plan", "")), title, llm, search_terms, topic=channel.topic)

    chapters = [f"{cues[i][0]}:{cues[i][1]:02d} {label}" for i, label in chapter_plan]
    if not chapters or not chapters[0].startswith("0:00 "):
        chapters.insert(0, f"0:00 {chapter_plan[0][1] if chapter_plan else 'Introduction'}" if cues else "0:00 Introduction")
    urls = official_source_urls(record)
    original = bool(record.get("original_footage_required"))
    primary_query = _clean(meta["primary_query"] or _title_head(title), 80)
    # Put the exact natural search phrase before the mobile fold. vidIQ's
    # controllable checklist looks for tag/query overlap in the first 200
    # characters; YouTube likewise recommends prominent 1-2 main terms.
    intro = [_plain(p) for p in meta["intro"]]
    points = [_plain(p) for p in meta["description_points"]]
    opening = f"{primary_query.capitalize()}: {intro[0]}"
    if not PAYOFF.search(opening[:200]):
        # The audit (and a viewer deciding whether to watch) needs the payoff before the fold; on 2026-10-13 the
        # model's intro had none, and the Singapore upload was blocked for it.
        opening = (f"{primary_query.capitalize()}: in this video you'll learn what changed and what to check "
                   f"{'before you travel' if channel == SONIA else 'about this topic'}. {intro[0]}")
    description = "\n\n".join(filter(None, [
        opening, intro[1],
        ("IN THIS VIDEO\n" + "\n".join(f"- {p}" for p in points)) if points else "",
        "CHAPTERS\n" + "\n".join(chapters),
        ("OFFICIAL SOURCES\n" + "\n".join(f"- {u}" for u in urls[:8])) if urls else "",
        ("IMPORTANT\nTravel rules, prices, schedules and breaking-news details can change. "
         f"Verify the official sources{' above' if urls else ''} for your dates before acting."
         if channel == SONIA else "IMPORTANT\n" + channel.source_note),
        f"{channel.playlist_heading}\n{channel.playlist_url}" if channel.playlist_url else "",
        f"SUBSCRIBE TO {channel.display_name.upper()}\n{channel.subscribe_url}" if channel.subscribe_url else "",
        " ".join(meta["hashtags"]),
        channel.share_note,
    ]))[:5000]

    secondary = meta["secondary_queries"]
    variants = meta["thumbnail_variants"] or [
        {"name": "Primary", "left_usp": packaging.get("thumbnail_concept_a") or f"Recognisable view of {meta['destination'] or 'the destination'}",
         "sonia_expression": "curious", "text": ""}]
    # A variant with no hook text is not a thumbnail; fall back to the first words of the title.
    for v in variants:
        v["text"] = v["text"] or " ".join(title.split("|")[0].upper().split()[:3])
    destination = meta["destination"] or title.split("|")[0].strip()
    # Styling is a reviewed operator request, not something the SEO model may infer. In particular the premium
    # black dual-colour treatment is opt-in so consecutive videos do not silently converge on the same template.
    requested_thumbnail_style = str(record.get("thumbnail_style") or "").strip()
    title_variants = [t for t in dict.fromkeys(
        [title] + [packaging.get(k, "") for k in ("title_a_searchable", "title_b_intriguing", "title_c_hybrid")]) if t][:4]

    ranked_tags = _ranked_tags(meta, title, packaging, channel)
    if channel.thumbnail_mode == "original":
        variants = [{k: v for k, v in row.items() if k != "sonia_expression"} for row in variants]
    return {
        "schema_version": "1.1", "owner": "ARES" if channel == SONIA else "LYRA", "brand": channel.brand,
        "handoff": "IRIS -> ARES -> IRIS upload gate" if channel == SONIA else "HELIOS -> LYRA -> ECHO approval gate", "master": str(master),
        "recommended_title": title, "title_variants": title_variants,
        "primary_query": primary_query, "secondary_queries": secondary,
        "description": description, "description_audit": description_audit(description, primary_query, ranked_tags, channel),
        "chapters": chapters, "tags": ranked_tags,
        "destination": destination,
        "thumbnail": {
            "owner": "ARES" if channel == SONIA else "LYRA", "generator": "chatgpt_image_generation",
            "generation_mode": f"edit approved {channel.display_name if channel != SONIA else 'Sonia'} portrait; preserve identity" if channel.thumbnail_mode == "portrait" else "original image; no portrait reference",
            **({"portrait_library": str(portrait_library)} if channel.thumbnail_mode == "portrait" else {}),
            "required_layout": f"{channel.display_name if channel != SONIA else 'Sonia'} close-up on right 32-34%; hook on left 0-38%; unobstructed story USP in centre 38-66%" if channel.thumbnail_mode == "portrait" else "One truthful focal subject on right; clear text area on left",
            "text": variants[0]["text"], "max_words": 3, "variants": variants,
            **({"requested_style": requested_thumbnail_style} if requested_thumbnail_style else {}),
            "quality_gates": ["1280x720", "16:9", "under 2 MB export", "recognizable at 10% size",
                              "text readable at mobile size", *(["face intact"] if channel.thumbnail_mode == "portrait" else ["no portrait reference", "truthful illustration"])],
            "chatgpt_prompt_template": (THUMBNAIL_PROMPT.replace("Sonia Travel Vlogs", channel.display_name).replace("Sonia", channel.display_name)
                                       if channel != SONIA else THUMBNAIL_PROMPT) if channel.thumbnail_mode == "portrait" else ORIGINAL_THUMBNAIL_PROMPT,
        },
        "upload": {"privacyStatus": "private", "categoryId": channel.category_id, "defaultLanguage": channel.metadata_language, "defaultAudioLanguage": spoken,
                   "embeddable": True, "license": "youtube", "publicStatsViewable": True,
                   "selfDeclaredMadeForKids": False, "containsSyntheticMedia": "HUMAN_REVIEW_REQUIRED"},
        "playlist_id": channel.playlist_id,
        # English remains the source language, while Hindi metadata gives the
        # channel's Indian audience a discoverable localized title/description.
        # Every video, English ones included, gets the 14 metadata locales: the video stays English, but its title and
        # description reach viewers in their own language (the Chairman, 2026-10-13, on Singapore showing only Hindi).
        "localizations_required": list(channel.locales),
        "pinned_comment_draft": meta["comment"] or (channel.comment if channel != SONIA else (
            "When are you planning to travel? Please re-check the official sources for your dates." if english else
            "Aap kab travel plan kar rahe hain? Official sources apni date ke liye dobara verify zaroor karein.")),
        "language": "en" if english else "hinglish",
        "source_plan": str(plan_path), "volatile_claims_require_same_day_recheck": True,
        "keyword_stuffing_allowed": False, "public_publish_authorized": False,
        "generation": {"chapters": label_source, "chapter_timing": timing, "metadata": meta_source, "models": local_llm.ladder("short") if llm is ollama_json else None},
    }
