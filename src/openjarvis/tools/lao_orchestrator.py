"""Bridge tool for controlling LAO workflows from ONE."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


DEFAULT_LAO_BASE_URL = "http://127.0.0.1:18000/api/v1"
DEFAULT_DRY_RUN_PROCESS = "Daily LinkedIn Authority Post - Dry Run"
DEFAULT_PUBLISH_PROCESS = "Daily LinkedIn Authority Post"
ACTIVE_JOB_STATUSES = {"Pending", "Assigned", "Running"}


def _json_result(payload: dict[str, Any], *, success: bool = True) -> ToolResult:
    return ToolResult(
        tool_name="lao_orchestrator",
        content=json.dumps(payload, ensure_ascii=True, indent=2),
        success=success,
        metadata=payload,
    )


def _scope_candidates(preferred: str | None) -> list[str]:
    scopes = [
        preferred or "",
        "production",
        "non-production",
        "non_production",
        "nonproduction",
        "all",
    ]
    seen: set[str] = set()
    return [scope for scope in scopes if scope and not (scope in seen or seen.add(scope))]


def _default_process_name(mode: str) -> str:
    if mode in {"publish", "production"}:
        return os.environ.get("LAO_LINKEDIN_PUBLISH_PROCESS", DEFAULT_PUBLISH_PROCESS)
    return os.environ.get("LAO_LINKEDIN_DRY_RUN_PROCESS", DEFAULT_DRY_RUN_PROCESS)


class _LaoClient:
    def __init__(self, base_url: str, email: str, password: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.timeout = timeout
        self.token = ""

    def login(self) -> None:
        preset_token = os.environ.get("LAO_ACCESS_TOKEN", "").strip()
        if preset_token:
            self.token = preset_token
            return
        response = httpx.post(
            f"{self.base_url}/auth/login",
            json={"email": self.email, "password": self.password},
            timeout=self.timeout,
        )
        response.raise_for_status()
        self.token = response.json()["access_token"]

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path: str, **params: Any) -> Any:
        response = httpx.get(
            f"{self.base_url}{path}",
            params={key: value for key, value in params.items() if value is not None},
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        response = httpx.post(
            f"{self.base_url}{path}",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        if response.status_code == 204:
            return {}
        return response.json()

    def list_processes(self, scope: str) -> list[dict[str, Any]]:
        return list(self.get("/processes", scope=scope) or [])

    def find_process(self, name: str, preferred_scope: str | None) -> tuple[dict[str, Any], str]:
        inspected: list[str] = []
        for scope in _scope_candidates(preferred_scope):
            inspected.append(scope)
            try:
                processes = self.list_processes(scope)
            except httpx.HTTPStatusError:
                continue
            exact = [process for process in processes if process.get("name") == name]
            if exact:
                return exact[0], scope
            fuzzy = [process for process in processes if name.lower() in str(process.get("name", "")).lower()]
            if fuzzy:
                return fuzzy[0], scope
        raise RuntimeError(f"LAO process not found: {name}. Inspected scopes: {', '.join(inspected)}")

    def list_jobs(self, scope: str, process_id: str | None = None) -> list[dict[str, Any]]:
        jobs = list(self.get("/jobs", scope=scope) or [])
        if process_id:
            jobs = [job for job in jobs if job.get("process_id") == process_id]
        return jobs

    def latest_job(self, scope: str, process_id: str | None = None, active_only: bool = False) -> dict[str, Any] | None:
        jobs = self.list_jobs(scope, process_id)
        if active_only:
            jobs = [job for job in jobs if job.get("status") in ACTIVE_JOB_STATUSES]
        return jobs[0] if jobs else None


@ToolRegistry.register("lao_orchestrator")
class LaoOrchestratorTool(BaseTool):
    """Control LAO packages, processes, and jobs from ONE agents."""

    tool_id = "lao_orchestrator"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="lao_orchestrator",
            description=(
                "Start, stop, inspect, and fetch logs for Local Agent Orchestrator "
                "(LAO) workflows such as LinkedIn daily posting."
            ),
            category="automation",
            timeout_seconds=45,
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list_processes", "start", "status", "logs", "stop"],
                        "default": "status",
                    },
                    "mode": {"type": "string", "enum": ["dry_run", "publish"], "default": "dry_run"},
                    "process_name": {"type": "string"},
                    "scope": {"type": "string", "default": "production"},
                    "job_id": {"type": "string"},
                    "include_logs": {"type": "boolean", "default": False},
                    "confirm_publish": {"type": "boolean", "default": False},
                    "input_args": {"type": "object"},
                },
                "required": ["action"],
            },
        )

    def execute(self, **params: Any) -> ToolResult:
        action = str(params.get("action") or "status").strip().lower()
        mode = str(params.get("mode") or "dry_run").strip().lower()
        scope = str(params.get("scope") or ("production" if mode == "publish" else "non-production")).strip()
        process_name = str(params.get("process_name") or _default_process_name(mode)).strip()
        timeout = float(params.get("timeout") or os.environ.get("LAO_TOOL_TIMEOUT_SECONDS", "30"))
        client = _LaoClient(
            os.environ.get("LAO_BASE_URL", DEFAULT_LAO_BASE_URL),
            os.environ.get("LAO_EMAIL", "admin@example.com"),
            os.environ.get("LAO_PASSWORD", "ChangeMe123!"),
            timeout,
        )

        try:
            client.login()
            if action == "list_processes":
                processes = client.list_processes(scope)
                return _json_result({"action": action, "scope": scope, "processes": processes})

            process: dict[str, Any] | None = None
            resolved_scope = scope
            try:
                process, resolved_scope = client.find_process(process_name, scope)
            except RuntimeError:
                if not params.get("job_id"):
                    raise

            if action == "start":
                if mode == "publish" and not bool(params.get("confirm_publish")):
                    return _json_result(
                        {
                            "action": action,
                            "mode": mode,
                            "accepted": False,
                            "reason": "Publish mode requires confirm_publish=true.",
                        },
                        success=False,
                    )
                assert process is not None
                job = client.post(
                    "/jobs",
                    {"process_id": process["id"], "input_args": params.get("input_args") or {}},
                )
                return _json_result(
                    {
                        "action": action,
                        "mode": mode,
                        "scope": resolved_scope,
                        "process": {"id": process["id"], "name": process.get("name")},
                        "job": job,
                    }
                )

            job_id = str(params.get("job_id") or "").strip()
            if not job_id:
                job = client.latest_job(
                    resolved_scope,
                    process.get("id") if process else None,
                    active_only=(action == "stop"),
                )
                if not job:
                    return _json_result(
                        {
                            "action": action,
                            "scope": resolved_scope,
                            "process": process_name,
                            "job": None,
                            "message": "No matching LAO job found.",
                        }
                    )
                job_id = job["id"]
            job = client.get(f"/jobs/{job_id}", scope=resolved_scope)

            payload: dict[str, Any] = {
                "action": action,
                "scope": resolved_scope,
                "process": {"id": process.get("id"), "name": process.get("name")} if process else None,
                "job": job,
            }
            if action == "stop":
                payload["stop_result"] = client.post(f"/jobs/{job_id}/stop")
            if action in {"logs", "status"} and bool(params.get("include_logs", action == "logs")):
                payload["logs"] = client.get(f"/jobs/{job_id}/logs", scope=resolved_scope)
                payload["artifacts"] = client.get(f"/jobs/{job_id}/artifacts", scope=resolved_scope)
            return _json_result(payload)
        except Exception as exc:  # noqa: BLE001 - tool boundary returns structured failure
            return _json_result(
                {"action": action, "mode": mode, "process": process_name, "error": str(exc)},
                success=False,
            )
