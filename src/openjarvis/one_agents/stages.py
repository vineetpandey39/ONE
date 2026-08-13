"""Fine-grained work stages for ONE's floor agents.

The job queue only knows queued/running/completed. That is too coarse for the
company building, which needs to show *what* an agent is doing right now —
researching at its desk, carrying a file across the floor, waiting on a long
external job, reporting back.

Stages are written by the agent runtime and read over HTTP by the Company
Layer. They are a presentation-facing mirror of real execution, never a
substitute for it: nothing sets a stage that the code isn't actually doing.

Shared by two OS processes (the API server and the standalone worker), so
writes go through a temp file + os.replace for atomicity.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

# Every stage an agent can be in. The building maps these to positions and
# animations; anything not listed here is treated as "at desk, idle".
IDLE = "idle"
RESEARCHING = "researching"        # head at its desk, thinking/writing
CARRYING_TO_WORKER = "carrying_to_worker"   # head walking, file in hand
BRIEFING = "briefing"              # head at the worker's desk, handing over
AWAITING_WORKER = "awaiting_worker"          # head back at desk, blocked
RECEIVING = "receiving"            # worker taking the brief
EXECUTING = "executing"            # worker typing; external job running
CARRYING_TO_HEAD = "carrying_to_head"        # worker walking back, book in hand
DELIVERING = "delivering"          # worker at the head's desk, handing over
CELEBRATING = "celebrating"        # both of them, the moment a book ships
REPORTING = "reporting"            # head reporting the result upward

_TERMINAL = {IDLE}


def _home() -> Path:
    return Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))


def _path() -> Path:
    path = _home() / "agent_stages.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_stages() -> dict[str, dict[str, Any]]:
    """Every agent's current stage. Never raises — a missing or corrupt file
    just means 'nobody is mid-flow', which is the correct default."""
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def set_stage(agent_id: str, stage: str, detail: str = "", **extra: Any) -> None:
    """Record an agent's stage. Best-effort: a failure here must never take
    down the job that is actually doing the work."""
    try:
        stages = get_stages()
        if stage in _TERMINAL:
            stages.pop(agent_id, None)
        else:
            stages[agent_id] = {
                "stage": stage,
                "detail": detail,
                "since": time.time(),
                **extra,
            }
        path = _path()
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(stages, handle)
        os.replace(tmp, path)     # atomic on Windows and POSIX alike
    except Exception:  # noqa: BLE001 - telemetry must not break execution
        pass


def clear_stage(agent_id: str) -> None:
    set_stage(agent_id, IDLE)


def clear_all() -> None:
    try:
        _path().unlink(missing_ok=True)
    except OSError:
        pass
