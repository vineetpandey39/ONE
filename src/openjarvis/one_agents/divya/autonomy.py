"""Fail-closed daily controls for the Shloka By Shloka production lane.

This module owns the clock-facing concerns only: one mission per IST day,
host readiness, a weekly Music credit reservation and operator alerts.  It
does not turn a review gate into an approval and never publishes a video.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .core import Blocked, read, write
from .daily import create_daily_mission
from .floor12 import BRAND, CHANNEL
from .live_worker import LANE

IST = ZoneInfo("Asia/Kolkata")


def default_policy_path() -> Path:
    override = os.environ.get("SHLOKA_AUTONOMY_POLICY", "").strip()
    if override:
        return Path(override)
    return Path("E:/ONE-Suite/one-company/floors/floor_12_youtube_studio/shloka_autonomy.json")


def load_policy(path: Path | None = None) -> dict[str, Any]:
    policy = read(path or default_policy_path())
    if policy.get("schema") != "one.shloka-autonomy/v1":
        raise Blocked("Shloka autonomy policy schema is missing or unsupported")
    if policy.get("brand") != BRAND or policy.get("channel_id") != CHANNEL:
        raise Blocked("Shloka autonomy policy is bound to the wrong brand or channel")
    return policy


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _week_key(moment: datetime | None = None) -> str:
    local = (moment or datetime.now(timezone.utc)).astimezone(IST)
    year, week, _ = local.isocalendar()
    return f"{year}-W{week:02d}"


def _ledger(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS music_reservations(
        mission_id TEXT PRIMARY KEY, week_key TEXT NOT NULL,
        credits INTEGER NOT NULL, state TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS ix_music_week ON music_reservations(week_key);
    """)
    return db


def reserve_music_credits(policy: dict[str, Any], mission_id: str, credits: int,
                          *, ledger_path: Path | None = None,
                          moment: datetime | None = None) -> dict[str, Any]:
    """Atomically reserve the only allowed paid attempt for a mission.

    A reservation remains consumed for UNKNOWN/BLOCKED provider outcomes.
    Releasing it could turn a network ambiguity into a second paid request.
    """
    limit = int(policy.get("weekly_music_credit_ceiling") or 0)
    credits = int(credits)
    if limit <= 0:
        raise Blocked("Weekly ElevenLabs Music credit ceiling has not been approved")
    if credits <= 0:
        raise Blocked("Exact Music credit estimate is required before submission")
    if credits > limit:
        raise Blocked("Music request exceeds the approved weekly credit ceiling")
    path = ledger_path or Path(policy["state_root"]) / "music-credits.sqlite3"
    week = _week_key(moment)
    with closing(_ledger(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute(
            "SELECT * FROM music_reservations WHERE mission_id=?", (mission_id,)
        ).fetchone()
        if prior:
            raise Blocked("A Music attempt is already reserved for this mission; paid retry refused")
        used = int(db.execute(
            "SELECT COALESCE(SUM(credits),0) FROM music_reservations WHERE week_key=?",
            (week,),
        ).fetchone()[0])
        if used + credits > limit:
            raise Blocked("Weekly ElevenLabs Music credit ceiling would be exceeded")
        now = _now_iso()
        db.execute(
            "INSERT INTO music_reservations VALUES(?,?,?,?,?,?)",
            (mission_id, week, credits, "RESERVED", now, now),
        )
    return {"mission_id": mission_id, "week_key": week, "reserved_credits": credits,
            "weekly_ceiling": limit, "remaining_after_reservation": limit - used - credits}


def mark_music_outcome(policy: dict[str, Any], mission_id: str, state: str,
                       *, ledger_path: Path | None = None) -> None:
    allowed = {"COMPLETE", "BLOCKED", "OUTCOME_UNKNOWN"}
    if state not in allowed:
        raise ValueError("Unsupported Music outcome")
    path = ledger_path or Path(policy["state_root"]) / "music-credits.sqlite3"
    with closing(_ledger(path)) as db, db:
        changed = db.execute(
            "UPDATE music_reservations SET state=?,updated_at=? WHERE mission_id=?",
            (state, _now_iso(), mission_id),
        ).rowcount
        if not changed:
            raise Blocked("Music outcome has no matching credit reservation")


def host_readiness(policy: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    host = policy.get("host") or {}
    failures: list[str] = []
    for raw in host.get("required_files", []):
        if not Path(raw).is_file():
            failures.append(f"missing file: {raw}")
    heartbeat = Path(str(host.get("worker_heartbeat") or ""))
    max_age = int(host.get("heartbeat_max_age_seconds") or 120)
    if not heartbeat.is_file():
        failures.append("Shloka worker heartbeat is missing")
    else:
        try:
            status = read(heartbeat)
            age = float(now if now is not None else time.time()) - float(status["heartbeat"])
            if age > max_age or status.get("state") == "STOPPED":
                failures.append(f"Shloka worker heartbeat is stale ({age:.0f}s)")
        except (KeyError, TypeError, ValueError, OSError):
            failures.append("Shloka worker heartbeat is unreadable")
    return {"status": "READY" if not failures else "BLOCKED", "failures": failures,
            "host_id": host.get("host_id"), "checked_at": _now_iso()}


def alert(policy: dict[str, Any], code: str, message: str, **details: Any) -> dict[str, Any]:
    """Write a durable alert and optionally mirror it to a secret webhook."""
    root = Path(policy["state_root"])
    root.mkdir(parents=True, exist_ok=True)
    item = {"created_at": _now_iso(), "brand": BRAND, "channel_id": CHANNEL,
            "code": code, "message": message, "details": details}
    with (root / "alerts.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    write(root / "latest-alert.json", item)
    env_name = str((policy.get("alerts") or {}).get("webhook_env") or "")
    endpoint = os.environ.get(env_name, "").strip() if env_name else ""
    item["remote_delivery"] = "NOT_CONFIGURED"
    if endpoint:
        try:
            body = json.dumps(item, ensure_ascii=False).encode("utf-8")
            request = Request(endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=10) as response:  # nosec - operator-configured secret endpoint
                if not 200 <= response.status < 300:
                    raise OSError(f"HTTP {response.status}")
            item["remote_delivery"] = "DELIVERED"
        except Exception as exc:  # alert transport must never hide the production fault
            item["remote_delivery"] = f"FAILED:{type(exc).__name__}"
    return item


def commission_daily(job: dict[str, Any], enqueue: Callable[..., dict[str, Any]],
                     *, policy_path: Path | None = None,
                     day: date | None = None) -> dict[str, Any]:
    """Create and queue exactly one no-spend daily mission for the live lane."""
    policy = load_policy(policy_path)
    if policy.get("enabled") is not True:
        raise Blocked("Shloka autonomy is disabled in policy")
    ready = host_readiness(policy)
    if ready["status"] != "READY":
        alert(policy, "HOST_NOT_READY", "Daily Shloka mission was not started", failures=ready["failures"])
        raise Blocked("Always-on production host is not ready")
    production_day = day or datetime.now(IST).date()
    root = Path(policy["output_root"]) / f"shloka-daily-{production_day.isoformat()}"
    topic = str(policy.get("default_topic") or "Lakshmi")
    created = create_daily_mission(root, day=production_day, deity=topic)
    mission = read(root / "mission.json")
    estimate = int(policy.get("estimated_music_credits_per_job") or 0)
    if int(policy.get("weekly_music_credit_ceiling") or 0) < estimate or estimate <= 0:
        alert(policy, "CREDIT_POLICY_BLOCK", "Mission prepared but Music was not authorized",
              mission_id=mission["mission_id"], estimate=estimate)
        raise Blocked("Approved credit ceiling/estimate is missing or insufficient")
    payload = {"brand": BRAND, "channel_id": CHANNEL, "mission_id": mission["mission_id"],
               "root": str(root), "action": "verify_pipeline", "execution_lane": LANE,
               "origin_job": str(job.get("id") or "daily-clock")}
    queued = enqueue("helios", json.dumps(payload, ensure_ascii=False), mode="execute", tier="heavy",
                     dedupe_key=f"shloka:daily:{production_day.isoformat()}", reserved=True)
    write(Path(policy["state_root"]) / "latest-commission.json",
          {"created_at": _now_iso(), "production_date": production_day.isoformat(),
           "mission_id": mission["mission_id"], "root": str(root), "job_id": queued["id"]})
    return {"status": "QUEUED", "mission": created, "root": str(root),
            "job_id": queued["id"], "published": False, "cost_credits": 0}
