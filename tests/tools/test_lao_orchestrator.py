from __future__ import annotations

import json

import httpx

from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.is_error:
            raise httpx.HTTPStatusError("failed", request=httpx.Request("GET", "http://test"), response=httpx.Response(self.status_code))


def test_lao_orchestrator_starts_dry_run(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(("POST", url, json))
        if url.endswith("/auth/login"):
            return _FakeResponse({"access_token": "token"})
        if url.endswith("/jobs"):
            return _FakeResponse({"id": "job-1", "status": "Pending", "process_id": "process-1"})
        raise AssertionError(url)

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(("GET", url, params))
        if url.endswith("/processes"):
            return _FakeResponse([{"id": "process-1", "name": "Daily LinkedIn Authority Post - Dry Run"}])
        raise AssertionError(url)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    result = LaoOrchestratorTool().execute(action="start", mode="dry_run")
    payload = json.loads(result.content)

    assert result.success
    assert payload["job"]["id"] == "job-1"
    assert calls[-1] == ("POST", "http://127.0.0.1:8000/api/v1/jobs", {"process_id": "process-1", "input_args": {}})


def test_lao_orchestrator_publish_requires_confirmation(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: _FakeResponse({"access_token": "token"}))
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: _FakeResponse([{"id": "process-1", "name": "Daily LinkedIn Authority Post"}]))

    result = LaoOrchestratorTool().execute(action="start", mode="publish", confirm_publish=False)
    payload = json.loads(result.content)

    assert not result.success
    assert payload["accepted"] is False
    assert "confirm_publish" in payload["reason"]


def test_lao_orchestrator_status_uses_latest_job(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResponse({"access_token": "token"})

    def fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/processes"):
            return _FakeResponse([{"id": "process-1", "name": "Daily LinkedIn Authority Post - Dry Run"}])
        if url.endswith("/jobs") and not url.endswith("/jobs/job-2"):
            return _FakeResponse([{"id": "job-2", "status": "Successful", "process_id": "process-1"}])
        if url.endswith("/jobs/job-2"):
            return _FakeResponse({"id": "job-2", "status": "Successful", "process_id": "process-1"})
        raise AssertionError(url)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    result = LaoOrchestratorTool().execute(action="status", mode="dry_run")
    payload = json.loads(result.content)

    assert result.success
    assert payload["job"]["id"] == "job-2"
