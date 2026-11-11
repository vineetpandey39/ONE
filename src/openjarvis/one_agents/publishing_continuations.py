"""Durable publishing follow-ups discovered from the queue, not HOME or timers."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def tick(connect, enqueue, *, now=None):
    now = now or datetime.now(timezone.utc).timestamp()
    with connect() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT id,agent_id,status,task,updated_at FROM jobs "
            "WHERE agent_id IN ('imprimatur','metron') ORDER BY created_at DESC")]
    latest, active = {}, set()
    for row in rows:
        try:
            payload = json.loads(row["task"])
            root = str(payload.get("run_dir") or "")
            if not root:
                continue
            key = (row["agent_id"], root)
            if row["status"] in {"queued", "reserved", "running", "awaiting_login"}:
                active.add(key)
            latest.setdefault(key, (row, payload))
        except (TypeError, ValueError):
            continue
    queued, errors = [], []
    for key, (row, payload) in latest.items():
        if key in active:
            continue
        agent, root = key
        if row["status"] in {"failed", "blocked", "cancelled"}:
            continue
        path = Path(root) / ("kdp_publish_state.json" if agent == "imprimatur" else "marketing/measurement.json")
        try:
            if not path.is_file():
                continue
            state = json.loads(path.read_text(encoding="utf-8"))
            if agent == "imprimatur":
                if state.get("stage") not in {"SUBMITTED", "AWAITING_ASIN"}:
                    continue
                if str(state.get("kdp_status", "")).lower() in {"blocked", "draft"}:
                    continue
                source = state.get("scribe_job_id") or payload.get("scribe_job_id")
                if not source:
                    errors.append({"run_dir": root, "error": "Missing SCRIBE identity"})
                    continue
                updated = datetime.fromisoformat(state["updated_at"]).timestamp()
                if now < updated + float(state.get("next_check_seconds", 1800)):
                    continue
                task = {"phase": "poll", "run_dir": root, "scribe_job_id": source,
                        "approval_id": state.get("approval_id") or payload.get("approval_id", ""),
                        "poll_attempt": int(state.get("poll_attempt", 0)), "recovered_after_restart": True}
                cycle = state["updated_at"]
            else:
                if now < float(state["next_review_epoch"]):
                    continue
                task = {k: v for k, v in payload.items() if k != "metrics"}
                task["phase"] = "measurement_review"
                cycle = str(state["next_review_epoch"])
            identity = hashlib.sha256(f"{agent}|{root}|{cycle}".encode()).hexdigest()
            queued.append(enqueue(agent, json.dumps(task), mode="execute", tier="fast",
                                  dedupe_key=f"publishing-continuation:{identity}")["id"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append({"run_dir": root, "error": str(exc)})
    return {"queued": queued, "errors": errors}
