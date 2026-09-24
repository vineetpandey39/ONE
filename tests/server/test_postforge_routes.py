"""Tests for the /v1/postforge API router.

The feed and the writer have their own tests; what matters here is the contract
the cockpit sees -- above all, that a missing Sanjeevani is a clear 503 and not
a silent empty feed the operator would read as "no AI news today".
"""

from __future__ import annotations

import pytest

from openjarvis.postforge import feed, writer


@pytest.fixture
def client():
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")

    from openjarvis.server.postforge_routes import router

    app = FastAPI()
    # The router already carries prefix="/v1/postforge", same as the real app.
    app.include_router(router)
    return TestClient(app)


def test_pillars_lists_all_five_tabs_and_the_window(client):
    payload = client.get("/v1/postforge/pillars").json()
    assert [pillar["id"] for pillar in payload["pillars"]] == [
        "news",
        "tool",
        "income",
        "transformation",
        "automation",
    ]
    assert payload["freshnessHours"] == 24
    assert "Carousel" in payload["formats"]


def test_refresh_returns_the_feed_payload(client, monkeypatch):
    monkeypatch.setattr(
        feed,
        "refresh",
        lambda pillar, force=False: {"pillar": pillar, "items": [], "forced": force},
    )
    response = client.post(
        "/v1/postforge/refresh", json={"pillar": "tool", "force": True}
    )
    assert response.status_code == 200
    assert response.json() == {"pillar": "tool", "items": [], "forced": True}


def test_refresh_rejects_an_unknown_pillar_with_400(client):
    response = client.post("/v1/postforge/refresh", json={"pillar": "crypto"})
    assert response.status_code == 400


def test_refresh_without_sanjeevani_is_a_503_not_an_empty_feed(client, monkeypatch):
    def unavailable(pillar, force=False):
        raise feed.SanjeevaniUnavailable("research library is unavailable")

    monkeypatch.setattr(feed, "refresh", unavailable)
    response = client.post("/v1/postforge/refresh", json={"pillar": "news"})
    assert response.status_code == 503
    assert "research library" in response.json()["detail"]


def test_generate_returns_the_plan(client, monkeypatch):
    monkeypatch.setattr(
        writer, "generate", lambda pillar, fmt, items: {"hook": "ok", "_format": fmt}
    )
    response = client.post(
        "/v1/postforge/generate",
        json={"pillar": "news", "format": "Carousel", "items": [{"verified": True}]},
    )
    assert response.status_code == 200
    assert response.json()["_format"] == "Carousel"


def test_generate_refuses_an_unverified_selection_with_400(client):
    response = client.post(
        "/v1/postforge/generate",
        json={"pillar": "news", "format": "Carousel", "items": []},
    )
    assert response.status_code == 400
    assert "verified" in response.json()["detail"]


def test_generate_reports_a_blocked_local_model_as_503(client, monkeypatch):
    def blocked(pillar, fmt, items):
        raise writer.GenerationBlocked("Ollama is not running")

    monkeypatch.setattr(writer, "generate", blocked)
    response = client.post(
        "/v1/postforge/generate",
        json={"pillar": "news", "format": "Carousel", "items": [{"verified": True}]},
    )
    assert response.status_code == 503
    assert "Ollama" in response.json()["detail"]
