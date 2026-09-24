# ruff: noqa: E501
"""Generation may not invent a source, and may not ship a half-written post.

The local model is stubbed here: what is under test is the contract around it --
the freshness gate before the call, the marker parsing after it, and the fact
that citations are attached by code rather than written by the model.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from openjarvis.postforge import writer as gen

NOW = datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc)

ITEMS = [
    {
        "verified": True,
        "url": "https://www.anthropic.com/news/claude-memory",
        "source": "anthropic.com",
        "headline": "Anthropic ships Claude memory",
        "summary": "Memory arrives for Claude.",
        "publishedAt": datetime.now(timezone.utc).isoformat(),
    },
    {
        "verified": True,
        "url": "https://openai.com/index/codex-update",
        "source": "openai.com",
        "headline": "OpenAI updates Codex",
        "summary": "Codex gets longer runs.",
        "publishedAt": datetime.now(timezone.utc).isoformat(),
    },
]

CAROUSEL_OUTPUT = """
HOOK: The memory update nobody read
COVER_TEXT: THIS QUIETLY CHANGES AI
COVER_SUBTEXT: read this
COVER_VISUAL: A locked vault opening inside a glowing neural core
SLIDE1_HEADLINE: YOUR CONTEXT DIES
SLIDE1_SUBLINE: every session
SLIDE1_BODY: Most creators restart every chat from zero, losing the context that made the last answer good.
SLIDE1_VISUAL: Anthropic Claude chat window resetting to an empty thread
SLIDE2_HEADLINE: ANTHROPIC SHIPPED IT
SLIDE2_SUBLINE: today
SLIDE2_BODY: Anthropic shipped persistent memory for Claude, so a project carries its own history forward.
SLIDE2_VISUAL: Anthropic newsroom page showing the memory announcement
SLIDE3_HEADLINE: THE REAL UNLOCK
SLIDE3_SUBLINE: compounding work
SLIDE3_BODY: Memory turns one-off prompts into a system that compounds, which is where the leverage actually lives.
SLIDE3_VISUAL: Stacked layers of saved project context compounding upward
SLIDE4_HEADLINE: DO THIS TODAY
SLIDE4_SUBLINE: one project
SLIDE4_BODY: Move your highest-value workflow into one project and let the memory build across a week.
SLIDE4_VISUAL: A creator pinning one workflow into a single Claude project
SLIDE5_HEADLINE: SAVE THIS NOW
SLIDE5_SUBLINE: FOLLOW @aibyvineet
SLIDE5_BODY: Save this so the next time your context resets you know exactly what to change.
SLIDE5_VISUAL: Save icon glowing over a finished workflow board
CAPTION: Claude just got memory. Here is the part that actually matters.
CTA: Save this and follow for the next drop
CANVA_BRIEF: Dark neon vault opening into layered context cards
HASHTAGS: #ainews #claude
HASHTAG_STRATEGY: Two topical tags plus the pillar set keeps reach on AI news
"""


def _synth(output):
    def run(prompt, max_tokens=2200):
        run.prompt = prompt
        return output, ""

    return run


def test_carousel_builds_five_roled_slides_from_markers():
    plan = gen.generate("news", "Carousel", ITEMS, synth=_synth(CAROUSEL_OUTPUT))

    assert plan["cover_text"] == "THIS QUIETLY CHANGES AI"
    assert [slide["role"] for slide in plan["slides"]] == [
        "problem",
        "proof",
        "reveal",
        "solution",
        "closure",
    ]
    assert plan["slides"][1]["slide_headline"] == "ANTHROPIC SHIPPED IT"
    assert plan["_format"] == "Carousel"
    assert plan["handle"] == "@aibyvineet"


def test_citations_come_from_the_selected_items_not_the_model():
    plan = gen.generate("news", "Carousel", ITEMS, synth=_synth(CAROUSEL_OUTPUT))
    urls = {slide["source_url"] for slide in plan["slides"]}
    assert urls == {item["url"] for item in ITEMS}
    assert plan["_verified_sources"][0]["url"] == ITEMS[0]["url"]


def test_hashtags_are_topped_up_to_exactly_five():
    plan = gen.generate("news", "Carousel", ITEMS, synth=_synth(CAROUSEL_OUTPUT))
    tags = plan["hashtags"].split()
    assert len(tags) == 5
    assert tags[:2] == ["#ainews", "#claude"]
    assert len(set(tags)) == 5


def test_the_prompt_carries_the_verified_sources_into_the_model():
    synth = _synth(CAROUSEL_OUTPUT)
    gen.generate("news", "Carousel", ITEMS, synth=synth)
    assert "https://www.anthropic.com/news/claude-memory" in synth.prompt
    assert "AI News Breakdown" in synth.prompt


def test_an_empty_local_answer_blocks_instead_of_shipping_nothing():
    with pytest.raises(gen.GenerationBlocked) as error:
        gen.generate(
            "news",
            "Carousel",
            ITEMS,
            synth=lambda prompt, max_tokens=0: ("", "Ollama is down"),
        )
    assert "Ollama is down" in str(error.value)


def test_a_partial_answer_blocks_rather_than_shipping_a_half_post():
    with pytest.raises(gen.GenerationBlocked) as error:
        gen.generate(
            "news",
            "Carousel",
            ITEMS,
            synth=_synth("HOOK: something\nCOVER_TEXT: WAIT WHAT\n"),
        )
    assert "caption" in str(error.value)


def test_generation_refuses_an_unverified_selection():
    stale = [{**ITEMS[0], "verified": False}]
    with pytest.raises(ValueError):
        gen.generate("news", "Carousel", stale, synth=_synth(CAROUSEL_OUTPUT))


def test_generation_refuses_an_unknown_format():
    with pytest.raises(KeyError):
        gen.generate("news", "Newsletter", ITEMS, synth=_synth(CAROUSEL_OUTPUT))


def test_reel_script_fills_every_beat_with_its_timestamp():
    output = "HOOK: watch this\nREEL_ANGLE: it matters now\nCOLD_OPEN: black frame\nCAPTION: caption here\n"
    output += "".join(
        f"SEG{index}_TEXT: text {index}\nSEG{index}_VO: voice {index}\nSEG{index}_VISUAL: visual {index}\n"
        for index in range(1, len(gen.REEL_BEATS) + 1)
    )
    plan = gen.generate("tool", "Reel Script", ITEMS, synth=_synth(output))

    assert [segment["timestamp"] for segment in plan["script_segments"]] == [
        stamp for stamp, _beat in gen.REEL_BEATS
    ]
    assert plan["shot_list"] == [
        f"visual {index}" for index in range(1, len(gen.REEL_BEATS) + 1)
    ]


def test_story_hook_builds_four_numbered_frames():
    output = "HOOK: swipe up\nCAPTION: caption here\n"
    output += "".join(
        f"FRAME{index}_TEXT: text {index}\nFRAME{index}_STICKER: poll {index}\nFRAME{index}_VISUAL: shot {index}\n"
        for index in range(1, len(gen.STORY_FRAMES) + 1)
    )
    plan = gen.generate("income", "Story Hook", ITEMS, synth=_synth(output))
    assert [frame["story_number"] for frame in plan["stories"]] == [1, 2, 3, 4]


def test_caption_only_falls_back_to_the_body_when_caption_is_missing():
    plan = gen.generate(
        "automation",
        "Caption Only",
        ITEMS,
        synth=_synth("HOOK: read this\nCAPTION_BODY: the long body of the caption\n"),
    )
    assert plan["caption"] == "the long body of the caption"


@pytest.mark.parametrize(
    "pillar", ["news", "tool", "income", "transformation", "automation"]
)
def test_every_pillar_has_a_fallback_hashtag_set(pillar):
    assert len(gen.normalize_hashtags("", pillar).split()) == 5
