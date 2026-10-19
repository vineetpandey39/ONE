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
AWAITING_UPLOAD = "awaiting_upload"  # work is done; blocked on a human's real-world action (e.g. KDP upload)

_TERMINAL = {IDLE}

# Stages that outlive the process that set them, on purpose. AWAITING_UPLOAD
# means "the agent is finished and a human now owes a real-world action" (the
# KDP upload), so it has to survive restarts -- that bubble is the reminder.
# Everything else describes work in flight and cannot outlive its process.
_DURABLE = {AWAITING_UPLOAD}

# How long an entry written before stages carried owner information is trusted.
# Anything volatile and older than this from the pre-owner format is a leftover.
_LEGACY_GRACE_SECONDS = 900


def _owner() -> dict[str, Any]:
    """Identify the process writing a stage, so a reader can tell whether that
    process is still alive. The boot time guards against PID reuse."""
    try:
        import psutil

        return {"pid": os.getpid(), "boot": psutil.Process().create_time()}
    except Exception:  # noqa: BLE001 - never block a stage write
        return {"pid": os.getpid()}


def _owner_alive(owner: Any) -> bool:
    """True unless the writing process is provably gone. Errs towards keeping
    the stage: a wrong "alive" shows a stale bubble for a while, a wrong "dead"
    erases an agent that is actually working."""
    if not isinstance(owner, dict) or not owner.get("pid"):
        return True
    try:
        import psutil

        process = psutil.Process(int(owner["pid"]))
        boot = owner.get("boot")
        if boot is None:
            return True
        # Same PID, different start time: the original process died and the OS
        # handed its number to something else.
        return abs(process.create_time() - float(boot)) < 1.0
    except Exception as exc:  # noqa: BLE001
        try:
            import psutil

            if isinstance(exc, psutil.NoSuchProcess):
                return False
        except Exception:  # noqa: BLE001
            pass
        return True


def _home() -> Path:
    return Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))


def _path() -> Path:
    path = _home() / "agent_stages.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_stages() -> dict[str, dict[str, Any]]:
    """Every agent's current stage. Never raises — a missing or corrupt file
    just means 'nobody is mid-flow', which is the correct default.

    Stages whose writing process is gone are dropped here. A stage used to be
    a write-only latch: the only thing that cleared it was the same process
    reaching its own ``clear_stage``, so any crash, restart or external kill
    stranded that bubble on the building permanently. Confirmed live
    2026-10-02 -- FABULA sat in EXECUTING with no job of its own anywhere in
    the queue, because whatever set it was killed before its ``finally`` ran,
    and the worker had since restarted. Filtering on read means every consumer
    (the HTTP route, floor watch, the handoff checks) is fixed at once, and
    the file self-heals on the next write.
    """
    try:
        stages = json.loads(_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(stages, dict):
        return {}
    now = time.time()
    live: dict[str, dict[str, Any]] = {}
    for agent_id, entry in stages.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("stage") in _DURABLE:
            live[agent_id] = entry
            continue
        owner = entry.get("owner")
        if owner is None:
            # Pre-owner format: trust it briefly, then treat it as abandoned.
            if now - float(entry.get("since") or 0) < _LEGACY_GRACE_SECONDS:
                live[agent_id] = entry
            continue
        if _owner_alive(owner):
            live[agent_id] = entry
    return live


def set_stage(agent_id: str, stage: str, detail: str = "", **extra: Any) -> None:
    """Record an agent's stage. Best-effort: a failure here must never take
    down the job that is actually doing the work."""
    try:
        stages = get_stages()
        if agent_id == 'yatra' and stage not in _TERMINAL:
            try:
                progress = json.loads((_home() / 'yatra_progress.json').read_text(encoding='utf-8'))
                counters = (f"Envato sources {progress.get('envato_done', 0)}/{progress.get('envato_total', '?')} | "
                            f"OBS {progress.get('obs_done', 0)}/{progress.get('obs_total', '?')} | "
                            f"Edit {progress.get('edit_done', 0)}/{progress.get('edit_total', '?')}")
                detail = counters + ' — ' + detail
                extra['progress'] = progress
            except (OSError, ValueError):
                pass
        if stage in _TERMINAL:
            stages.pop(agent_id, None)
        else:
            stages[agent_id] = {
                "stage": stage,
                "detail": detail,
                "since": time.time(),
                # Who to ask about this stage later. Without it a reader cannot
                # tell a long-running job from a process that died mid-flow.
                "owner": _owner(),
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


def worker_finished(head_id: str, worker_job_id: str) -> bool:
    """Release a head that is still AWAITING_WORKER on this exact worker job.

    For one-shot errands that never send a report leg back to the head (ECHO's
    hourly comment sweep, the daily community poll). Without it the head's
    "Waiting on ECHO ..." bubble outlived the finished job for good, because
    the stage's owner (the worker process) is still alive (seen live
    2026-10-09 after the first community poll was posted). A head that has
    since moved on to other work is left alone.
    """
    entry = get_stages().get(head_id) or {}
    if entry.get("stage") == AWAITING_WORKER and entry.get("worker_job") == worker_job_id:
        clear_stage(head_id)
        return True
    return False
