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

import subprocess
import sys
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_TIMEOUT_SECONDS = 25
_MAX_OUTPUT_CHARS = 6000

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
                "hardware, network, and devices -- via vetted read-only "
                "system commands. Use this INSTEAD of opening Windows "
                "Settings whenever the request is for information (what "
                "devices/networks/disks exist, their status): Settings is a "
                "GUI you cannot see into, but this returns the actual data "
                "directly. Topics: " + topic_lines + ". Read-only and safe, "
                "so no confirmation needed -- call it directly."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "enum": list(_TOPICS.keys()),
                        "description": "Which aspect of the system to query.",
                    },
                },
                "required": ["topic"],
            },
            category="local_execution",
            cost_estimate=0.0,
            timeout_seconds=30,
        )

    def execute(self, **params: Any) -> ToolResult:
        topic = str(params.get("topic", "")).strip()
        if topic not in _TOPICS:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Unknown topic '{topic}'. Valid: {', '.join(_TOPICS)}",
                success=False,
            )

        if sys.platform != "win32":
            return ToolResult(
                tool_name=self.tool_id,
                content="system_query is only implemented for Windows right now.",
                success=False,
            )

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
