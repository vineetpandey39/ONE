"""IRIS grounding the aibyvineet carousel brief in the verified feed.

This lane can publish to Instagram under a standing authority, so the rule
under test is not "does grounding work" but "does a research miss leave the
existing behaviour exactly as it was". Every miss path is pinned below.
"""

from __future__ import annotations

import pytest

from openjarvis.one_agents import runtime

TASK = "Next aibyvineet carousel"

ITEMS = [
    {
        "headline": "Anthropic ships Claude memory",
        "source": "anthropic.com",
        "url": "https://www.anthropic.com/news/claude-memory",
        "publishedAt": "2026-09-24T12:00:00Z",
        "summary": "Memory arrives for Claude projects.",
    },
    {
        "headline": "OpenAI updates Codex",
        "source": "openai.com",
        "url": "https://openai.com/index/codex-update",
        "publishedAt": "2026-09-24T09:00:00Z",
        "summary": "Codex gets longer autonomous runs.",
    },
]


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("ONE_KAIROS_VERIFIED_FEED", raising=False)
    monkeypatch.delenv("ONE_KAIROS_PILLAR", raising=False)
    monkeypatch.delenv("TITAN_DEFAULT_PILLAR", raising=False)
    return tmp_path


def _feed(monkeypatch, payload, *, calls=None):
    def fake(pillar="news", *, force=False):
        if calls is not None:
            calls.append(pillar)
        return payload

    monkeypatch.setattr(runtime, "_kairos_verified_feed", fake)


def test_the_brief_carries_every_verified_source(monkeypatch, home):
    _feed(monkeypatch, {"items": ITEMS, "freshnessHours": 24, "rejected": 3})

    angle, evidence_path, count = runtime._kairos_grounded_angle(TASK, "job-1", [])

    assert count == 2
    assert TASK in angle
    for item in ITEMS:
        assert item["url"] in angle
        assert item["headline"] in angle
    assert "last 24 hours" in angle
    assert evidence_path.endswith("job-1-aibyvineet-sources.md")
    written = (home / "agent_outputs" / "job-1-aibyvineet-sources.md").read_text(
        encoding="utf-8"
    )
    assert "Researched by: Sanjeevani, verified by PostForge" in written
    assert "Rejected: 3" in written


def test_prior_angles_are_handed_over_so_the_worker_does_not_repeat_itself(monkeypatch):
    _feed(monkeypatch, {"items": ITEMS, "freshnessHours": 24, "rejected": 0})
    angle, _path, _count = runtime._kairos_grounded_angle(
        TASK, "job-2", ["An older angle"]
    )
    assert "An older angle" in angle


def test_an_empty_feed_leaves_the_brief_exactly_as_it_was(monkeypatch, home):
    _feed(monkeypatch, {"items": [], "freshnessHours": 24, "rejected": 7})

    angle, evidence_path, count = runtime._kairos_grounded_angle(TASK, "job-3", [])

    assert (angle, evidence_path, count) == (TASK, "", 0)
    assert not (home / "agent_outputs").exists()


def test_a_failing_feed_never_stops_the_lane(monkeypatch):
    def explode(pillar="news", *, force=False):
        raise RuntimeError("Sanjeevani research library is unavailable")

    monkeypatch.setattr(runtime, "_kairos_verified_feed", explode)
    assert runtime._kairos_grounded_angle(TASK, "job-4", []) == (TASK, "", 0)


@pytest.mark.parametrize("value", ["0", "false", "NO"])
def test_the_kill_switch_skips_the_feed_entirely(monkeypatch, value):
    calls: list[str] = []
    _feed(
        monkeypatch, {"items": ITEMS, "freshnessHours": 24, "rejected": 0}, calls=calls
    )
    monkeypatch.setenv("ONE_KAIROS_VERIFIED_FEED", value)

    assert runtime._kairos_grounded_angle(TASK, "job-5", []) == (TASK, "", 0)
    assert calls == [], "the kill switch must stop the search, not just the brief"


def test_the_pillar_comes_from_the_environment(monkeypatch):
    calls: list[str] = []
    _feed(
        monkeypatch, {"items": ITEMS, "freshnessHours": 24, "rejected": 0}, calls=calls
    )
    monkeypatch.setenv("ONE_KAIROS_PILLAR", "tool")
    runtime._kairos_grounded_angle(TASK, "job-6", [])
    assert calls == ["tool"]


def test_the_pillar_falls_back_to_the_existing_titan_setting(monkeypatch):
    calls: list[str] = []
    _feed(
        monkeypatch, {"items": ITEMS, "freshnessHours": 24, "rejected": 0}, calls=calls
    )
    monkeypatch.setenv("TITAN_DEFAULT_PILLAR", "automation")
    runtime._kairos_grounded_angle(TASK, "job-7", [])
    assert calls == ["automation"]


def test_the_pillar_defaults_to_news(monkeypatch):
    calls: list[str] = []
    _feed(
        monkeypatch, {"items": ITEMS, "freshnessHours": 24, "rejected": 0}, calls=calls
    )
    runtime._kairos_grounded_angle(TASK, "job-8", [])
    assert calls == ["news"]
