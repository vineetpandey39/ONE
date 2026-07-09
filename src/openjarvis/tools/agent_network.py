"""Tool for dispatching ONE's named local agents."""

from __future__ import annotations

import json
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.one_agents.runtime import AGENTS, enqueue_job, get_job, list_jobs
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
                "List ONE agents, dispatch a durable agent job, or inspect queue status. "
                "Use plan by default because it is free/local. Use execute or publish only when the user explicitly requests it. "
                "Use tier=fast (default, local model) unless the task genuinely needs the heavier cloud model — "
                "tier=heavy costs NVIDIA NIM credits."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "dispatch", "status", "history"]},
                    "agent_id": {"type": "string", "enum": sorted(AGENTS)},
                    "task": {"type": "string"},
                    "mode": {"type": "string", "enum": ["plan", "execute", "publish"]},
                    "tier": {"type": "string", "enum": ["fast", "heavy"]},
                    "job_id": {"type": "string"},
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
                content = enqueue_job(
                    str(params.get("agent_id", "")),
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
            else:
                raise ValueError(f"Unsupported action: {action}")
            return ToolResult(tool_name=self.tool_id, content=json.dumps(content, ensure_ascii=True), success=True)
        except Exception as exc:
            return ToolResult(tool_name=self.tool_id, content=str(exc), success=False)
