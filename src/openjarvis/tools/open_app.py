"""Open a local application, file, or URL — Windows-native, non-blocking.

Confirmed live (2026-07-19): routing "open Chrome" / "open youtube.com"
through shell_exec's `start <target>` hung for the full 30s timeout every
time. Root cause is a well-known Windows subprocess gotcha: shell_exec runs
`cmd.exe /c start ...` with stdout/stderr captured via pipes, and the app
`start` launches (e.g. chrome.exe) inherits those pipe handles -- Python's
subprocess.run then blocks waiting for every process holding the pipe's
write end to close, which the launched GUI app never does for the rest of
the session. os.startfile() sidesteps this entirely: it calls the Win32
ShellExecute API directly (the same mechanism as double-clicking something
in Explorer), returns in well under a tenth of a second, and creates no
subprocess/pipe relationship with the launched app at all.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("open_app")
class OpenAppTool(BaseTool):
    """Open an application, website, or file on the local machine."""

    tool_id = "open_app"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="open_app",
            description=(
                "Open an application, website, or file on Vineet's computer -- "
                "e.g. open Chrome, open a URL like youtube.com, open a document. "
                "Equivalent to double-clicking it: launches and returns "
                "immediately, does not read its output or wait for it to close. "
                "Safe and non-destructive, so unlike shell_exec this needs no "
                "confirmation -- use it directly for any 'open X' request "
                "instead of routing it through shell_exec's `start` command, "
                "which hangs for GUI apps."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": (
                            "What to open: a full URL (https://youtube.com), "
                            "an application name (chrome, notepad, calc), or a "
                            "file path."
                        ),
                    },
                },
                "required": ["target"],
            },
            category="local_execution",
            cost_estimate=0.0,
            timeout_seconds=10,
        )

    def execute(self, **params: Any) -> ToolResult:
        target = str(params.get("target", "")).strip()
        if not target:
            return ToolResult(tool_name=self.tool_id, content="No target provided.", success=False)

        if sys.platform != "win32":
            return ToolResult(
                tool_name=self.tool_id,
                content="open_app is only implemented for Windows right now.",
                success=False,
            )

        try:
            os.startfile(target)  # type: ignore[attr-defined]
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Opened: {target}",
                success=True,
                metadata={"target": target},
            )
        except FileNotFoundError:
            return ToolResult(
                tool_name=self.tool_id,
                content=(
                    f"Could not find '{target}'. Try a full URL (https://...) "
                    "or the exact application name."
                ),
                success=False,
            )
        except OSError as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Failed to open '{target}': {exc}",
                success=False,
            )


__all__ = ["OpenAppTool"]
