"""In-process bridge between the Ghost Agent and a real Chrome extension
running in Vineet's own browser -- not a separate Playwright-controlled
Chrome instance.

Confirmed root cause (2026-07-20) of most of play_video's crash history: a
freshly-launched, cookie-less, unauthenticated automation Chrome profile
(tools/play_video.py's _VideoSession) triggers CAPTCHA/bot-detection that
Vineet's own logged-in, cookie-rich Chrome never sees, on top of a long tail
of separate-process issues (SingletonLock conflicts, orphaned processes
surviving a server restart, the automation window dying whenever the ONE
server process itself restarts since it's tied to that process's pipe).
Vineet's own suggestion: build a Chrome extension in the model of
Anthropic's own "Claude in Chrome" -- have the Ghost Agent control tabs in
his REAL browser via extension APIs instead of spawning an isolated copy.

This module is the queue the extension's background service worker
long-polls and reports results through. Deliberately in-process (no native
messaging host registration, which is fragile to set up correctly on
Windows, and no new server/port) -- the extension just talks to ONE's
already-running local HTTP server, and play_video.py enqueues commands here
directly via plain function calls since it runs in the same process.

Everything here only ever talks to 127.0.0.1 -- matches this project's
standing rule (see one.env's comments) that nothing should let a remote
party reach Vineet's machine; this is a same-process queue plus a localhost
HTTP surface for the extension, nothing more.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

# The extension's background worker long-polls every few seconds when idle.
# If nothing has polled within this window, treat it as not connected/not
# running -- play_video falls back to the old Playwright automation path.
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


def enqueue_open_video(url: str) -> str:
    """Queue an 'open this video URL' command for the extension. Returns its id."""
    command_id = uuid.uuid4().hex
    with _lock:
        _pending.append({"id": command_id, "type": "open_video", "url": url})
    return command_id


def enqueue_bookmark(url: str, title: str) -> str:
    """Queue an 'add this bookmark' command for the extension. Returns its id."""
    command_id = uuid.uuid4().hex
    with _lock:
        _pending.append({"id": command_id, "type": "add_bookmark", "url": url, "title": title})
    return command_id


def take_pending() -> list[dict[str, Any]]:
    """Drain and return all pending commands. Called by the poll endpoint."""
    with _lock:
        commands = list(_pending)
        _pending.clear()
    return commands


def has_pending() -> bool:
    with _lock:
        return bool(_pending)


def report_result(command_id: str, success: bool, detail: str = "") -> None:
    with _lock:
        _results[command_id] = {"success": success, "detail": detail, "at": time.time()}


def pop_result(command_id: str) -> dict[str, Any] | None:
    with _lock:
        return _results.pop(command_id, None)


__all__ = [
    "extension_is_live",
    "mark_polled",
    "enqueue_open_video",
    "enqueue_bookmark",
    "take_pending",
    "has_pending",
    "report_result",
    "pop_result",
]
