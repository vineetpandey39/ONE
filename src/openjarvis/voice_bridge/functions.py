"""Narrow, redacted function surface exposed to Deepgram's cloud 'think' LLM.

Only 3 functions are declared here -- deliberately NOT the full tool zoo from
server/routes.py's `_cloud_escalation_tools()`. Anything that could expose
free-text conversation/journal/task content wholesale is either excluded
entirely (search_obsidian, agent_network history/dispatch, ShellExecTool,
FileReadTool, OpenAppTool, ScreenControlTool) or piped through
`voice_bridge.redact.redact()` before it's ever returned (recall_memory).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from openjarvis.tools._stubs import BaseTool
from openjarvis.tools.agent_network import AgentNetworkTool
from openjarvis.tools.datetime_tool import GetCurrentTimeTool
from openjarvis.tools.memory_recall import MemoryRecallTool
from openjarvis.voice_bridge.redact import redact

logger = logging.getLogger("openjarvis.voice_bridge")

_time_tool = GetCurrentTimeTool()
_agent_tool = AgentNetworkTool()
_memory_tool = MemoryRecallTool()

_AGENT_STATS_SCHEMA: Dict[str, Any] = {
    "name": "agent_stats",
    "description": (
        "Get a summary of how Sir's local agents are doing -- job counts and "
        "last-run status. Use for any 'how are the agents doing' or "
        "status-review question. Never use this to start new agent work."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "detail": {
                "type": "string",
                "enum": ["brief", "holistic"],
                "description": "brief = one line per agent (default). holistic = fuller breakdown.",
            }
        },
        "required": [],
    },
}


def deepgram_function_schemas() -> List[Dict[str, Any]]:
    """The 3 functions declared to Deepgram, in its flat schema shape.

    Deepgram's `agent.think.functions` wants `[{name, description,
    parameters}]` -- one layer flatter than BaseTool.to_openai_function()'s
    `{type: "function", function: {...}}` envelope -- so this just unwraps
    it. No `endpoint` is set on any of these, which per Deepgram's docs means
    they're executed client-side: the server sends a FunctionCallRequest and
    this bridge answers it locally (see client.py's _handle_function_calls).
    """
    tools: list[BaseTool] = [_time_tool]
    schemas = [t.to_openai_function()["function"] for t in tools]
    schemas.append(_AGENT_STATS_SCHEMA)

    mem_schema = _memory_tool.to_openai_function()["function"]
    mem_schema["description"] = (
        mem_schema["description"]
        + " Results are sanitized and shortened before you receive them; some detail may be trimmed."
    )
    schemas.append(mem_schema)
    return schemas


def _audit(name: str, arguments: Dict[str, Any], pre: str, post: str) -> None:
    """Local-only audit trail: what a function returned before and after
    redaction, so Vineet can verify the filter is actually working. Never
    transmitted -- this file never leaves the machine."""
    try:
        from openjarvis.core.paths import get_config_dir

        log_dir = get_config_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "function": name,
                "arguments": arguments,
                "pre_redaction": pre,
                "post_redaction": post,
            },
            ensure_ascii=True,
        )
        with open(log_dir / "voice_bridge_audit.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        logger.debug("voice bridge audit log write failed", exc_info=True)


def execute_function(name: str, arguments: Dict[str, Any]) -> str:
    """Run one of the 3 allowed functions and return an already-redacted string.

    Never raises: an unknown function name or a tool-level error becomes a
    safe generic message rather than propagating, since this return value
    goes straight back over the WebSocket to Deepgram's cloud.
    """
    try:
        if name == "get_current_time":
            pre = _time_tool.execute(**arguments).content
        elif name == "agent_stats":
            pre = _agent_tool.execute(action="stats", detail=arguments.get("detail", "brief")).content
        elif name == "recall_memory":
            pre = _memory_tool.execute(**arguments).content
        else:
            pre = f"Unknown function: {name}"
    except Exception as exc:  # noqa: BLE001
        pre = f"Function '{name}' failed: {exc}"

    post = redact(pre)
    _audit(name, arguments, pre, post)
    return post


__all__ = ["deepgram_function_schemas", "execute_function"]
