"""Read-only Windows system/network/hardware queries for the Ghost Agent.

Born from a real failure (2026-07-21): Vineet asked "give me the details of
bluetooth connections available to pair in windows settings". The Ghost
Agent opened Settings via open_app, then correctly admitted it cannot see
or click a GUI -- and stopped. But the information itself never required
the GUI: Windows exposes all of it through PowerShell/CIM queries. The
agent had no tool for that; shell_exec exists but is confirmation-gated
(rightly -- it can run ANYTHING), and the LLM doesn't reliably know the
right Windows admin incantations anyway.

This tool is the fix: a curated allowlist of READ-ONLY diagnostic
commands, each vetted by hand. Because every command is inspect-only
(no pairing, no disconnecting, no config writes), it needs no
confirmation step -- same trust level as file_read. The knowledge lives
in the topic table below, not in the model's head, so answers come from
the actual machine, not from training-data guesses.

Windows-only, like open_app. Commands run with -NoProfile and a hard
timeout; output is truncated to keep tool results LLM-sized.
"""

from __future__ import annotations

import concurrent.futures
import os
import re
import subprocess
import sys
import time
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_TIMEOUT_SECONDS = 25
_MAX_OUTPUT_CHARS = 6000

# folder_sizes gets its own, larger budget: sizing a whole drive's folder
# tree is inherently slow (confirmed live 2026-07-25 -- "which folder is
# consuming extreme space in C:" timed out end-to-end and the frontend
# aborted at its 120s ceiling with "ONE took too long to respond").
# 70s of scanning + a couple of LLM rounds still fits inside that ceiling;
# whatever hasn't finished counting by the deadline is reported as partial
# rather than failing the whole query.
_FOLDER_SIZES_BUDGET_SECONDS = 70.0
_FOLDER_SIZES_WORKERS = 6

# topic -> (description for the LLM, exact PowerShell command)
# Every command must be read-only. Adding a topic that mutates state is a
# design violation -- that's shell_exec's (confirmation-gated) job.
_TOPICS: dict[str, tuple[str, str]] = {
    "bluetooth_devices": (
        "Bluetooth radios and all known/paired Bluetooth devices with status",
        "Get-PnpDevice -Class Bluetooth | Sort-Object Status -Descending | "
        "Select-Object Status, FriendlyName | Format-Table -AutoSize | Out-String -Width 120",
    ),
    "wifi_networks": (
        "Wi-Fi networks currently visible to the machine, with signal and channel",
        "netsh wlan show networks mode=bssid",
    ),
    "network_adapters": (
        "All network adapters with link status, speed, and MAC",
        "Get-NetAdapter | Select-Object Name, InterfaceDescription, Status, LinkSpeed, MacAddress | "
        "Format-Table -AutoSize | Out-String -Width 140",
    ),
    "ip_config": (
        "Full IP configuration: addresses, gateways, DNS, DHCP per adapter",
        "ipconfig /all",
    ),
    "audio_devices": (
        "Audio input/output endpoints (speakers, headsets, microphones) and their state",
        "Get-PnpDevice -Class AudioEndpoint -PresentOnly | "
        "Select-Object Status, FriendlyName | Format-Table -AutoSize | Out-String -Width 120",
    ),
    "usb_devices": (
        "Currently connected USB devices",
        "Get-PnpDevice -Class USB -PresentOnly | "
        "Select-Object Status, FriendlyName | Format-Table -AutoSize | Out-String -Width 120",
    ),
    "disks": (
        "Logical drives with free/total space",
        "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | "
        "Select-Object DeviceID, VolumeName, "
        "@{N='FreeGB';E={[math]::Round($_.FreeSpace/1GB,1)}}, "
        "@{N='TotalGB';E={[math]::Round($_.Size/1GB,1)}} | "
        "Format-Table -AutoSize | Out-String",
    ),
    "memory_cpu": (
        "CPU model, load, total/free RAM",
        "Get-CimInstance Win32_Processor | Select-Object Name, LoadPercentage | Format-List | Out-String; "
        "Get-CimInstance Win32_OperatingSystem | Select-Object "
        "@{N='TotalRAM_GB';E={[math]::Round($_.TotalVisibleMemorySize/1MB,1)}}, "
        "@{N='FreeRAM_GB';E={[math]::Round($_.FreePhysicalMemory/1MB,1)}} | Format-List | Out-String",
    ),
    "gpu": (
        "GPU model, VRAM, and live utilization (NVIDIA)",
        "nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv",
    ),
    "battery": (
        "Battery charge level and status (empty on desktops without one)",
        "Get-CimInstance Win32_Battery | "
        "Select-Object EstimatedChargeRemaining, BatteryStatus | Format-List | Out-String",
    ),
    "printers": (
        "Installed printers and their status",
        "Get-Printer | Select-Object Name, PrinterStatus, DriverName | "
        "Format-Table -AutoSize | Out-String -Width 120",
    ),
}


def _robocopy_folder_bytes(folder: str, deadline: float) -> int | None:
    """Total bytes under `folder` via robocopy list-only mode, or None.

    robocopy /L walks the tree natively (much faster than Python
    os.walk on a big drive) without copying anything. src==dst is the
    standard list-only trick; /XJ skips junctions so C:\\Users-style
    reparse loops don't double-count. Returns None if the per-folder
    share of the deadline ran out or the summary couldn't be parsed
    (robocopy's exit code is a bitmask, not success/failure, so the
    Bytes line is the only thing worth trusting).
    """
    remaining = deadline - time.time()
    if remaining <= 1:
        return None
    try:
        result = subprocess.run(
            [
                "robocopy", folder, folder,
                "/L", "/E", "/BYTES", "/NFL", "/NDL", "/NJH",
                "/NC", "/NS", "/NP", "/XJ", "/R:0", "/W:0",
            ],
            capture_output=True,
            text=True,
            timeout=remaining,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    match = re.search(r"Bytes\s*:\s*(\d+)", result.stdout or "")
    return int(match.group(1)) if match else None


def _folder_sizes(path_str: str) -> ToolResult:
    """Size each immediate subfolder of a path, largest first."""
    root = path_str or "C:\\"
    if not os.path.isdir(root):
        return ToolResult(
            tool_name="system_query",
            content=f"'{root}' is not an accessible directory.",
            success=False,
        )

    subdirs: list[str] = []
    try:
        for entry in os.scandir(root):
            try:
                if entry.is_dir(follow_symlinks=False):
                    subdirs.append(entry.path)
            except OSError:
                continue
    except OSError as exc:
        return ToolResult(
            tool_name="system_query",
            content=f"Cannot list '{root}': {exc}",
            success=False,
        )

    deadline = time.time() + _FOLDER_SIZES_BUDGET_SECONDS
    sizes: dict[str, int | None] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=_FOLDER_SIZES_WORKERS) as pool:
        futures = {pool.submit(_robocopy_folder_bytes, d, deadline): d for d in subdirs}
        for future in concurrent.futures.as_completed(futures):
            sizes[futures[future]] = future.result()

    finished = sorted(
        ((d, b) for d, b in sizes.items() if b is not None),
        key=lambda item: item[1],
        reverse=True,
    )
    unfinished = [d for d, b in sizes.items() if b is None]

    lines = [f"Folder sizes under {root} (largest first):"]
    for d, b in finished[:20]:
        lines.append(f"  {b / 1024 ** 3:8.2f} GB  {os.path.basename(d) or d}")
    if unfinished:
        names = ", ".join(os.path.basename(d) or d for d in unfinished)
        lines.append(
            f"(Could not finish counting within the time budget: {names} -- "
            "typically very large or permission-restricted trees. Query one "
            "of them directly with its path for a closer look.)"
        )
    return ToolResult(
        tool_name="system_query",
        content="\n".join(lines),
        success=True,
        metadata={"topic": "folder_sizes", "path": root, "unfinished": len(unfinished)},
    )


@ToolRegistry.register("system_query")
class SystemQueryTool(BaseTool):
    """Read-only queries about this Windows machine's hardware/network state."""

    tool_id = "system_query"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        topic_lines = "; ".join(f"'{k}': {v[0]}" for k, v in _TOPICS.items())
        return ToolSpec(
            name="system_query",
            description=(
                "Read the REAL current state of Vineet's Windows machine -- "
                "hardware, network, devices, and disk usage -- via vetted "
                "read-only system commands. Use this INSTEAD of opening "
                "Windows Settings whenever the request is for information "
                "(what devices/networks/disks exist, their status): Settings "
                "is a GUI you cannot see into, but this returns the actual "
                "data directly. Topics: " + topic_lines + "; "
                "'folder_sizes': which folders consume the most disk space "
                "under a path (default C:\\) -- use for any 'what is eating "
                "my disk space' question; takes up to a minute and reports "
                "partial results for trees it couldn't finish counting. "
                "Read-only and safe, so no confirmation needed -- call it "
                "directly."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "enum": [*_TOPICS.keys(), "folder_sizes"],
                        "description": "Which aspect of the system to query.",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "folder_sizes only: directory to size the "
                            "subfolders of (default C:\\). Pass a deeper "
                            "path to drill into a large folder."
                        ),
                    },
                },
                "required": ["topic"],
            },
            category="local_execution",
            cost_estimate=0.0,
            # folder_sizes legitimately needs ~70s; every other topic
            # returns in a few seconds regardless of this ceiling.
            timeout_seconds=100,
        )

    def execute(self, **params: Any) -> ToolResult:
        topic = str(params.get("topic", "")).strip()
        if topic not in _TOPICS and topic != "folder_sizes":
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Unknown topic '{topic}'. Valid: {', '.join(_TOPICS)}, folder_sizes",
                success=False,
            )

        if sys.platform != "win32":
            return ToolResult(
                tool_name=self.tool_id,
                content="system_query is only implemented for Windows right now.",
                success=False,
            )

        if topic == "folder_sizes":
            return _folder_sizes(str(params.get("path", "")).strip() or "C:\\")

        _, command = _TOPICS[topic]
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Query '{topic}' timed out after {_TIMEOUT_SECONDS}s.",
                success=False,
            )
        except OSError as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Failed to run query: {exc}",
                success=False,
            )

        output = (result.stdout or "").strip()
        if not output:
            output = (result.stderr or "").strip() or "(no output)"
        if len(output) > _MAX_OUTPUT_CHARS:
            output = output[:_MAX_OUTPUT_CHARS] + "\n... (truncated)"

        return ToolResult(
            tool_name=self.tool_id,
            content=output,
            success=result.returncode == 0,
            metadata={"topic": topic},
        )


__all__ = ["SystemQueryTool"]
