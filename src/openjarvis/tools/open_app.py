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

import glob
import os
import sys
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _shortcut_dirs() -> list[str]:
    """Folders where Windows app shortcuts (.lnk) live."""
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
    programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    return [
        os.path.join(home, "Desktop"),
        os.path.join(home, "OneDrive", "Desktop"),
        r"C:\Users\Public\Desktop",
        os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(programdata, "Microsoft", "Windows", "Start Menu", "Programs"),
    ]


def _resolve_app_shortcut(name: str) -> tuple[str, str] | None:
    """Find the .lnk shortcut best matching an app name (path, display).

    Confirmed live (2026-07-25): asked to "open Filmora" (and even the full
    "Wondershare Filmora 15"), open_app passed that NAME to os.startfile,
    which only resolves URLs / real paths / file associations -- not an app
    by its shortcut display name -- so it reported "not available" even
    though 'Wondershare Filmora 15.lnk' sat on the desktop. This searches
    the shortcut folders and scores by name overlap so a partial name like
    "filmora" still finds it.
    """
    query = name.strip().lower()
    if not query:
        return None
    q_tokens = [t for t in query.replace("-", " ").split() if t]

    best: tuple[float, int, str] | None = None  # (score, -stem_len, path)
    for i, d in enumerate(_shortcut_dirs()):
        if not os.path.isdir(d):
            continue
        for path in glob.glob(os.path.join(d, "**", "*.lnk"), recursive=True):
            stem = os.path.splitext(os.path.basename(path))[0]
            s = stem.lower()
            if s == query:
                score = 100.0
            elif q_tokens and all(tok in s for tok in q_tokens):
                score = 85.0
            elif query in s:
                score = 75.0
            elif s in query and len(s) >= 4:
                score = 65.0
            else:
                # No weak "any shared word" tier -- matching on a common
                # token like "app" made "nonexistent app xyz" resolve to
                # "NVIDIA App" (confirmed 2026-07-25). Require a real
                # substring / full-token match or skip this shortcut.
                continue
            # Earlier dirs (Desktop) win ties; shorter stems are more specific.
            score -= i * 0.5
            cand = (score, -len(stem), path)
            if best is None or cand > best:
                best = cand
    if best is None:
        return None
    path = best[2]
    return path, os.path.splitext(os.path.basename(path))[0]


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

        # A URL or an existing path launches directly. Anything else is
        # treated as an APP NAME: resolve it against the desktop/Start-Menu
        # shortcuts first (so "filmora" finds "Wondershare Filmora 15.lnk"),
        # then fall back to raw os.startfile for names ShellExecute knows
        # natively (notepad, calc, control...).
        is_url = "://" in target
        launch_target = target
        display = target
        if not is_url and not os.path.exists(target):
            match = _resolve_app_shortcut(target)
            if match:
                launch_target, display = match

        try:
            os.startfile(launch_target)  # type: ignore[attr-defined]
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Opened {display}.",
                success=True,
                metadata={"target": launch_target, "display": display},
            )
        except (FileNotFoundError, OSError):
            # startfile failed AND we found no shortcut -> genuinely not found.
            match = None if is_url else _resolve_app_shortcut(target)
            if match:
                try:
                    os.startfile(match[0])  # type: ignore[attr-defined]
                    return ToolResult(
                        tool_name=self.tool_id,
                        content=f"Opened {match[1]}.",
                        success=True,
                        metadata={"target": match[0], "display": match[1]},
                    )
                except OSError:
                    pass
            return ToolResult(
                tool_name=self.tool_id,
                content=(
                    f"Could not find an app matching '{target}'. It may not be "
                    "installed, or has no desktop/Start-Menu shortcut. Tell me "
                    "the exact name you see under its icon, or a full path."
                ),
                success=False,
            )


__all__ = ["OpenAppTool"]
