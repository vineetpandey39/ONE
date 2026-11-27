"""Exact-job recovery for a registry refusal before company dispatch."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from . import floors_bridge, helios_repair_coordination, runtime

IST = timezone(timedelta(hours=5, minutes=30))
TRIGGER = "daily-sonia-job-hunt"


def resume_registry_refusal(job_id: str, evidence_dir: Path) -> dict:
    """Reserve a linked attempt, retaining the exact task and original authority.

    This contract covers only an explicit pre-dispatch registry denial. Other
    failures need their own checkpoint reconciliation and cannot use this API.
    """
    previous = runtime.get_job(job_id)
    if not previous:
        raise ValueError("job not found")
    with helios_repair_coordination.external_repair_guard(runtime._connect, previous):
        with closing(runtime._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            result = json.loads(row.get("result") or "{}")
            # An exact-ID retry can be refused by the global execution ledger.
            # Only accept that state when the immutable pre-resume snapshot
            # proves the original failure happened before company dispatch.
            snapshot = Path(evidence_dir) / f"{job_id}.before-resume.json"
            if row["status"] == "completed" and result.get("governed") == "refused" and row.get("resume_count") == 1:
                original = json.loads(snapshot.read_text(encoding="utf-8"))
                if any(original.get(k) != row.get(k) for k in ("id", "task", "agent_id", "created_at", "error")):
                    raise ValueError("original evidence does not bind this job")
                row = original
                result = json.loads(row.get("result") or "{}")
            error = row.get("error") or ""
            if (row["agent_id"] != "poseidon" or row["status"] != "blocked"
                    or row["mode"] != "execute" or row.get("resume_count", 0)
                    or "DENIED_BY_ABSENCE" not in error or "floors.index.json is stale" not in error
                    or result.get("company_job_id") or row.get("external_job")
                    or result.get("blocked_reason") != error):
                raise ValueError("not a first pre-dispatch registry refusal")
            today = datetime.now(IST).date()
            if datetime.fromisoformat(row["created_at"]).astimezone(IST).date() != today:
                raise ValueError("past-day job cannot resume")
            if not runtime._job_fired_by_trigger(TRIGGER, job_id):
                raise ValueError("original trigger receipt missing")
            registry = floors_bridge.registry()
            if registry is None:
                raise ValueError("registry still unavailable")
            if db.execute("SELECT 1 FROM jobs WHERE agent_id='poseidon' AND id!=? "
                          "AND status IN ('queued','reserved','running')", (job_id,)).fetchone():
                raise ValueError("POSEIDON already has active work")
            company = runtime._home() / "company_jobs.db"
            with closing(sqlite3.connect(company.as_uri() + "?mode=ro", uri=True)) as company_db:
                cycles = company_db.execute(
                    "SELECT job_id,status,created_at FROM jobs WHERE assigned_to='poseidon' "
                    "AND floor_id='1' AND objective LIKE '%Sonia%job hunt%'"
                ).fetchall()
            for cycle_id, status, created in cycles:
                if (status not in ('completed', 'cancelled')
                        or datetime.fromisoformat(created).astimezone(IST).date() == today):
                    raise ValueError(f"company cycle requires reconciliation: {cycle_id} ({status})")
            evidence_dir = Path(evidence_dir)
            evidence_dir.mkdir(parents=True, exist_ok=True)
            snapshot = evidence_dir / f"{job_id}.before-resume.json"
            if not snapshot.exists():
                with snapshot.open('x', encoding='utf-8') as stream:
                    json.dump(row, stream, indent=2)
            db.rollback()
        key = f"poseidon-registry-recovery:{job_id}"
        queued = runtime.enqueue_job(row['agent_id'], row['task'], mode=row['mode'],
                                     tier=row.get('tier', 'fast'), dedupe_key=key, reserved=True)
        receipt = {'original_job_id': job_id, 'recovery_job_id': queued['id'],
                   'trigger_id': TRIGGER, 'task_unchanged': queued['task'] == row['task'],
                   'reason': 'verified registry repair after pre-dispatch denial'}
        (evidence_dir / 'recovery-link.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return queued
