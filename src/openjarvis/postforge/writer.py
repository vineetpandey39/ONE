# ruff: noqa: E501
"""Turning verified sources into a post, without spending a cloud credit.

PostForge asked Anthropic for a JSON object. A floor run may not, so the copy
here comes from the same local-only synthesis every floor head already uses
(``runtime._research_synthesis`` -> Sanjeevani's Ollama call). Two changes fall
out of that:

* **Markers, not JSON.** A 9B local model emits ``KEY: value`` lines reliably
  and nested JSON unreliably. The repo already reads that shape with
  ``runtime._marker``, and the JSON the cockpit receives is assembled in Python.
* **Sources are attached by code.** The model never writes a source name or URL;
  each slide is bound to one of the selected verified items after the fact. That
  removes the single failure PostForge's prompt spent the most words fighting --
  an invented citation -- instead of asking the model not to do it.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Sequence

from openjarvis.postforge.feed import pillar_by_id, require_verified

FORMATS: tuple[str, ...] = ("Carousel", "Reel Script", "Story Hook", "Caption Only")

SLIDE_ROLES: tuple[tuple[str, str], ...] = (
    ("problem", "name the pain, risk or hidden shift this creates"),
    (
        "proof",
        "one verified fact, number or date from the sources that proves it is real",
    ),
    ("reveal", "the mechanism nobody noticed -- why this actually matters"),
    ("solution", "the exact move a creator or builder should make now"),
    ("closure", "close the open loop and earn the save/follow"),
)

REEL_BEATS: tuple[tuple[str, str], ...] = (
    ("0-2s", "pattern interrupt"),
    ("2-6s", "context"),
    ("6-12s", "proof"),
    ("12-20s", "meaning"),
    ("20-30s", "creator move"),
    ("30-35s", "save CTA"),
)

STORY_FRAMES: tuple[tuple[str, str], ...] = (
    ("hook", "stop the tap-through"),
    ("context", "what happened, in one line"),
    ("value", "why it matters to the viewer"),
    ("cta", "poll or question sticker + follow"),
)

PILLAR_FOCUS: dict[str, str] = {
    "news": "Explain why the update matters to creators and AI income builders. Be urgent without exaggerating.",
    "tool": "Focus on practical use cases, time saved, cost saved, and how to start.",
    "income": "Use only the numbers in the sources. Invent no earnings, averages or timelines.",
    "transformation": "Focus on the identity shift and the practical behaviour change. No invented statistics.",
    "automation": "Focus on exact workflow steps, the tools involved, and realistic time savings from the source.",
}

HANDLE = "@aibyvineet"

_FALLBACK_HASHTAGS: dict[str, tuple[str, ...]] = {
    "news": ("#ainews", "#aitools", "#technews", "#aiforcreators", "#futureofwork"),
    "tool": (
        "#aitools",
        "#aiautomation",
        "#productivitytools",
        "#creatorstack",
        "#buildinpublic",
    ),
    "income": (
        "#aiincome",
        "#creatorbusiness",
        "#digitalincome",
        "#sidehustleideas",
        "#aiforcreators",
    ),
    "transformation": (
        "#aiforcreators",
        "#futureofwork",
        "#creatormindset",
        "#worksmart",
        "#digitalcreator",
    ),
    "automation": (
        "#aiautomation",
        "#workflowautomation",
        "#nocodetools",
        "#creatorstack",
        "#aitools",
    ),
}

Synthesizer = Callable[..., tuple[str, str]]


class GenerationBlocked(RuntimeError):
    """Raised when local synthesis cannot produce the post honestly."""


def _marker(text: str, key: str, default: str = "") -> str:
    from openjarvis.one_agents.runtime import _marker as runtime_marker

    return runtime_marker(text, key, default)


def _default_synth(prompt: str, max_tokens: int = 2200) -> tuple[str, str]:
    from openjarvis.one_agents.runtime import _research_synthesis

    return _research_synthesis(prompt, max_tokens=max_tokens)


def source_context(items: Sequence[dict[str, Any]]) -> str:
    lines = []
    for index, item in enumerate(items, start=1):
        lines.append(
            f"{index}. {item.get('headline', '')}\n"
            f"   Source: {item.get('source', '')}\n"
            f"   Published: {item.get('publishedAt') or item.get('date', '')}\n"
            f"   URL: {item.get('url', '')}\n"
            f"   Summary: {item.get('summary', '')}"
        )
    return "\n".join(lines)


def normalize_hashtags(value: Any, pillar: str) -> str:
    """Exactly five tags: whatever the model gave, topped up from the pillar set."""
    found = [tag.lower() for tag in re.findall(r"#[A-Za-z0-9_]+", str(value or ""))]
    unique = list(dict.fromkeys(found))
    fallback = _FALLBACK_HASHTAGS.get(pillar, _FALLBACK_HASHTAGS["news"])
    unique.extend(tag for tag in fallback if tag not in unique)
    return " ".join(unique[:5])


def _cite(items: Sequence[dict[str, Any]], index: int) -> dict[str, str]:
    """Bind slide ``index`` to a real selected item, cycling when there are fewer."""
    if not items:
        return {"source": "", "source_url": ""}
    item = items[index % len(items)]
    return {
        "source": str(item.get("source") or ""),
        "source_url": str(item.get("url") or ""),
    }


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_RULES = f"""Hard rules:
- Use ONLY the verified sources below. Never invent a product name, number, price, date or claim.
- Never write a source name or a URL yourself; they are attached afterwards.
- Image text stays short: a headline is 2-5 words, a subline is under 5 words.
- Every image ends with {HANDLE} at the bottom.
- Answer ONLY with the KEY: value lines asked for, one per line, nothing else."""


def carousel_prompt(pillar: str, items: Sequence[dict[str, Any]]) -> str:
    slides = "\n".join(
        f"SLIDE{index}_HEADLINE: 2-5 words, all caps, for the {role} slide\n"
        f"SLIDE{index}_SUBLINE: under 5 words\n"
        f"SLIDE{index}_BODY: 14-24 words that {brief}\n"
        f"SLIDE{index}_VISUAL: one sentence naming the exact company, product and event this slide shows"
        for index, (role, brief) in enumerate(SLIDE_ROLES, start=1)
    )
    return f"""You are a factual Instagram strategist writing a 6-image carousel for {HANDLE}.

Pillar: {pillar_by_id(pillar)["full"]}
Focus: {PILLAR_FOCUS.get(pillar, "")}

The arc: the cover opens a loop without revealing the news, then problem, proof,
reveal, solution, and a closure slide that earns the save.

{_RULES}

Verified sources:
{source_context(items)}

Return exactly these lines:
HOOK: max 12 words
COVER_TEXT: 3-7 words, all caps, extreme curiosity hook that does not reveal the news
COVER_SUBTEXT: max 4 words
COVER_VISUAL: one sentence describing a cinematic visual metaphor for the cover
{slides}
CAPTION: under 150 characters
CTA: one line
CANVA_BRIEF: one visual direction sentence
HASHTAGS: exactly 5 Instagram hashtags, space separated
HASHTAG_STRATEGY: one sentence on why these five fit"""


def reel_prompt(pillar: str, items: Sequence[dict[str, Any]]) -> str:
    beats = "\n".join(
        f"SEG{index}_TEXT: 3-7 words on screen for the {beat} beat at {stamp}\n"
        f"SEG{index}_VO: the exact voiceover words for {stamp}\n"
        f"SEG{index}_VISUAL: faceless visual direction for {stamp}"
        for index, (stamp, beat) in enumerate(REEL_BEATS, start=1)
    )
    return f"""You are writing a faceless 22-35 second Instagram Reel script for {HANDLE}.

Pillar: {pillar_by_id(pillar)["full"]}
Focus: {PILLAR_FOCUS.get(pillar, "")}

Open on the consequence, never on "today we are talking about". Cuts every 2-4
seconds. B-roll is AI-generated: UI mockups, proof cards, kinetic text, charts.

{_RULES}

Verified sources:
{source_context(items)}

Return exactly these lines:
HOOK: max 10 words, frame-one retention hook
REEL_ANGLE: one sentence on why this matters now
COLD_OPEN: the exact first frame
{beats}
CAPTION: under 150 characters
CTA: one line
MUSIC: an audio mood, not a copyrighted song title
HASHTAGS: exactly 5 Instagram hashtags, space separated
HASHTAG_STRATEGY: one sentence on why these five fit"""


def story_prompt(pillar: str, items: Sequence[dict[str, Any]]) -> str:
    frames = "\n".join(
        f"FRAME{index}_TEXT: the text overlay for the {kind} frame ({brief})\n"
        f"FRAME{index}_STICKER: a poll or question sticker idea\n"
        f"FRAME{index}_VISUAL: the visual direction"
        for index, (kind, brief) in enumerate(STORY_FRAMES, start=1)
    )
    return f"""You are writing a 4-frame Instagram Story sequence for {HANDLE}.

Pillar: {pillar_by_id(pillar)["full"]}
Focus: {PILLAR_FOCUS.get(pillar, "")}

{_RULES}

Verified sources:
{source_context(items)}

Return exactly these lines:
HOOK: max 12 words
{frames}
CAPTION: under 150 characters
CTA: one line
HASHTAGS: exactly 5 Instagram hashtags, space separated
HASHTAG_STRATEGY: one sentence on why these five fit"""


def caption_prompt(pillar: str, items: Sequence[dict[str, Any]]) -> str:
    return f"""You are writing one standalone Instagram caption for {HANDLE}. No slides, no script.

Pillar: {pillar_by_id(pillar)["full"]}
Focus: {PILLAR_FOCUS.get(pillar, "")}

{_RULES}

Verified sources:
{source_context(items)}

Return exactly these lines:
HOOK: max 12 words
CAPTION_BODY: 400-600 characters
CAPTION: the complete caption
CTA: one line
CANVA_BRIEF: single image direction
HASHTAGS: exactly 5 Instagram hashtags, space separated
HASHTAG_STRATEGY: one sentence on why these five fit"""


PROMPTS: dict[str, Callable[[str, Sequence[dict[str, Any]]], str]] = {
    "Carousel": carousel_prompt,
    "Reel Script": reel_prompt,
    "Story Hook": story_prompt,
    "Caption Only": caption_prompt,
}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_carousel(text: str, items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    slides = []
    for index, (role, _brief) in enumerate(SLIDE_ROLES, start=1):
        headline = _marker(text, f"SLIDE{index}_HEADLINE")
        body = _marker(text, f"SLIDE{index}_BODY")
        visual = _marker(text, f"SLIDE{index}_VISUAL")
        slides.append(
            {
                "role": role,
                "title": headline.title() if headline else role.title(),
                "body": body,
                "image_body_text": body,
                "slide_headline": headline.upper(),
                "slide_subline": _marker(text, f"SLIDE{index}_SUBLINE"),
                "slide_stat": "",
                "visual_prompt": visual,
                "content_brief": visual,
                **_cite(items, index - 1),
            }
        )
    return {
        "hook": _marker(text, "HOOK"),
        "cover_text": _marker(text, "COVER_TEXT").upper(),
        "cover_subtext": _marker(text, "COVER_SUBTEXT"),
        "cover_visual_prompt": _marker(text, "COVER_VISUAL"),
        "slides": slides,
        "caption": _marker(text, "CAPTION"),
        "cta": _marker(text, "CTA"),
        "canva_brief": _marker(text, "CANVA_BRIEF"),
        "hashtag_strategy": _marker(text, "HASHTAG_STRATEGY"),
        "hashtags": _marker(text, "HASHTAGS"),
    }


def parse_reel(text: str, items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    segments = []
    for index, (stamp, beat) in enumerate(REEL_BEATS, start=1):
        segments.append(
            {
                "timestamp": stamp,
                "beat": beat,
                "on_screen_text": _marker(text, f"SEG{index}_TEXT"),
                "voiceover": _marker(text, f"SEG{index}_VO"),
                "visual": _marker(text, f"SEG{index}_VISUAL"),
                "edit_note": "hard cut on the beat",
                **_cite(items, index - 1),
            }
        )
    return {
        "hook": _marker(text, "HOOK"),
        "reel_angle": _marker(text, "REEL_ANGLE"),
        "cold_open_visual": _marker(text, "COLD_OPEN"),
        "script_segments": segments,
        "shot_list": [segment["visual"] for segment in segments if segment["visual"]],
        "caption": _marker(text, "CAPTION"),
        "cta": _marker(text, "CTA"),
        "music_suggestion": _marker(text, "MUSIC"),
        "hashtag_strategy": _marker(text, "HASHTAG_STRATEGY"),
        "hashtags": _marker(text, "HASHTAGS"),
    }


def parse_story(text: str, items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    stories = []
    for index, (kind, _brief) in enumerate(STORY_FRAMES, start=1):
        stories.append(
            {
                "story_number": index,
                "type": kind,
                "text_overlay": _marker(text, f"FRAME{index}_TEXT"),
                "sticker_suggestion": _marker(text, f"FRAME{index}_STICKER"),
                "visual_direction": _marker(text, f"FRAME{index}_VISUAL"),
                **_cite(items, index - 1),
            }
        )
    return {
        "hook": _marker(text, "HOOK"),
        "stories": stories,
        "caption": _marker(text, "CAPTION"),
        "cta": _marker(text, "CTA"),
        "hashtag_strategy": _marker(text, "HASHTAG_STRATEGY"),
        "hashtags": _marker(text, "HASHTAGS"),
    }


def parse_caption(text: str, items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "hook": _marker(text, "HOOK"),
        "caption_body": _marker(text, "CAPTION_BODY"),
        "caption": _marker(text, "CAPTION") or _marker(text, "CAPTION_BODY"),
        "cta": _marker(text, "CTA"),
        "canva_brief": _marker(text, "CANVA_BRIEF"),
        "hashtag_strategy": _marker(text, "HASHTAG_STRATEGY"),
        "hashtags": _marker(text, "HASHTAGS"),
        **_cite(items, 0),
    }


PARSERS: dict[str, Callable[[str, Sequence[dict[str, Any]]], dict[str, Any]]] = {
    "Carousel": parse_carousel,
    "Reel Script": parse_reel,
    "Story Hook": parse_story,
    "Caption Only": parse_caption,
}

#: The fields a post is useless without, per format.
_REQUIRED: dict[str, tuple[str, ...]] = {
    "Carousel": ("hook", "cover_text", "caption"),
    "Reel Script": ("hook", "caption"),
    "Story Hook": ("hook", "caption"),
    "Caption Only": ("hook", "caption"),
}


def generate(
    pillar: str = "news",
    fmt: str = "Carousel",
    items: Sequence[dict[str, Any]] | None = None,
    *,
    synth: Synthesizer | None = None,
    max_tokens: int = 2200,
) -> dict[str, Any]:
    """One post plan from verified sources, written locally.

    ``synth`` is injectable for tests; it defaults to the local-only research
    path, which refuses to buy a cloud answer when Ollama is unavailable.
    """
    if fmt not in PROMPTS:
        raise KeyError(f"Unknown format: {fmt!r}")
    selected = require_verified(list(items or []))

    prompt = PROMPTS[fmt](pillar, selected)
    text, note = (synth or _default_synth)(prompt, max_tokens=max_tokens)
    if not text:
        raise GenerationBlocked(note or "Local synthesis returned nothing")

    parsed = PARSERS[fmt](text, selected)
    missing = [field for field in _REQUIRED[fmt] if not parsed.get(field)]
    if missing:
        raise GenerationBlocked(
            f"Local synthesis left {', '.join(missing)} empty; refusing to ship a half-written post"
        )

    parsed["hashtags"] = normalize_hashtags(parsed.get("hashtags"), pillar)
    parsed["handle"] = HANDLE
    parsed["_format"] = fmt
    parsed["_pillar"] = pillar
    parsed["_researcher"] = "sanjeevani+local"
    parsed["_verified_sources"] = [
        {
            "source": item.get("source", ""),
            "headline": item.get("headline", ""),
            "url": item.get("url", ""),
            "date": item.get("publishedAt") or item.get("date", ""),
        }
        for item in selected
    ]
    return parsed
