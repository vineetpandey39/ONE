"""Tool for dispatching ONE's named local agents."""

from __future__ import annotations

import json
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.one_agents.runtime import AGENTS, agent_stats, enqueue_job, get_job, list_jobs
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("agent_network")
class AgentNetworkTool(BaseTool):
    tool_id = "agent_network"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="agent_network",
            description=(
                "List ONE agents, dispatch a durable agent job, inspect queue status, or review "
                "aggregated per-agent stats (job counts, status breakdown, last run, avg duration). "
                "Use action=stats -- NOT dispatch -- whenever the user asks how the agents are doing, "
                "for a status/stats review, or a summary of agent activity; dispatch is only for "
                "actually starting new agent work, never for reporting on existing history. "
                "Only dispatch a FLOOR HEAD (e.g. hermes, zeus, athena) -- never a worker that "
                "reports to one (e.g. scribe reports to hermes). A worker is a child the head "
                "brings in on its own once it needs the work done; dispatching the worker "
                "directly is rejected and does not start real work. "
                "detail=brief gives one line per agent; detail=holistic gives the full breakdown. "
                "Use plan by default because it is free/local. Use execute or publish only when the user explicitly requests it. "
                "Use tier=fast (default, local model) unless the task genuinely needs the heavier cloud model — "
                "tier=heavy costs NVIDIA NIM credits."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "dispatch", "status", "history", "stats"]},
                    "agent_id": {"type": "string", "enum": sorted(AGENTS)},
                    "task": {"type": "string"},
                    "mode": {"type": "string", "enum": ["plan", "execute", "publish"]},
                    "tier": {"type": "string", "enum": ["fast", "heavy"]},
                    "job_id": {"type": "string"},
                    "detail": {
                        "type": "string",
                        "enum": ["brief", "holistic"],
                        "description": (
                            "Only used with action=stats. 'brief' returns one summary line "
                            "per agent (total jobs, last status). 'holistic' includes the full "
                            "status breakdown and average completed-job duration per agent."
                        ),
                    },
                },
                "required": ["action"],
            },
            category="automation",
            cost_estimate=0.0,
            timeout_seconds=10,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            action = str(params.get("action", "list")).lower()
            if action == "list":
                content = [{"id": key, **value} for key, value in AGENTS.items()]
            elif action == "dispatch":
                agent_id = str(params.get("agent_id", "")).strip().lower()
                reports_to = AGENTS.get(agent_id, {}).get("reports_to")
                if reports_to:
                    # A worker (has reports_to) is a CHILD of its floor head --
                    # it never gets dispatched directly. Its head's own job
                    # triggers it automatically once the head actually starts
                    # running. Dispatching the worker straight from chat was
                    # observed to send it a malformed/bare task and skip the
                    # head's real handoff entirely (wrong mode, missing
                    # brief fields the worker actually needs).
                    raise ValueError(
                        f"'{agent_id}' is a worker that reports to '{reports_to}' -- it cannot be "
                        f"dispatched directly. Dispatch '{reports_to}' instead; it will bring "
                        f"'{agent_id}' in automatically once it needs the work done."
                    )
                content = enqueue_job(
                    agent_id,
                    str(params.get("task", "")),
                    str(params.get("mode", "plan")),
                    str(params.get("tier", "fast")),
                )
            elif action == "status":
                content = get_job(str(params.get("job_id", "")))
                if not content:
                    raise ValueError("Job not found")
            elif action == "history":
                content = list_jobs()
            elif action == "stats":
                detail = str(params.get("detail", "brief")).lower()
                full_stats = agent_stats()
                if detail == "holistic":
                    content = full_stats
                else:
                    # brief: one summary line's worth of fields per agent --
                    # total jobs and the most recent one's status, not the
                    # full status breakdown/duration data holistic mode gets.
                    content = [
                        {
                            "agent_id": s["agent_id"],
                            "name": s["name"],
                            "total_jobs": s["total_jobs"],
                            "last_run_at": s["last_run_at"],
                            "most_common_status": (
                                max(s["status_counts"], key=s["status_counts"].get)
                                if s["status_counts"]
                                else None
                            ),
                        }
                        for s in full_stats
                    ]
            else:
                raise ValueError(f"Unsupported action: {action}")
            return ToolResult(tool_name=self.tool_id, content=json.dumps(content, ensure_ascii=True), success=True)
        except Exception as exc:
            return ToolResult(tool_name=self.tool_id, content=str(exc), success=False)
