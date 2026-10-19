"""Exit 1 if any job is currently 'running' in the given agent_queue.db, else 0.

Used by start-one.ps1's runtime.py mtime-restart check: that check used to
Stop-Process -Force the worker unconditionally whenever runtime.py looked
newer than the running process, with no regard for a job in flight. Once
ONE-AutoRestart made start-one.ps1 fire every 5 minutes on its own, that hard
kill could land mid-job. This lets the caller defer the restart by one cycle
instead.
"""
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path


def restart_blockers(queue_db: str, trigger_db: str | None = None,
                     horizon_seconds: int = 600) -> list[str]:
    blockers: list[str] = []
    with closing(sqlite3.connect(queue_db)) as con:
        rows = con.execute(
            "SELECT id,agent_id,status,mode FROM jobs "
            "WHERE status='running' OR (status='queued' AND mode!='watch')"
        ).fetchall()
    blockers.extend(f"job {row[0]} ({row[1]} {row[2]})" for row in rows)

    if trigger_db and Path(trigger_db).is_file():
        deadline = time.time() + max(0, horizon_seconds)
        with closing(sqlite3.connect(trigger_db)) as con:
            rows = con.execute(
                "SELECT id,next_fire_epoch FROM triggers "
                "WHERE enabled=1 AND next_fire_epoch<=? ORDER BY next_fire_epoch",
                (deadline,),
            ).fetchall()
        blockers.extend(f"trigger {row[0]} due in {max(0, int(row[1] - time.time()))}s" for row in rows)
    return blockers


def main(argv: list[str]) -> int:
    queue_db = argv[1]
    trigger_db = argv[2] if len(argv) > 2 else None
    horizon = int(argv[3]) if len(argv) > 3 else 600
    blockers = restart_blockers(queue_db, trigger_db, horizon)
    for blocker in blockers:
        print(f"restart deferred: {blocker}")
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
