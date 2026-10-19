"""In-worker serialization for scarce Floor 12 resources.

Floor 12 is flow-concurrent, not resource-concurrent. Research, SEO and local
editing may overlap; an Envato account/download session may not. Named lanes
keep that distinction explicit instead of blocking the whole floor.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator


_LOCKS: dict[str, threading.Lock] = {}
_GUARD = threading.Lock()


def _lock(name: str) -> threading.Lock:
    with _GUARD:
        return _LOCKS.setdefault(name, threading.Lock())


@contextmanager
def claim(name: str, *, heartbeat: Callable[[], None] | None = None,
          cancelled: Callable[[], bool] | None = None,
          poll_seconds: float = 2.0) -> Iterator[None]:
    """Wait for one named lane while keeping queue ownership alive."""
    lane = _lock(name)
    while not lane.acquire(timeout=max(0.1, poll_seconds)):
        if heartbeat:
            heartbeat()
        if cancelled and cancelled():
            raise RuntimeError(f"Job cancelled while waiting for {name} resource lane")
        time.sleep(0)
    try:
        yield
    finally:
        lane.release()
