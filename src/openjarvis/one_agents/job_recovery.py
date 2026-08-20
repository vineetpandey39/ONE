"""Restart-safe recovery for jobs blocked on an external system.

The problem this exists for
---------------------------
SCRIBE and MUSE start a job inside LAO and then block, polling it, for as long
as the work actually takes - up to three hours for a book. That poll loop lives
in a thread inside the worker process. When the process restarts, the thread
dies, but three things do not:

  - the row in agent_queue.db, which stays 'running' forever, because
    claim_job() only ever selects rows with status 'queued'
  - the stage record, which keeps showing the agent busy on work nobody is
    doing
  - the LAO job itself, which carries on and finishes into a folder that
    nothing collects

Every MUSE run and most SCRIBE runs died this way. The book or reel often
existed; the company simply never found out.

The approach
------------
A handler that starts external work *attaches* the external job id to its own
row, and heartbeats while it polls. At worker startup, sweep() looks at every
row still marked 'running':

  - stale heartbeat and an attached external id -> put it back to 'queued'.
    The handler sees the attached id and re-attaches to the existing external
    job rather than starting a second one, so recovery reuses the ordinary
    dispatch path instead of a parallel one.
  - stale heartbeat and no external id -> fail it. Re-queuing here could start
    duplicate external work, and a duplicate three-hour book run is worse than
    an honest failure.
  - fresh heartbeat -> leave it alone. Another worker is on it.

resume_count caps how often one job may be resumed, so a job that orphans on
every restart eventually fails instead of cycling forever.

Nothing here talks to LAO. Deciding whether the external job is still alive is
the handler's business; this module only decides whether a row deserves
another go.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

# Added to the jobs table the same additive way `tier` was: check
# PRAGMA table_info, ALTER only what is missing, tolerate a race with another
# worker. No existing column is touched and no data is rewritten.
COLUMNS: dict[str, str] = {
    "external_job": "TEXT NOT NULL DEFAULT ''",
    "external_kind": "TEXT NOT NULL DEFAULT ''",
    "heartbeat_at": "TEXT NOT NULL DEFAULT ''",
    "resume_count": "INTEGER NOT NULL DEFAULT 0",
}

DEFAULT_STALE_AFTER = 300.0     # seconds without a heartbeat before orphaned
DEFAULT_MAX_RESUMES = 2

Connect = Callable[[], sqlite3.Connection]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_seconds(stamp: str, now: float | None = None) -> float:
    """Seconds since an ISO timestamp. A missing or unparseable stamp reads as
    infinitely old, which is the safe direction: it means 'treat as orphaned'
    rather than 'assume someone is working on it'."""
    if not stamp:
        return float("inf")
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return float("inf")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    reference = now if now is not None else time.time()
    return reference - moment.timestamp()


def ensure_columns(connection: sqlite3.Connection) -> None:
    """Add the recovery columns if they are missing. Safe to call on every
    connection; safe to lose the race to another worker."""
    existing = {row["name"] if isinstance(row, sqlite3.Row) else row[1]
                for row in connection.execute("PRAGMA table_info(jobs)").fetchall()}
    for name, definition in COLUMNS.items():
        if name in existing:
            continue
        try:
            connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
        except sqlite3.OperationalError:
            pass  # another worker added it between the read and the write


def attach(connect: Connect, job_id: str, external_id: str, kind: str = "lao") -> None:
    """Record that this job now owns an external job, and start its heartbeat.

    Call this immediately after the external system returns an id - before the
    first poll, not after it. The window between 'started it' and 'recorded it'
    is exactly the window where a restart loses the reference.
    """
    if not external_id:
        return
    with closing(connect()) as db, db:
        db.execute(
            "UPDATE jobs SET external_job = ?, external_kind = ?, heartbeat_at = ?, "
            "updated_at = ? WHERE id = ?",
            (external_id, kind, _now(), _now(), job_id),
        )


def detach(connect: Connect, job_id: str) -> None:
    """Clear the external reference once the work is genuinely finished, so a
    later sweep cannot mistake a completed row for something to resume."""
    with closing(connect()) as db, db:
        db.execute(
            "UPDATE jobs SET external_job = '', external_kind = '', heartbeat_at = '' "
            "WHERE id = ?",
            (job_id,),
        )


def heartbeat(connect: Connect, job_id: str) -> None:
    """Say 'still here' from inside a poll loop. Best-effort: a failed
    heartbeat must never break the work it is reporting on."""
    try:
        with closing(connect()) as db, db:
            db.execute("UPDATE jobs SET heartbeat_at = ? WHERE id = ?", (_now(), job_id))
    except sqlite3.Error:
        pass


def resume_target(job: dict[str, Any] | sqlite3.Row) -> str:
    """The external id a handler should re-attach to, or '' for a fresh start.

    Handlers call this instead of reading the column directly, so 'am I a
    resume?' is one obvious question with one answer.
    """
    try:
        return str(job["external_job"] or "")
    except (KeyError, IndexError, TypeError):
        return ""


def sweep(
    connect: Connect,
    *,
    stale_after: float = DEFAULT_STALE_AFTER,
    max_resumes: int = DEFAULT_MAX_RESUMES,
    now: float | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Deal with every job left 'running' by a dead worker.

    Returns what it did, so the caller can clear stale stages and log it:
        {"resumed": [...], "failed": [...], "left": [...]}
    Each entry carries id, agent_id and external_job.
    """
    resumed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    left: list[dict[str, Any]] = []

    with closing(connect()) as db, db:
        ensure_columns(db)
        rows = db.execute("SELECT * FROM jobs WHERE status = 'running'").fetchall()
        for row in rows:
            entry = {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "external_job": str(row["external_job"] or ""),
                "resume_count": int(row["resume_count"] or 0),
            }
            if _age_seconds(str(row["heartbeat_at"] or ""), now) < stale_after:
                left.append(entry)
                continue

            if entry["external_job"] and entry["resume_count"] < max_resumes:
                db.execute(
                    "UPDATE jobs SET status = 'queued', progress = 0, "
                    "resume_count = resume_count + 1, heartbeat_at = '', updated_at = ? "
                    "WHERE id = ? AND status = 'running'",
                    (_now(), row["id"]),
                )
                entry["resume_count"] += 1
                resumed.append(entry)
                continue

            if entry["external_job"]:
                reason = (
                    f"Orphaned by a restart and already resumed {entry['resume_count']} "
                    f"time(s), which is the limit. The external {row['external_kind'] or 'job'} "
                    f"{entry['external_job']} may still be running or may have finished; "
                    "check it by hand before re-running this."
                )
            else:
                reason = (
                    "Orphaned by a restart before it recorded an external job. Not resumed "
                    "on purpose: re-running it could start a second copy of work that may "
                    "already be underway."
                )
            db.execute(
                "UPDATE jobs SET status = 'failed', error = ?, updated_at = ? "
                "WHERE id = ? AND status = 'running'",
                (reason, _now(), row["id"]),
            )
            entry["reason"] = reason
            failed.append(entry)

    return {"resumed": resumed, "failed": failed, "left": left}


def describe(summary: dict[str, list[dict[str, Any]]]) -> str:
    """One line for the log. Silent when there was nothing to do."""
    parts: list[str] = []
    for kind in ("resumed", "failed"):
        items: Iterable[dict[str, Any]] = summary.get(kind, [])
        names = [f"{i['id']}" for i in items]
        if names:
            parts.append(f"{kind}: {', '.join(names)}")
    return "; ".join(parts)
