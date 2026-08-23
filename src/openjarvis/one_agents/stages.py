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
from typing import Any, Callable

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


def head_briefs_worker(
    head_id: str,
    worker_id: str,
    *,
    carrying_detail: str,
    briefing_detail: str,
    awaiting_detail: str,
    enqueue: Callable[[], dict[str, Any]],
    receiving_detail: str | None = None,
    extra_awaiting: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The ONE correct way to animate a head handing a brief to a worker.
    Every floor's head-to-worker handoff (IRIS->MUSE, HERMES->SCRIBE, and
    any future floor) must go through this instead of hand-rolling the
    set_stage/sleep/enqueue sequence itself.

    Bug this exists to prevent, confirmed live 2026-08-22 (IRIS->MUSE and
    HERMES->SCRIBE both had it independently): a worker's RECEIVING stage
    used to only get set inside the worker's OWN job handler, which doesn't
    run until a separate process (the job-queue worker, polling on its own
    interval) actually dequeues the job -- by which point the head had
    already finished its own BRIEFING pause and moved on to walking back.
    The building visibly showed the head leaving before the worker ever
    reacted, on every single head/worker pair that had its own copy of this
    logic. Setting the worker's RECEIVING stage HERE, synchronously, at the
    exact moment the head's BRIEFING stage is set, is what makes both
    agents animate standing together instead of sequentially with a gap.

    ``enqueue`` is called once, after the briefing pause, and must return
    the queued job dict (with an ``"id"`` key) -- exactly what
    ``enqueue_job(...)`` already returns. This keeps the actual queueing
    call (whose arguments differ per floor) in the caller, while this
    function owns the choreography around it.

    The paired worker-side call is ``worker_confirms_receipt`` below --
    call that at the top of the worker's job handler instead of calling
    ``set_stage(worker_id, RECEIVING, ...)`` directly there, so nobody
    re-adds a redundant second sleep on the worker's side.
    """
    set_stage(head_id, CARRYING_TO_WORKER, carrying_detail, worker=worker_id)
    time.sleep(float(os.environ.get("ONE_HANDOFF_SECONDS", "6")))

    set_stage(head_id, BRIEFING, briefing_detail, worker=worker_id)
    set_stage(worker_id, RECEIVING, receiving_detail or briefing_detail)
    time.sleep(float(os.environ.get("ONE_BRIEFING_SECONDS", "8")))

    worker_job = enqueue()

    extra = dict(extra_awaiting or {})
    extra.setdefault("worker", worker_id)
    extra["worker_job"] = worker_job["id"]
    set_stage(head_id, AWAITING_WORKER, awaiting_detail, **extra)

    return worker_job


def worker_confirms_receipt(worker_id: str, detail: str) -> None:
    """Call this at the very start of a worker's job handler (the function
    the job queue dispatches to once it dequeues the job), instead of
    calling ``set_stage(worker_id, RECEIVING, ...)`` directly there.

    Deliberately does NOT sleep: the RECEIVING visual pause already
    happened synchronously on the head's side, inside
    ``head_briefs_worker``, before this job was even enqueued. This just
    refreshes the detail text with whatever the worker itself now knows
    (e.g. a freshly-parsed brief) once it actually starts processing —
    existing as a named function (instead of a bare ``set_stage`` call) so
    that "don't sleep here, the pause already happened" is documented once,
    centrally, rather than relying on a comment at every call site.
    """
    set_stage(worker_id, RECEIVING, detail)
