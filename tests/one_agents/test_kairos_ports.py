"""KAIROS's port wiring, and the one failure mode it has to survive.

``Ports`` is defined in one-company/floors, outside this repository and
versioned separately, so a checkout here can be newer than the floors tree on
disk. Passing a keyword that tree does not declare would TypeError every KAIROS
job -- the carousel lane and the revenue lane both -- so the new verified_feed
port is offered, never assumed. Both directions are pinned here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from openjarvis.one_agents import runtime


@dataclass
class _OldPorts:
    """A floors checkout from before the feed existed."""

    research: Any = None
    remember: Any = None
    set_stage: Any = None
    clear_stage: Any = None
    enqueue: Any = None
    output_dir: Any = None
    collect: Any = None
    chatgpt: Any = None
    generate_images: Any = None
    upload: Any = None
    publish: Any = None
    confirm_receipt: Any = None
    insights: Any = None
    video_search: Any = None
    web_search: Any = None
    read_page: Any = None
    graph_for: Any = None
    declare_revenue_source: Any = None


@dataclass
class _NewPorts(_OldPorts):
    verified_feed: Any = None


class _FakeKairos:
    """Stands in for floors' kairos_agent: records the ports it was handed."""

    def __init__(self, ports_type):
        self.Ports = ports_type
        self.received = None

    def run(self, job, ports):
        self.received = ports
        return {"agent": "KAIROS", "job": job.get("id")}


@pytest.fixture
def load_fake(monkeypatch):
    def install(ports_type):
        fake = _FakeKairos(ports_type)

        def load(package, module):
            # aibyvineet_publish stays absent: the publishing ports are not
            # what this test is about, and None is a shape KAIROS already
            # handles (runtime passes None for every unavailable port).
            return fake if module == "kairos_agent" else None

        monkeypatch.setattr(runtime.floors_bridge, "load", load)
        return fake

    return install


def test_ports_accepts_reads_the_floors_side_signature():
    assert runtime._ports_accepts(_NewPorts, "verified_feed")
    assert not runtime._ports_accepts(_OldPorts, "verified_feed")


def test_ports_accepts_says_no_rather_than_raising_on_a_weird_type():
    assert not runtime._ports_accepts(None, "verified_feed")
    assert not runtime._ports_accepts(object(), "verified_feed")


def test_kairos_gets_the_verified_feed_when_floors_declares_it(load_fake):
    fake = load_fake(_NewPorts)
    result = runtime._run_kairos({"id": "job-1"})
    assert result["agent"] == "KAIROS"
    assert fake.received.verified_feed is runtime._kairos_verified_feed


def test_an_older_floors_checkout_still_runs_untouched(load_fake):
    # The regression that matters: this used to be a TypeError, which would
    # have taken out the revenue lane too, not just the carousel.
    fake = load_fake(_OldPorts)
    result = runtime._run_kairos({"id": "job-2"})
    assert result["agent"] == "KAIROS"
    assert not hasattr(fake.received, "verified_feed")


def test_the_existing_ports_are_still_handed_over(load_fake):
    fake = load_fake(_NewPorts)
    runtime._run_kairos({"id": "job-3"})
    assert fake.received.research is runtime._research_synthesis
    assert fake.received.chatgpt is runtime._kairos_chatgpt
    assert fake.received.output_dir.name == "agent_outputs"


def test_verified_feed_port_delegates_to_the_postforge_feed(monkeypatch):
    from openjarvis.postforge import feed

    seen: dict[str, Any] = {}

    def fake_refresh(pillar, force=False):
        seen.update(pillar=pillar, force=force)
        return {"items": [], "pillar": pillar}

    monkeypatch.setattr(feed, "refresh", fake_refresh)
    payload = runtime._kairos_verified_feed("tool", force=True)
    assert seen == {"pillar": "tool", "force": True}
    assert payload["pillar"] == "tool"


def test_verified_feed_port_defaults_to_the_news_pillar(monkeypatch):
    from openjarvis.postforge import feed

    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        feed, "refresh", lambda pillar, force=False: seen.update(pillar=pillar) or {}
    )
    runtime._kairos_verified_feed()
    assert seen == {"pillar": "news"}


def test_kairos_without_a_floors_tree_degrades_to_the_local_planner(monkeypatch):
    monkeypatch.setattr(runtime.floors_bridge, "load", lambda package, module: None)
    monkeypatch.setattr(
        runtime, "_local_plan", lambda job: {"agent": "local", "job": job["id"]}
    )
    assert runtime._run_kairos({"id": "job-4"})["agent"] == "local"
