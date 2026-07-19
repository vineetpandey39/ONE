"""Current date/time tool.

Confirmed live (2026-07-19): asking ONE "what time is it right now?" burned
all 10 ReAct turns and returned "Maximum turns reached without a final
answer" -- there was no tool anywhere that could answer a plain clock
question, so the agent kept trying unrelated tools (memory notes, file
writes) as workarounds instead. This is the missing capability.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

DEFAULT_TIMEZONE = "Asia/Kolkata"


@ToolRegistry.register("get_current_time")
class GetCurrentTimeTool(BaseTool):
    """Returns the real current date and time -- never guess this from memory."""

    tool_id = "get_current_time"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_current_time",
            description=(
                "Get the real current date and time. Use this whenever the user asks "
                "what time or date it is, or a request needs 'now' as a reference point -- "
                "never guess or estimate the time from memory notes or journal entries."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": (
                            f"IANA timezone name, e.g. 'Asia/Kolkata'. Defaults to "
                            f"{DEFAULT_TIMEZONE} (Vineet's local timezone) if omitted."
                        ),
                    },
                },
                "required": [],
            },
            category="utility",
            cost_estimate=0.0,
            timeout_seconds=5,
        )

    def execute(self, **params: Any) -> ToolResult:
        tz_name = str(params.get("timezone") or DEFAULT_TIMEZONE)
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Unknown timezone: {tz_name}",
                success=False,
            )
        now = datetime.now(tz)
        content = (
            f"{now.strftime('%A, %d %B %Y, %H:%M:%S')} ({tz_name}, "
            f"UTC{now.strftime('%z')[:3]}:{now.strftime('%z')[3:]})"
        )
        return ToolResult(tool_name=self.tool_id, content=content, success=True)


__all__ = ["GetCurrentTimeTool"]
