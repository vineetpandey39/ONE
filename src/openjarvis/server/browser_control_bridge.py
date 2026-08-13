"""In-process bridge between the Ghost Agent and the ONE Browser Control
Chrome extension running in Vineet's own browser.

Deliberately a SEPARATE module from ghost_extension_bridge.py (which backs
the narrower "ONE Ghost Agent" extension -- open a video, add a bookmark)
per Vineet's explicit instruction not to merge the two systems: simple
"open this video" / "search and play" requests stay on that simpler path;
this module exists only for genuine multi-step page control (navigate,
read, click, type) that Ghost Agent delegates to a separate specialized
sub-agent for (see tools/browser_control.py).

Same in-process-queue design as ghost_extension_bridge.py, for the same
reasons: no native messaging host (fragile to register correctly on
Windows), no new port -- the extension just talks to ONE's already-running
local HTTP server. Only ever talks to 127.0.0.1.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

_LIVENESS_WINDOW_SECONDS = 6.0

_lock = threading.Lock()
_pending: list[dict[str, Any]] = []
_results: dict[str, dict[str, Any]] = {}
_last_poll_at: float = 0.0


def extension_is_live() -> bool:
    """True if the extension's background worker polled recently."""
    with _lock:
        return (time.time() - _last_poll_at) < _LIVENESS_WINDOW_SECONDS


def mark_polled() -> None:
    global _last_poll_at
    with _lock:
        _last_poll_at = time.time()


def _enqueue(command: dict[str, Any]) -> str:
    command_id = uuid.uuid4().hex
    command["id"] = command_id
    with _lock:
        _pending.append(command)
    return command_id


def enqueue_navigate(url: str) -> str:
    return _enqueue({"type": "navigate", "url": url})


def enqueue_read_page() -> str:
    return _enqueue({"type": "read_page"})


def enqueue_click(ref: str, confirmed: bool = False) -> str:
    return _enqueue({"type": "click", "ref": ref, "confirmed": confirmed})


def enqueue_type(ref: str, text: str, submit: bool = False, confirmed: bool = False) -> str:
    return _enqueue({"type": "type_text", "ref": ref, "text": text, "submit": submit, "confirmed": confirmed})


def take_pending() -> list[dict[str, Any]]:
    """Drain and return all pending commands. Called by the poll endpoint."""
    with _lock:
        commands = list(_pending)
        _pending.clear()
    return commands


def has_pending() -> bool:
    with _lock:
        return bool(_pending)


def report_result(command_id: str, success: bool, detail: str = "", data: Any = None) -> None:
    with _lock:
        _results[command_id] = {"success": success, "detail": detail, "data": data, "at": time.time()}


def pop_result(command_id: str) -> dict[str, Any] | None:
    with _lock:
        return _results.pop(command_id, None)


__all__ = [
    "extension_is_live",
    "mark_polled",
    "enqueue_navigate",
    "enqueue_read_page",
    "enqueue_click",
    "enqueue_type",
    "take_pending",
    "has_pending",
    "report_result",
    "pop_result",
]
