"""Search ONE's connected Obsidian memory."""

from __future__ import annotations

import json
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.one_agents.obsidian import (
    read_obsidian_file,
    search_obsidian,
    write_obsidian_file,
)
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("obsidian_memory")
class ObsidianMemoryTool(BaseTool):
    tool_id = "obsidian_memory"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="obsidian_memory",
            description=(
                "Safely search, read, create, or append Obsidian vault notes. "
                "All file access is restricted to the connected vault."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search", "read", "create", "append"],
                    },
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
            category="memory",
            cost_estimate=0.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            action = str(params.get("action", "search")).lower()
            if action == "search":
                result = search_obsidian(
                    str(params.get("query", "")),
                    min(int(params.get("limit", 3)), 3),
                )
            elif action == "read":
                result = read_obsidian_file(str(params.get("path", "")))
            elif action in {"create", "append"}:
                result = write_obsidian_file(
                    str(params.get("path", "")),
                    str(params.get("content", "")),
                    mode=action,
                )
            else:
                raise ValueError("Unsupported Obsidian action")
            return ToolResult(
                tool_name=self.tool_id,
                content=json.dumps(result, ensure_ascii=True),
                success=True,
            )
        except Exception as exc:
            return ToolResult(tool_name=self.tool_id, content=str(exc), success=False)
