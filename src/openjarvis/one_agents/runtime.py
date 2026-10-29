"""Durable, local-first runtime for ONE's named agents."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from openjarvis.one_agents import (
    floor_watch, floors_bridge, job_recovery, linkedin_growth, memory, publishing_strategy, stages,
)


AGENTS: dict[str, dict[str, str]] = {
    "helios": {"name": "HELIOS", "role": "Multi-channel YouTube commissioning, resource coordination and delivery reconciliation head", "floor_id": "12", "floor_name": "YouTube Studio", "division": "youtube_studio", "seat": "head"},
    "zeus": {"name": "ZEUS", "role": "Cross-division orchestration, escalation, and resource-allocation operator", "floor_id": "11", "floor_name": "ONE-JARVIS Executive Command", "division": "executive"},
    "athena": {"name": "ATHENA", "role": "Opportunity discovery, research, and scoring operator", "floor_id": "10", "floor_name": "Venture & Opportunity Lab", "division": "venture_lab"},
    "jobhunt": {"name": "DAEDALUS", "role": "Micro-SaaS and AI product build/QA operator", "floor_id": "9", "floor_name": "Micro-SaaS & AI Product Factory", "division": "micro_saas"},
    "titan": {"name": "TITAN", "role": "Apps, websites, and games build/ship operator", "floor_id": "8", "floor_name": "Apps / Websites / Games", "division": "apps_web_games"},
    "beta": {"name": "BETA", "role": "Browser extensions, plugins, and utility-tools delivery operator", "floor_id": "7", "floor_name": "Digital Utilities", "division": "digital_utilities"},
    "apollo": {"name": "APOLLO", "role": "Courses, templates, and digital-product operator", "floor_id": "6", "floor_name": "Digital Products & Education", "division": "digital_products"},
    "hermes": {"name": "HERMES", "role": "KDP authority-catalogue research and publishing operator", "floor_id": "5", "floor_name": "Book Publishing (KDP)", "division": "publishing", "seat": "head"},
    # First worker agent under a floor head — sits at an open desk on Floor 5
    # and is the one that actually drives LAO's KDP factory to completion.
    "scribe": {"name": "SCRIBE", "role": "KDP manuscript production worker", "floor_id": "5", "floor_name": "Book Publishing (KDP)", "division": "publishing", "seat": "worker", "reports_to": "hermes"},
    "biblos": {"name": "BIBLOS", "role": "Publishing demand validation and commercial scoring worker", "floor_id": "5", "floor_name": "Book Publishing (KDP)", "division": "publishing", "seat": "worker", "reports_to": "hermes"},
    "mercury": {"name": "MERCURY", "role": "Publishing rights and distribution-route worker", "floor_id": "5", "floor_name": "Book Publishing (KDP)", "division": "publishing", "seat": "worker", "reports_to": "hermes"},
    "imprimatur": {"name": "IMPRIMATUR", "role": "Governed KDP draft upload, submission, and ASIN monitoring worker", "floor_id": "5", "floor_name": "Book Publishing (KDP)", "division": "publishing", "seat": "worker", "reports_to": "hermes"},
    "leda": {"name": "LEDA", "role": "Consent-safe reader audience worker", "floor_id": "5", "floor_name": "Book Publishing (KDP)", "division": "publishing", "seat": "worker", "reports_to": "hermes"},
    "metron": {"name": "METRON", "role": "Publishing measurement and attribution worker", "floor_id": "5", "floor_name": "Book Publishing (KDP)", "division": "publishing", "seat": "worker", "reports_to": "hermes"},
    # Floor 5's second worker, added 2026-08-26. Starts only after HERMES
    # reports a finished book (the report leg SCRIBE hands back), same
    # dual-worker-under-one-head shape as IRIS/MUSE/KAIROS on Floor 4.
    # Deliberately a stub for now -- it proves the seat (receives the
    # handoff, notes the book, clears back to idle) without inventing the
    # actual lead-generation logic, which is a separate, later step.
    "peitho": {"name": "PEITHO", "role": "KDP lead-generation and marketing worker", "floor_id": "5", "floor_name": "Book Publishing (KDP)", "division": "publishing", "seat": "worker", "reports_to": "hermes"},
    "ia": {"name": "IRIS", "role": "Media and content production/distribution operator across ImagineIndia and future brands", "floor_id": "4", "floor_name": "Media & Content (ImagineIndia)", "division": "media", "seat": "head"},
    # Floor 4's worker seat, added 2026-08-14 -- deliberately the same
    # arrangement as HERMES/SCRIBE one floor up: IRIS decides what to shoot,
    # MUSE actually drives LAO's ImagineIndia reel pipeline to completion and
    # walks the finished reel back. ImagineIndia's own 3x/day LAO triggers are
    # untouched; this is a second, on-demand way to run it through the floor.
    "muse": {"name": "MUSE", "role": "ImagineIndia reel production worker", "floor_id": "4", "floor_name": "Media & Content (ImagineIndia)", "division": "media", "seat": "worker", "reports_to": "ia"},
    # Floor 4's second worker, added 2026-08-19. IRIS now serves two brands:
    # MUSE produces ImagineIndia reels, KAIROS produces posts for the founder's
    # own @aibyvineet channel. Which one gets a job is decided by the brand
    # router in one-company/floors/floor_04_media, never by preference order --
    # guessing wrong here means posting to the wrong account.
    "kairos": {"name": "KAIROS", "role": "aibyvineet carousel worker and Floor 4 revenue agent: turns @imagineindia.ai and @aibyvineet reach into income - money-funnel reviews, brand deals, media kits, affiliate and product plans (drafts only, sends nothing without the Chairman)", "floor_id": "4", "floor_name": "Media & Content", "division": "media", "seat": "worker", "reports_to": "ia"},
    "herald": {"name": "HERALD", "role": "LinkedIn authority-post production and publishing worker (Growth floor, reports to ARES)", "floor_id": "3", "floor_name": "Growth & Distribution", "division": "growth", "seat": "worker", "reports_to": "ares"},
    "chandan": {"name": "CHANDAN", "role": "Origin to Ovation biography production worker; reuses approved assets and hands completed masters to ARES", "floor_id": "12", "floor_name": "YouTube Studio", "division": "youtube_studio", "seat": "worker", "reports_to": "helios"},
    "planexium": {"name": "PLANEXIUM", "role": "The Planexium science production worker using local Windows narration and shared services", "floor_id": "12", "floor_name": "YouTube Studio", "division": "youtube_studio", "seat": "worker", "reports_to": "helios"},
    "yatra": {"name": "YATRA", "role": "Sonia Travel Vlogs Envato acquisition, OBS capture and video assembly worker", "floor_id": "12", "floor_name": "YouTube Studio", "division": "youtube_studio", "seat": "worker", "reports_to": "helios"},
    "fabula": {"name": "FABULA", "role": "YouTube narration production and approved voice checkpoint worker", "floor_id": "12", "floor_name": "YouTube Studio", "division": "youtube_studio", "seat": "worker", "reports_to": "helios"},
    "lyra": {"name": "LYRA", "role": "YouTube SEO, metadata and thumbnail experiment packaging specialist", "floor_id": "12", "floor_name": "YouTube Studio", "division": "youtube_studio", "seat": "worker", "reports_to": "helios"},
    "echo": {"name": "ECHO", "role": "YouTube subtitles, localization, comments and governed upload completion worker", "floor_id": "12", "floor_name": "YouTube Studio", "division": "youtube_studio", "seat": "worker", "reports_to": "helios"},
    "vista": {"name": "VISTA", "role": "YouTube vertical short-form production worker; consumes HELIOS research and produces governed Shorts", "floor_id": "12", "floor_name": "YouTube Studio", "division": "youtube_studio", "seat": "worker", "reports_to": "helios"},
    "ares": {"name": "ARES", "role": "SEO, social, and cross-floor distribution operator", "floor_id": "3", "floor_name": "Growth & Distribution", "division": "growth"},
    "alfa": {"name": "ALFA", "role": "Pricing, funnels, and revenue-attribution operator", "floor_id": "2", "floor_name": "Commerce & Monetization", "division": "commerce"},
    "poseidon": {"name": "POSEIDON", "role": "Finance, HR, Admin, and Legal/Compliance operator", "floor_id": "1", "floor_name": "Corporate Services", "division": "corporate"},
    "hephaistos": {"name": "HEPHAISTOS", "role": "ONE runtime, workflow-engine, and LAO-bridge operator", "floor_id": "B1", "floor_name": "Platform Engineering", "division": "platform"},
    "argus": {"name": "WARDEN", "role": "Health, audit, kill-switch, and rate-limit operator", "floor_id": "B2", "floor_name": "Security & SRE", "division": "security"},
}


def _home() -> Path:
    return Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))


def _db_path() -> Path:
    path = _home() / "agent_queue.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            task TEXT NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0,
            result TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_schedules (
            agent_id TEXT PRIMARY KEY,
            interval_seconds INTEGER NOT NULL,
            next_run_epoch REAL NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    existing_job_cols = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()}
    if "tier" not in existing_job_cols:
        try:
            connection.execute("ALTER TABLE jobs ADD COLUMN tier TEXT NOT NULL DEFAULT 'fast'")
        except sqlite3.OperationalError:
            pass  # Another worker already added it.
    # Columns that let a job survive the worker process dying mid-poll. Same
    # additive pattern as `tier` above; see job_recovery for what they carry.
    job_recovery.ensure_columns(connection)
    connection.commit()
    return connection


def _enqueue_floor_watches() -> None:
    """Give each floor head a recurring look at its own floor.

    Only heads whose floor actually did something recently get a watch job. A
    floor with no jobs in the lookback window has nothing to reconcile, and
    enqueuing fourteen no-op rows every interval would bury the real work in
    the job list -- the watch is supposed to make problems easier to see, not
    harder.
    """
    if os.environ.get("ONE_FLOOR_WATCH", "true").lower() not in {"1", "true", "yes", "on"}:
        return
    interval = max(300, int(os.environ.get("ONE_FLOOR_WATCH_INTERVAL_SECONDS", "1800")))
    lookback = floor_watch.DEFAULT_LOOKBACK_SECONDS
    now_epoch = time.time()
    now = _now()

    # "not a worker", not "seat == head". Only floors that actually have
    # workers bother to mark their head's seat -- today just HERMES and IRIS.
    # The other eleven floors are a single agent who IS the floor head and
    # declares no seat at all, so matching on seat == "head" scheduled two
    # watches and silently skipped eleven floors. Caught by testing every head
    # rather than the one being worked on.
    # A watch that found nothing does not need a permanent row. Its real record
    # is floor_watch's own log; the job queue is for work, and the cockpit's
    # recent-jobs strip is the one place a human looks to see what needs them.
    # Watches that DID find something keep their row -- that is the audit trail
    # worth having. Without this the strip fills with "checked, all clear"
    # cards and buries the one card that was asking for a human.
    try:
        with _connect() as db:
            db.execute(
                "DELETE FROM jobs WHERE mode = 'watch' AND status = 'completed' "
                "AND created_at < ? AND (result LIKE '%\"findings\": 0%' OR result = '')",
                (datetime.fromtimestamp(now_epoch - 3600, timezone.utc).isoformat(),),
            )
    except Exception as exc:  # noqa: BLE001 - pruning must never stop scheduling
        print(f"[one-agents] watch prune skipped: {exc}", flush=True)

    heads = [agent_id for agent_id, meta in AGENTS.items() if meta.get("seat") != "worker"]
    with _connect() as db:
        for head_id in heads:
            schedule_id = f"watch:{head_id}"
            db.execute(
                "INSERT OR IGNORE INTO agent_schedules (agent_id, interval_seconds, next_run_epoch) "
                "VALUES (?, ?, 0)",
                (schedule_id, interval),
            )
            schedule = db.execute(
                "SELECT * FROM agent_schedules WHERE agent_id = ?", (schedule_id,)
            ).fetchone()
            if not schedule or not schedule["enabled"] or schedule["next_run_epoch"] > now_epoch:
                continue

            floor_ids = floor_watch.floor_agents(head_id)
            placeholders = ",".join("?" for _ in floor_ids)
            # mode != 'watch' or this gate defeats itself: a watch job is a job,
            # so the first watch makes its own floor look "recently active"
            # forever and every head keeps getting watched every interval with
            # nothing to watch. Confirmed live 2026-08-29 -- 129 of 238 rows in
            # the queue were watches, and they buried SCRIBE's awaiting_upload
            # job at position 130 where the cockpit's recent-jobs strip could
            # not show it. Third place the same mistake had to be fixed;
            # counting a watch as floor work is the bug, in all three.
            recent = db.execute(
                f"SELECT COUNT(*) FROM jobs WHERE agent_id IN ({placeholders}) "
                "AND mode != 'watch' AND created_at >= ?",
                (*floor_ids, datetime.fromtimestamp(now_epoch - lookback, timezone.utc).isoformat()),
            ).fetchone()[0]
            # Always move the schedule forward, even when skipping: otherwise a
            # quiet floor is re-evaluated on every single 30s tick forever.
            db.execute(
                "UPDATE agent_schedules SET interval_seconds = ?, next_run_epoch = ? WHERE agent_id = ?",
                (interval, now_epoch + interval, schedule_id),
            )
            if not recent:
                continue
            # A long diagnosis/repair can legitimately outlast one interval.
            # Do not launch a second copy of the same floor head's checker:
            # concurrent HELIOS runs can race on the same clean working tree,
            # commit gate, and failed-job checkpoint. The schedule has already
            # advanced above, so the next normal interval will check again.
            active_watch = db.execute(
                "SELECT 1 FROM jobs WHERE agent_id = ? AND mode = 'watch' "
                "AND status IN ('queued', 'running') LIMIT 1",
                (head_id,),
            ).fetchone()
            if active_watch:
                continue
            db.execute(
                "INSERT INTO jobs (id, agent_id, task, mode, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'watch', 'queued', ?, ?)",
                (f"{head_id}-{uuid.uuid4().hex[:12]}", head_id,
                 "[watch] Check this floor's recent jobs for anything stuck or unreconciled",
                 now, now),
            )


def _job_fired_by_trigger(trigger_id: str, job_id: str) -> bool:
    """The scheduler's own receipt: was this job enqueued by that trigger's fire?

    A standing publish authority must not rest on task text alone - anyone can
    type "[ONE trigger: ...]". fire_due writes the job id it enqueued into
    trigger_fires right after enqueue returns, so a short retry covers a head
    that picked the job up in that gap. No receipt means no authority.
    """
    if not trigger_id or not job_id:
        return False
    try:
        import importlib.util
        module = sys.modules.get("one_company_triggers")
        if module is None or not hasattr(module, "fired_job"):
            trigger_path = floors_bridge.floors_root() / "_work" / "triggers.py"
            spec = importlib.util.spec_from_file_location("one_company_triggers", trigger_path)
            if spec is None or spec.loader is None:
                return False
            module = importlib.util.module_from_spec(spec)
            sys.modules["one_company_triggers"] = module
            spec.loader.exec_module(module)
        for attempt in range(3):
            if module.fired_job(trigger_id, job_id):
                return True
            if attempt < 2:
                time.sleep(1.0)
    except Exception as exc:  # noqa: BLE001 - fail closed
        print(f"[one-agents] trigger receipt check failed for {job_id}: {exc}", flush=True)
    return False


def _enqueue_due_recurring_jobs() -> None:
    # ONE-company owns business triggers. LAO remains only an execution
    # adapter called by the receiving agent; it is no longer the clock.
    try:
        import importlib.util
        trigger_path = floors_bridge.floors_root() / "_work" / "triggers.py"
        spec = importlib.util.spec_from_file_location("one_company_triggers", trigger_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("ONE trigger module loader unavailable")
        trigger_module = sys.modules.get("one_company_triggers")
        if trigger_module is None:
            trigger_module = importlib.util.module_from_spec(spec)
            sys.modules["one_company_triggers"] = trigger_module
            spec.loader.exec_module(trigger_module)
        # Keep durable rows aligned with the source registry. This preserves
        # enabled/next-fire state, but prevents a floor migration from leaving
        # an old head receiving the canonical trigger forever.
        if hasattr(trigger_module, "reconcile_defaults"):
            trigger_module.reconcile_defaults()

        def active_count(agent_id: str) -> int:
            """How much work this head's FLOOR already has in flight.

            A trigger's max_concurrent_jobs is about the floor's capacity, not
            the head's own calendar. This counted the head alone, so on
            2026-09-24 the 09:00 KDP trigger fired while SCRIBE was still
            writing the book commissioned at 08:38 -- HERMES itself was idle,
            so the guard saw an empty floor. Nothing would have serialised the
            two either: ONE_WORKER_MAX_CONCURRENT_JOBS defaults to 6, so both
            commissions would have driven the same LAO process and the same
            logged-in browser profile at once.

            mode != 'watch' for the reason the watch scheduler already
            documents a few lines above: a head's own watch job is not floor
            work, and counting it would make every floor look permanently
            busy and silently starve every trigger.
            """
            # Floor 12 is intentionally flow-concurrent: a long YATRA visual
            # run must not suppress a due VISTA slot, community poll or a
            # second channel's research. Its workers already guard their
            # scarce browser/OBS/download resources at the adapter level, so
            # the scheduler only prevents duplicate HELIOS commissions here.
            # Other floors retain their proven floor-wide serialization.
            agents = ([agent_id] if agent_id == "helios"
                      else (floor_watch.floor_agents(agent_id) or [agent_id]))
            placeholders = ",".join("?" for _ in agents)
            with _connect() as db:
                return int(db.execute(
                    f"SELECT COUNT(*) FROM jobs WHERE agent_id IN ({placeholders}) "
                    "AND mode != 'watch' AND status IN ('queued','running')",
                    tuple(agents),
                ).fetchone()[0])

        def dispatch(agent_id: str, task: str, mode: str, priority: str) -> dict[str, Any]:
            agent = AGENTS.get(agent_id)
            if not agent or agent.get("seat") == "worker" or agent.get("reports_to"):
                raise RuntimeError(f"Scheduled trigger refused non-head target: {agent_id}")
            if mode != "execute":
                raise RuntimeError(f"Scheduled trigger refused direct/legacy mode: {mode}")
            return enqueue_job(agent_id, task, "execute", priority)

        for outcome in trigger_module.fire_due(dispatch, active_count):
            print(f"[one-agents] company trigger {outcome['trigger_id']}: "
                  f"{outcome['outcome']} {outcome.get('job_id') or ''}", flush=True)
    except Exception as exc:  # scheduling failure must not stop manual work
        print(f"[one-agents] company trigger scheduling skipped: {exc}", flush=True)

    try:
        _enqueue_floor_watches()
    except Exception as exc:  # noqa: BLE001 - the watch must never stop ordinary dispatch
        print(f"[one-agents] floor watch scheduling skipped: {exc}", flush=True)

    now_epoch = time.time()
    now = _now()
    if os.environ.get("ALFA_AUTOSCOUT", "false").lower() in {"1", "true", "yes", "on"}:
        interval = max(900, int(os.environ.get("ALFA_SCAN_INTERVAL_SECONDS", "3600")))
        with _connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO agent_schedules (agent_id, interval_seconds, next_run_epoch) VALUES ('alfa', ?, 0)",
                (interval,),
            )
            schedule = db.execute("SELECT * FROM agent_schedules WHERE agent_id = 'alfa'").fetchone()
            if schedule and schedule["enabled"] and schedule["next_run_epoch"] <= now_epoch:
                job_id = f"alfa-{uuid.uuid4().hex[:12]}"
                db.execute(
                    "INSERT INTO jobs (id, agent_id, task, mode, status, created_at, updated_at) VALUES (?, 'alfa', ?, 'execute', 'queued', ?, ?)",
                    (job_id, "[scheduled] Scan public forums for fresh paid service opportunities", now, now),
                )
                db.execute(
                    "UPDATE agent_schedules SET interval_seconds = ?, next_run_epoch = ? WHERE agent_id = 'alfa'",
                    (interval, now_epoch + interval),
                )

    # Job hunting belongs to POSEIDON on Floor 1's Prompt 0-28 company plane.
    # The legacy Floor-9 autoscout was removed rather than left behind a flag.


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def enqueue_job(agent_id: str, task: str, mode: str = "plan", tier: str = "fast", *, dedupe_key: str = "", reserved: bool = False) -> dict[str, Any]:
    agent_id = agent_id.strip().lower()
    if agent_id not in AGENTS:
        raise ValueError(f"Unknown agent: {agent_id}")

    # Every job in ONE passes through here, which makes it the one place where
    # "an agent must be defined on a floor before it can work" can be true by
    # construction rather than by anybody remembering it.
    #
    # PEITHO was added straight to AGENTS with no floor definition and ran for
    # days. A safety check found it afterwards, which is the only time a
    # checker can find anything. This refuses it at the moment of dispatch.
    #
    # The None case is deliberately the opposite of the publish gate's, and the
    # asymmetry is the point. There, None means "cannot tell whether this needs
    # a person" and it holds, because refusing to publish costs a delay and
    # publishing wrongly cannot be undone. Here, None means "there is no floors
    # tree" - the ordinary state of a public clone, since that folder is not
    # mirrored - and refusing would make the open-source repository unable to
    # run any agent at all. So an absent registry allows, and a present one
    # that has never heard of this agent refuses.
    known = floors_bridge.agent_is_defined(agent_id)
    if known is False:
        raise ValueError(
            f"{agent_id} has no floor definition. Define it under "
            f"one-company/floors/floor_NN_*/agents/{agent_id}/ with agent.yaml, "
            f"capabilities.yaml and permissions.yaml, rebuild the index with "
            f"_registry/build_index.py, then dispatch. An agent wired without a "
            f"floor inherits no capability check, no approval tier and no audit."
        )
    mode = mode.strip().lower()
    # "report" is a real, implemented mode: _run_hermes dispatches it to
    # _hermes_report(), and SCRIBE enqueues it as the hand-back leg once a
    # book is produced. It was missing from this validation set only, so
    # SCRIBE crashed at the very END of a run, after doing its actual work
    # (confirmed 2026-08-14: job scribe-da983f3c750f failed "Mode must be
    # plan, execute, or publish" while its own mode was execute -- the
    # rejected value was the downstream hand-back, not the job itself).
    # This only permits a previously-rejected value; no existing caller
    # changes behaviour. Deliberately NOT added to agent_network's tool
    # enum -- this is an internal hand-back, not for the LLM to dispatch.
    if mode not in {"plan", "execute", "publish", "report"}:
        raise ValueError("Mode must be plan, execute, publish, or report")
    tier = (tier or "fast").strip().lower()
    if tier not in {"fast", "heavy"}:
        raise ValueError("Tier must be fast or heavy")
    task = task.strip()
    if not task:
        raise ValueError("Task is required")
    from openjarvis.one_agents.chandan_control import continuation_key
    checkpoint_key = continuation_key(agent_id, task)
    if checkpoint_key:
        dedupe_key = checkpoint_key
    job_id = f"{agent_id}-{uuid.uuid4().hex[:12]}"
    now = _now()
    with _connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS handoff_keys (key TEXT PRIMARY KEY, job_id TEXT NOT NULL)")
        if dedupe_key:
            db.execute("BEGIN IMMEDIATE")
            if checkpoint_key:
                for prior in db.execute("SELECT * FROM jobs WHERE agent_id='chandan' ORDER BY created_at DESC").fetchall():
                    if continuation_key(agent_id, prior["task"]) == checkpoint_key:
                        db.execute("INSERT OR REPLACE INTO handoff_keys (key, job_id) VALUES (?, ?)", (checkpoint_key, prior["id"]))
                        return dict(prior)
            previous = db.execute("SELECT job_id FROM handoff_keys WHERE key = ?", (dedupe_key,)).fetchone()
            if previous:
                existing = db.execute("SELECT * FROM jobs WHERE id = ?", (previous["job_id"],)).fetchone()
                # A key stops a second, duplicate handoff of live or finished work. It must not pin a handoff to a
                # job that failed: IRIS's verified Vietnam master was "handed" to ARES's morning failure (raised
                # because no master existed yet) and ARES never ran on it (2026-10-06).
                if existing and existing["status"] not in ("failed", "cancelled"):
                    return dict(existing)
        db.execute(
            "INSERT INTO jobs (id, agent_id, task, mode, tier, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            # Publishing handoffs carry governed evidence and scorecards. TEXT
            # has no 4K database limit; truncating here corrupts the JSON and
            # makes the receiving agent misclassify the handoff as a new task.
            (job_id, agent_id, task[:100000], mode, tier, "reserved" if reserved else "queued", now, now),
        )
        if dedupe_key:
            # REPLACE: after a failed job the key now points at its retry.
            db.execute("INSERT OR REPLACE INTO handoff_keys (key, job_id) VALUES (?, ?)", (dedupe_key, job_id))
    return get_job(job_id) or {}


def get_job(job_id: str) -> dict[str, Any] | None:
    with _connect() as db:
        return _row(db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


def _job_is_active(job_id: str) -> bool:
    """True only while the queue still owns this execution.

    A watchdog cannot kill the Python thread it timed out. Long-running floor
    handlers must therefore check queue ownership before creating downstream
    work, otherwise an already-failed HERMES run can still commission a book.
    """
    job = get_job(job_id)
    return bool(job and job.get("status") in {"queued", "running"})


def _require_active_job(job: dict[str, Any], action: str) -> None:
    """Stop a released/cancelled worker before it creates downstream work."""
    # Direct handler/unit invocations are intentionally supported and carry no
    # claimed queue status. Worker-owned jobs do, so only those need the live
    # ownership lookup.
    if job.get("status") in {"queued", "running"} and not _job_is_active(str(job.get("id") or "")):
        raise RuntimeError(f"Job no longer owns the queue row; refusing to {action}")


def list_agent_jobs(agent_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """All jobs for one specific agent, most recent first.

    Confirmed live (2026-07-19): ``list_jobs()`` is a global recent-N window
    across every agent -- a busy agent (ALFA, 352+ jobs) crowds a quieter
    agent's own history out of that window entirely, so filtering
    ``list_jobs()``'s results down to one agent_id can silently return far
    fewer rows than that agent actually has. Querying by agent_id directly
    is the only way to reliably answer "why did IA fail" with its own real
    history instead of whatever happened to survive the global limit.
    """
    with _connect() as db:
        rows = db.execute(
            "SELECT * FROM jobs WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
            (agent_id, max(1, min(limit, 100))),
        ).fetchall()
    return [dict(row) for row in rows]


def resume_yatra_visual_job(job_id: str) -> dict[str, Any]:
    """Safely retry a failed visual-only YATRA job from its saved checkpoint.

    This intentionally refuses discovery/script/narration jobs: those stages
    can change the approved story or spend voice credits. Visual resumes must
    carry a successful FABULA receipt and a durable production plan, and only
    one YATRA queue job may be active at a time. Accepted files are reused by
    the normal visual checkpoint handlers.
    """
    previous = get_job(job_id)
    if not previous:
        raise ValueError("YATRA job not found")
    if previous.get("agent_id") != "yatra" or previous.get("mode") != "execute":
        raise ValueError("Only failed YATRA execute jobs can be resumed here")
    if previous.get("status") != "failed":
        raise ValueError("Resume is available only for failed jobs")
    try:
        payload = json.loads(str(previous.get("task") or ""))
    except (TypeError, ValueError) as exc:
        raise ValueError("The failed job has no readable saved task") from exc
    if not isinstance(payload, dict) or payload.get("stage") != "visuals":
        raise ValueError("Only the saved visual stage can be resumed; narration is not retried")
    checkpoint = str(payload.get("preproduction_job") or "").strip()
    receipt_value = str(payload.get("narration_receipt") or "").strip()
    if not checkpoint or not receipt_value:
        raise ValueError("Saved visual task is missing its preproduction or narration checkpoint")
    receipt_path = Path(receipt_value).resolve()
    asset_root = _YATRA_ASSET_ROOT.resolve()
    try:
        receipt_path.relative_to(asset_root)
    except ValueError as exc:
        raise ValueError("Narration checkpoint is outside the YATRA asset library") from exc
    if receipt_path.name != "fabula-receipt.json" or not receipt_path.is_file():
        raise ValueError("Successful FABULA narration receipt is missing; refusing a paid regeneration")
    try:
        envelope = json.loads(receipt_path.read_text(encoding="utf-8"))
        narration = envelope.get("narration") or {}
        if (str(envelope.get("checkpoint") or "") != checkpoint
                or narration.get("ok") is not True
                or str(narration.get("status") or "") != "Successful"):
            raise ValueError("FABULA receipt does not match this successful production checkpoint")
        plan = receipt_path.parent.parent / "production-plan.json"
        if not plan.is_file():
            # The visual worker renders the opening map before it copies the
            # immutable LAO plan into the asset folder.  A map failure could
            # therefore leave a complete paid narration receipt but no local
            # plan, and the resume gate introduced on 2026-10-18 refused the
            # otherwise safe checkpoint. Recover only from the exact attached
            # LAO checkpoint and prove that its script is the one that was
            # narrated before creating the missing local copy.
            source = _yatra_preproduction_file(checkpoint)
            records = json.loads(source.read_text(encoding="utf-8"))
            record = records[0] if records else {}
            script_value = str(narration.get("script_file") or "").strip()
            script_path = Path(script_value).resolve() if script_value else None
            if (not script_path or not script_path.is_file()
                    or script_path.parent != receipt_path.parent
                    or script_path.read_text(encoding="utf-8").strip()
                    != str(record.get("full_script") or "").strip()):
                raise ValueError(
                    "Local production plan is missing and the immutable LAO script cannot be "
                    "matched to this narration receipt"
                )
            _validate_yatra_contract(record, _YATRA_EXPECTED_SCENES)
            plan.parent.mkdir(parents=True, exist_ok=True)
            plan.write_bytes(source.read_bytes())
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Saved narration checkpoint is unreadable: {exc}") from exc

    active = [item for item in list_agent_jobs("yatra", 100)
              if item.get("id") != job_id and item.get("status") in {"queued", "running"}]
    if active:
        raise ValueError(f"YATRA already has active job {active[0].get('id')}; wait before resuming")
    return enqueue_job("yatra", str(previous["task"]), mode="execute",
                       tier=str(previous.get("tier") or "fast"),
                       dedupe_key=f"yatra-visual-resume:{job_id}")


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    with _connect() as db:
        rows = db.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 100)),)
        ).fetchall()
    return [dict(row) for row in rows]


def latest_jobs_by_agent() -> dict[str, dict[str, Any]]:
    """The newest real job for every agent, whatever else has happened since.

    list_jobs(12) is a system-wide window, so an agent that finished its work
    an hour ago simply vanishes from it once any twelve other jobs run - and a
    panel built on that window reports a floor as idle while it is mid-mission.
    The OLYMPUS decision list was moved off that window on 2026-09-13 for
    exactly this reason; the publishing flow strip was not, and showed HERMES
    through IMPRIMATUR as "Awaiting mission" on the day they published a book.

    mode != 'watch' for the reason the watch scheduler documents: a head's own
    watch job is not floor work, and counting it would make every floor look
    busy with nothing.
    """
    with _connect() as db:
        rows = db.execute(
            "SELECT j.* FROM jobs j JOIN ("
            "  SELECT agent_id, MAX(created_at) AS newest FROM jobs"
            "  WHERE mode != 'watch' GROUP BY agent_id"
            ") latest ON j.agent_id = latest.agent_id AND j.created_at = latest.newest"
        ).fetchall()
    return {str(row["agent_id"]): dict(row) for row in rows}


def agent_stats() -> list[dict[str, Any]]:
    """Aggregate job history per agent: counts, status breakdown, last run,
    average duration of completed jobs.

    Previously agent_network's only introspection was ``history`` (raw,
    un-aggregated job rows, capped at 100) -- answering "how are the agents
    doing" meant the LLM had to eyeball a wall of individual rows itself.
    This does the aggregation in code instead, over the FULL job history
    (not capped like list_jobs), one row per agent, ready to narrate.
    """
    with _connect() as db:
        rows = db.execute("SELECT * FROM jobs").fetchall()

    by_agent: dict[str, list[dict[str, Any]]] = {agent_id: [] for agent_id in AGENTS}
    for row in rows:
        job = dict(row)
        by_agent.setdefault(job["agent_id"], []).append(job)

    stats: list[dict[str, Any]] = []
    for agent_id, agent_meta in AGENTS.items():
        jobs = by_agent.get(agent_id, [])
        status_counts: dict[str, int] = {}
        for job in jobs:
            status_counts[job["status"]] = status_counts.get(job["status"], 0) + 1

        durations_seconds: list[float] = []
        last_run_at = ""
        for job in jobs:
            if job["updated_at"] > last_run_at:
                last_run_at = job["updated_at"]
            if job["status"] == "completed":
                try:
                    started = datetime.fromisoformat(job["created_at"])
                    finished = datetime.fromisoformat(job["updated_at"])
                    durations_seconds.append((finished - started).total_seconds())
                except ValueError:
                    continue

        avg_duration_seconds = (
            round(sum(durations_seconds) / len(durations_seconds), 1)
            if durations_seconds
            else None
        )

        stats.append({
            "agent_id": agent_id,
            "name": agent_meta["name"],
            "role": agent_meta["role"],
            "total_jobs": len(jobs),
            "status_counts": status_counts,
            "last_run_at": last_run_at or None,
            "avg_duration_seconds": avg_duration_seconds,
        })

    return stats


def claim_job(job_id: str | None = None) -> dict[str, Any] | None:
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        # A scoped deployment may reserve a job so an older running worker
        # cannot win the claim and execute stale code. Only an exact-id claim
        # can consume that reservation; the normal scheduler ignores it.
        # PLANEXIUM's pipeline deliberately owns one channel-wide production
        # lease.  Since the worker can execute several unrelated jobs at once,
        # claiming a second PLANEXIUM row while the first is running only makes
        # that second row fail at the lease boundary.  Keep it queued instead;
        # BEGIN IMMEDIATE makes this admission check and the claim atomic even
        # when more than one worker process is polling the queue.
        planexium_available = (
            "(jobs.agent_id != 'planexium' OR NOT EXISTS ("
            "SELECT 1 FROM jobs AS active_planexium "
            "WHERE active_planexium.agent_id = 'planexium' "
            "AND active_planexium.status = 'running'))"
        )
        row = (db.execute(
                   "SELECT * FROM jobs WHERE status IN ('queued','reserved') AND id = ? AND "
                   + planexium_available, (job_id,)).fetchone()
               if job_id else db.execute(
                   "SELECT * FROM jobs WHERE status = 'queued' AND " + planexium_available
                   + " ORDER BY created_at LIMIT 1").fetchone())
        if not row:
            return None
        now = _now()
        changed = db.execute(
            "UPDATE jobs SET status = 'running', progress = 5, updated_at = ?, heartbeat_at = ? WHERE id = ? AND status = ?",
            (now, now, row["id"], row["status"]),
        ).rowcount
        if not changed:
            return None
    return get_job(row["id"])


def finish_job(job_id: str, result: dict[str, Any]) -> None:
    with _connect() as db:
        db.execute(
            "UPDATE jobs SET status = 'completed', progress = 100, result = ?, updated_at = ? WHERE id = ?",
            (json.dumps(result, ensure_ascii=True), _now(), job_id),
        )
    if job_id.startswith("beta-"):
        try:
            from openjarvis.one_agents.revenue import mark_delivery_job

            mark_delivery_job(job_id, "workspace_ready")
        except Exception:
            pass


def mark_blocked(job_id: str, result: dict[str, Any]) -> None:
    """Persist an honest terminal hold when a required capability is absent.

    A blocked research run must never look completed, and it must not leave
    the building projection stuck on ``running`` after the worker goes idle.
    """
    reason = str(result.get("blocked_reason") or "Required capability unavailable")[:2000]
    safe_review = job_id.startswith("chandan-") and result.get("status") in {"review_required", "awaiting_identity_review", "identity_review_required"}
    with _connect() as db:
        db.execute(
            "UPDATE jobs SET status = ?, progress = 0, result = ?, error = ?, updated_at = ? WHERE id = ?",
            ("review_required" if safe_review else "blocked", json.dumps(result, ensure_ascii=True), "" if safe_review else reason, _now(), job_id),
        )
    job = get_job(job_id)
    if job:
        stages.clear_stage(str(job.get("agent_id") or ""))


def mark_awaiting_upload(job_id: str, result: dict[str, Any]) -> None:
    """SCRIBE's own execution is done, but the real-world action -- uploading
    to kdp.amazon.com by hand, since there's no KDP API and automating that
    submit is explicitly off the table (see _generate_kdp_packet) -- hasn't
    happened yet. This holds the job open as 'awaiting_upload' instead of
    'completed', so the dashboard keeps showing SCRIBE waiting rather than
    looking finished while the actual publish step still sits with a human.
    confirm_scribe_upload is what actually closes it out.
    """
    with _connect() as db:
        db.execute(
            "UPDATE jobs SET status = 'awaiting_upload', progress = 95, result = ?, updated_at = ? WHERE id = ?",
            (json.dumps(result, ensure_ascii=True), _now(), job_id),
        )


def mark_awaiting_login(job_id: str, result: dict[str, Any]) -> None:
    with _connect() as db:
        db.execute(
            "UPDATE jobs SET status='awaiting_login', result=?, error='', updated_at=? "
            "WHERE id=? AND status='running'",
            (json.dumps(result), _now(), job_id),
        )
    stages.clear_stage("imprimatur")


def _resume_kdp_login_jobs() -> None:
    with _connect() as db:
        waiting = db.execute(
            "SELECT id FROM jobs WHERE agent_id='imprimatur' AND status='awaiting_login'"
        ).fetchall()
    if not waiting:
        return
    from openjarvis.tools.kdp_browser_publisher import login_ready
    if not login_ready():
        return
    # Requeue the original task, retaining its phase, approval, and book folder.
    with _connect() as db:
        for row in waiting:
            db.execute(
                "UPDATE jobs SET status='queued', error='', updated_at=?, "
                "resume_count=COALESCE(resume_count,0)+1 WHERE id=? AND status='awaiting_login'",
                (_now(), row["id"]),
            )


def mark_awaiting_growth_review(job_id: str, result: dict[str, Any]) -> None:
    """Hold a finished manuscript while MERCURY and ALFA review it."""
    with _connect() as db:
        db.execute(
            "UPDATE jobs SET status = 'awaiting_growth_review', progress = 90, "
            "result = ?, updated_at = ? WHERE id = ?",
            (json.dumps(result, ensure_ascii=True), _now(), job_id),
        )


def _publishing_lifecycle_module():
    """Load Floor 5's implementation without moving ownership into runtime."""
    path = (Path(__file__).resolve().parents[4] / "one-company" / "floors" /
            "floor_05_publishing" / "lib" / "post_upload_lifecycle.py")
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("floor05_post_upload_lifecycle", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def confirm_scribe_upload(job_id: str,
                          upload_evidence: dict[str, Any] | None = None,
                          rationale: str = "") -> dict[str, Any]:
    """Dashboard 'mark uploaded' action -- the Chairman confirms they actually
    submitted the book on kdp.amazon.com by hand. Explicit call, 2026-08-26:
    "jab book upload ho jayegi to SCRIBE ko message bhi dena hai ki wo book
    handover kar sakta hai PEITHO ko tabhi database mn bhi update hoga" --
    only this action enqueues PEITHO's job and finishes SCRIBE's; nothing
    else does. Starting PEITHO before this (post-publish marketing) would
    have nothing real to work from, since the book isn't actually live yet.

    ``rationale`` is recorded, not required. The building enforces the same
    10-character floor the rejection path uses before it ever calls this;
    OneCockpit's confirm button is a single click with an empty body, and
    breaking that to enforce the floor twice would remove a working gate to
    tighten one that is already covered.
    """
    job = get_job(job_id)
    if not job:
        raise ValueError(f"Unknown job: {job_id}")
    if job["agent_id"] != "scribe":
        raise ValueError(f"Job {job_id} belongs to {job['agent_id']}, not scribe")
    if job["status"] != "awaiting_upload":
        raise ValueError(f"Job {job_id} is {job['status']}, not awaiting an upload confirmation")

    try:
        result = json.loads(job.get("result") or "{}")
    except json.JSONDecodeError:
        result = {}
    run_dir = str(result.get("run_dir") or "")
    title = str(result.get("title") or "")
    lao_job_id = str(result.get("lao_job") or "")
    kdp_packet_path = str((result.get("kdp_packet") or {}).get("path") or "")

    lifecycle = _publishing_lifecycle_module()
    if lifecycle is not None:
        launch = lifecycle.launch_plan(
            title_id=str((upload_evidence or {}).get("asin") or job_id),
            title=title, evidence=upload_evidence,
        )
    else:
        launch = {
            "listing_evidence": {"verification_status": "verification_pending",
                                 "remote_checked": False,
                                 "errors": ["Floor 5 lifecycle module unavailable"]},
            "phases": [], "owner_setup": {"items": []},
        }

    # Floor 5's own policy already makes this a hard requirement -- it is
    # OWNER_REQUIREMENTS['kdp_listing_evidence'], required=True, and it is what
    # "unblocks" PEITHO. Until now that verdict was computed and discarded, so
    # a confirmation carrying nothing still completed the job, recorded a
    # published title and started launch work. Raising here leaves the job at
    # awaiting_upload: the gate stays open instead of closing on nothing.
    #
    # The lifecycle module being unavailable also lands here, deliberately. If
    # the evidence cannot be validated it cannot be attested either, and a book
    # wrongly recorded as on sale is worse than a gate that waits.
    evidence_errors = [str(e) for e in (launch.get("listing_evidence") or {}).get("errors") or []]
    if evidence_errors:
        raise ValueError(
            "KDP listing evidence is required before a book counts as uploaded: "
            + "; ".join(evidence_errors)
        )

    celebration = f"“{title}” upload attested! 🎉" if title else "Upload attested! 🎉"
    stages.set_stage("scribe", stages.CELEBRATING, celebration)
    stages.set_stage("peitho", stages.CELEBRATING, celebration)
    time.sleep(float(os.environ.get("ONE_CELEBRATE_SECONDS", "9")))
    stages.clear_stage("scribe")

    peitho_job = enqueue_job(
        "peitho",
        json.dumps({
            "run_dir": run_dir, "title": title, "lao_job": lao_job_id,
            "kdp_packet_path": kdp_packet_path,
            "mission_id": result.get("mission_id"),
            "origin_job": result.get("origin_job"),
            "objective": result.get("objective"),
            "post_upload_lifecycle": launch,
            "upload_evidence": launch.get("listing_evidence"),
        }),
        mode="execute", tier="fast",
    )

    result["uploaded_confirmed_at"] = _now()
    if rationale.strip():
        result["upload_confirmed_rationale"] = rationale.strip()[:2000]
    result["upload_evidence"] = launch.get("listing_evidence")
    result["post_upload_lifecycle"] = launch
    result["handed_to"] = {"agent": "PEITHO", "job_id": peitho_job["id"]}
    with _connect() as db:
        db.execute(
            "UPDATE jobs SET status = 'completed', progress = 100, result = ?, updated_at = ? WHERE id = ?",
            (json.dumps(result, ensure_ascii=True), _now(), job_id),
        )

    memory.remember(
        agent="SCRIBE", floor_id="5", floor_name="Book Publishing (KDP)",
        kind="Upload Confirmed",
        body=(f"Chairman attested the KDP upload for “{title}”. "
              f"Listing state: {launch['listing_evidence']['verification_status']}. "
              "Handed off to PEITHO for draft-only launch preparation."),
        task=title, tags=["kdp", "publishing", "uploaded"],
    )
    _publishing_event({**job, "task": json.dumps(result)}, agent="OLYMPUS",
                      event_type="upload_confirmed", stage="human_gate",
                      summary="Chairman confirmed the Amazon KDP upload",
                      details={"title": title, "peitho_job_id": peitho_job["id"],
                               "rationale": rationale.strip(),
                               "listing_evidence": launch.get("listing_evidence"),
                               "owner_setup": launch.get("owner_setup")})

    return {"scribe_job": get_job(job_id), "peitho_job": peitho_job}


def reject_scribe_upload(job_id: str, rationale: str) -> dict[str, Any]:
    """OLYMPUS rejects the submission packet; no publish or PEITHO handoff."""
    job = get_job(job_id)
    if not job or job.get("agent_id") != "scribe":
        raise ValueError(f"Unknown SCRIBE job: {job_id}")
    if job.get("status") != "awaiting_upload":
        raise ValueError(f"Job {job_id} is {job.get('status')}, not awaiting upload review")
    rationale = rationale.strip()
    if len(rationale) < 10:
        raise ValueError("a rejection rationale of 10+ characters is required")
    with _connect() as db:
        db.execute(
            "UPDATE jobs SET status='failed', error=?, updated_at=? WHERE id=?",
            (f"OLYMPUS rejected KDP submission: {rationale}"[:2000], _now(), job_id),
        )
    stages.clear_stage("scribe")
    result = _json_task({"task": job.get("result") or "{}"})
    _publishing_event({**job, "task": json.dumps(result)}, agent="OLYMPUS",
                      event_type="upload_rejected", stage="human_gate",
                      summary="OLYMPUS rejected the KDP submission packet",
                      details={"rationale": rationale}, status="rejected")
    return get_job(job_id) or {}


def fail_job(job_id: str, error: Exception) -> None:
    failed = get_job(job_id)
    with _connect() as db:
        db.execute(
            "UPDATE jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
            (str(error)[:2000], _now(), job_id),
        )
    if failed:
        agent_id = str(failed.get("agent_id") or "")
        stages.clear_stage(agent_id)
        reports_to = str((AGENTS.get(agent_id) or {}).get("reports_to") or "")
        if reports_to:
            stages.clear_stage(reports_to)
    if job_id.startswith("beta-"):
        try:
            from openjarvis.one_agents.revenue import mark_delivery_job

            mark_delivery_job(job_id, "failed")
        except Exception:
            pass


def cancel_job(job_id: str) -> dict[str, Any]:
    """User-initiated kill from the dashboard, for a job stuck queued/running
    (e.g. a polling loop that went stale across a system sleep/wake cycle --
    confirmed live 2026-08-16: a SCRIBE job's own row never advanced past
    'running' even though the LAO job it was polling had long since finished,
    because sleep/wake killed the polling coroutine without ever raising an
    exception the normal fail_job() path would have caught).

    Reuses the existing 'failed' status (already rendered correctly
    everywhere -- the dashboard's job cards, the agent-execution grid) rather
    than introducing a new status value that would need matching UI/CSS
    support nobody has written yet.

    If this is a worker job with a LAO job attached (recorded in
    agent_stages.json while the worker polls), also asks LAO to stop that job
    -- otherwise the underlying multi-hour pipeline just keeps running
    unattended even after the dashboard says it's dead. Best-effort: a LAO
    API failure here still lets the local job get marked cancelled.

    Also clears the floor head that was blocked waiting on this worker, so the
    building doesn't keep showing a handover to an agent that no longer exists.
    """
    job = get_job(job_id)
    if not job:
        raise ValueError(f"Unknown job: {job_id}")
    if job["status"] not in {"queued", "running"}:
        raise ValueError(f"Job {job_id} is already {job['status']}, nothing to cancel")

    # Generic across every worker seat, not just SCRIBE. Both halves below used
    # to hard-code `if agent_id == "scribe"`, so cancelling any OTHER worker
    # left its LAO job running AND stranded its floor head forever -- confirmed
    # live 2026-08-26: MUSE was cancelled from the dashboard and IRIS sat on
    # "Waiting on MUSE to produce the reel" with no worker left to wait for.
    # The registry already knows both facts (`reports_to` names the head, and
    # the worker records `lao_process` in its stage), so nothing here needs to
    # name an agent -- a new worker seat inherits this for free.
    agent = AGENTS.get(job["agent_id"], {})
    worker_stage = stages.get_stages().get(job["agent_id"]) or {}

    lao_job_id = ""
    if worker_stage.get("worker_job") == job_id or not worker_stage.get("worker_job"):
        lao_job_id = str(worker_stage.get("lao_job") or "")

    if lao_job_id:
        try:
            from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool

            # Recorded by the worker alongside lao_job. The KDP fallback only
            # covers stages written before lao_process existed.
            process_name = str(worker_stage.get("lao_process") or "").strip() or os.environ.get(
                "LAO_KDP_PROCESS", KDP_PROCESS_NAME
            )
            LaoOrchestratorTool().execute(
                action="stop", process_name=process_name, scope="production", job_id=lao_job_id,
            )
        except Exception:  # noqa: BLE001 - local cancel must still succeed even if LAO is unreachable
            pass

    with _connect() as db:
        db.execute(
            "UPDATE jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
            (f"Cancelled by user from the dashboard{' (LAO job ' + lao_job_id + ' stop requested)' if lao_job_id else ''}", _now(), job_id),
        )

    stages.clear_stage(job["agent_id"])
    # Release the floor head that was blocked on this worker -- but only if it
    # was actually waiting on THIS job. A head that has already moved on to
    # something else must not be reset out from under itself.
    head_id = str(agent.get("reports_to") or "")
    if head_id:
        head_stage = stages.get_stages().get(head_id) or {}
        waiting_job = head_stage.get("worker_job")
        if waiting_job == job_id or (waiting_job is None and head_stage.get("worker") == job["agent_id"]):
            stages.clear_stage(head_id)

    return get_job(job_id) or {}


def _resolve_planner_model(tier: str) -> tuple[str, str]:
    """Resolve (model, engine) for a planner call.

    'fast' (default) always uses the configured local router (ONE_ENGINE/
    ONE_ROUTER_MODEL — Ollama unless the operator has deliberately pointed
    the whole server at NVIDIA). It never silently falls through to
    NEMOTRON_MODEL, so an unset ONE_ROUTER_MODEL can't accidentally route a
    "fast" job to a paid cloud model.

    'heavy' escalates on purpose: the configured NVIDIA Nemotron model when
    an API key is present, otherwise the local heavy model
    (ONE_HEAVY_LOCAL_MODEL), otherwise the same fast-tier default.
    """
    if tier == "heavy":
        nemotron_model = os.environ.get("NEMOTRON_MODEL", "").strip()
        if nemotron_model and os.environ.get("NVIDIA_API_KEY", "").strip():
            return nemotron_model, "nvidia"
        heavy_local = os.environ.get("ONE_HEAVY_LOCAL_MODEL", "").strip()
        if heavy_local:
            return heavy_local, os.environ.get("ONE_ENGINE", "ollama").strip().lower() or "ollama"
    model = os.environ.get("ONE_ROUTER_MODEL") or "llama3.1:8b"
    engine = os.environ.get("ONE_ENGINE", "ollama").strip().lower()
    return model, engine


def _local_plan(job: dict[str, Any]) -> dict[str, Any]:
    agent = AGENTS[job["agent_id"]]
    prompt = (
        f"You are {agent['name']}, ONE's {agent['role']}. "
        "Produce a concise operational plan or draft for the task. Do not claim external actions occurred. "
        "State required approvals and integrations.\n\n"
        f"Task: {job['task']}"
    )
    tier = (job.get("tier") or "fast").strip().lower()
    model, engine = _resolve_planner_model(tier)
    # Every non-worker is a floor head in ONE's company roster. Floor-head
    # planning is a Sanjeevani/local boundary and may not spend cloud credits,
    # even when a caller accidentally requests the heavy/NVIDIA tier.
    if agent.get("seat") != "worker":
        model = os.environ.get("ONE_LOCAL_RESEARCH_MODEL", "qwen3.5:9b")
        engine = "ollama"
    fallback_reason = ""
    if engine == "nvidia":
        api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
        if not api_key:
            fallback_reason = "NVIDIA_API_KEY is missing"
            content = ""
        else:
            try:
                response = httpx.post(
                    os.environ.get("NVIDIA_HOST", "https://integrate.api.nvidia.com").rstrip("/") + "/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "top_p": 0.95,
                        "max_tokens": 900,
                    },
                    timeout=180,
                )
                response.raise_for_status()
                content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            except Exception as exc:  # noqa: BLE001 - fallback is intentional for plan mode
                fallback_reason = f"NVIDIA planner unavailable: {exc}"
                content = ""
    else:
        try:
            response = httpx.post(
                os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "think": False,
                    "messages": [{"role": "user", "content": prompt}],
                    "options": {"temperature": 0.2, "num_predict": 700},
                },
                timeout=180,
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "").strip()
        except Exception as exc:  # noqa: BLE001 - fallback is intentional for plan mode
            fallback_reason = f"Ollama planner unavailable: {exc}"
            content = ""
    if not content:
        content = (
            f"# {agent['name']} Operational Plan\n\n"
            f"Task: {job['task']}\n\n"
            "## Next Actions\n"
            "- Confirm the intended mode: plan, execute, or publish.\n"
            "- Check required credentials in the ONE credential vault before running external tools.\n"
            "- Use deterministic/Sanjeevani local steps; cloud-model fallback is forbidden for floor heads.\n"
            "- Save outputs and audit trail under the ONE runtime data folder.\n"
            "- Do not publish, send, or apply without explicit approval.\n\n"
            "## Current Runtime Note\n"
            f"{fallback_reason or 'Planner model returned no text; deterministic fallback plan created locally.'}\n"
        )
    output_dir = _home() / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job['id']}.md"
    output_path.write_text(content, encoding="utf-8")
    return {"agent": agent["name"], "mode": "local-plan", "content": content, "output": str(output_path)}


# --- ONE Autonomous Company floor-head scaffolds -----------------------
#
# Rebuilt per Vineet's direction: LAO (Documents\LAO) is not being touched,
# so each of these is a clean, safe, side-effect-free scaffold for now (they
# all just produce a local plan/log artifact via `_local_plan`, same as the
# old dead-persona fallback did). Real LAO integration gets wired into each
# one individually once the full floor set is built — that's the intended
# hook point for e.g. a future `LaoOrchestratorTool` call inside `_run_iris`
# or `_run_hermes`. The old direct external integrations this replaced
# (PostForge/Instagram in TITAN, the Leonardo/ffmpeg pipeline in IA, the
# live LAO bridge in HEPHAISTOS, the alfa.py/jobhunt.py scan jobs) are left
# in place as unused source files, not deleted, in case any of that logic is
# worth reusing when real integration comes back.


# Where the company's books live. ZEUS reads them; floors/_services/revenue
# owns them. Kept as a path rather than an import of the service module so a
# missing or moved company layer degrades to "scorecard unavailable" instead of
# breaking every dispatch to floor 11.
_COMPANY_SERVICES = Path(__file__).resolve().parents[4] / "one-company" / "floors" / "_services"


def _money_board() -> dict[str, Any]:
    """The company's money, or an honest statement that it could not be read."""
    import sys  # module-local: runtime.py has no top-level sys import

    service = _COMPANY_SERVICES / "revenue"
    if not service.is_dir():
        return {"unavailable": "floors/_services/revenue is not present"}
    if str(service) not in sys.path:
        sys.path.insert(0, str(service))
    try:
        import money  # type: ignore
        return money.money_board(_COMPANY_SERVICES.parents[1] / "data" / "company.db")
    except Exception as exc:  # noqa: BLE001
        return {"unavailable": f"{type(exc).__name__}: {exc}"[:300]}


# Who to send a measurement gap to. A business that cannot report a sale is a
# job for the floor that owns the source, not a question for the Chairman --
# that is the whole point of ZEUS holding the scorecard rather than printing it.
# A floor missing from here has no collector to route to yet and is escalated
# instead, which is the honest outcome rather than a job sent nowhere.
# Empty today, and that is the accurate state rather than an oversight. Neither
# collector exists yet: nothing anywhere fetches a KDP royalty report, and
# instagram_insights.py can read reach but nothing writes what it reads to the
# ledger. Routing to IRIS or METRON now would send them work they cannot do and
# get a plausible-looking non-answer back, which is worse than an honest gap.
#
# The mechanism below is live and tested. Adding an entry here is all it takes
# to start routing the moment a collector is real - that is a one-line change,
# not a rewrite, which is the point of registering them rather than hardcoding.
_COLLECTORS: dict[str, tuple[str, str]] = {}


def _drain_inbox() -> dict[str, Any]:
    """Collect sales that arrived while ONE was not running.

    Runs before the scorecard is read, not after. A board that reports money
    it has not collected yet is a board that is wrong for as long as it takes
    somebody to notice - and the whole point of the inbox is that nobody has
    to notice.
    """
    import sys  # module-local: runtime.py has no top-level sys import

    service = _COMPANY_SERVICES / "revenue"
    if not service.is_dir():
        return {"skipped": "revenue service not present"}
    if str(service) not in sys.path:
        sys.path.insert(0, str(service))
    try:
        import inbox  # type: ignore
        return inbox.drain(db_path=_COMPANY_SERVICES.parents[1] / "data" / "company.db")
    except Exception as exc:  # noqa: BLE001 - an unreachable inbox must not stop the report
        # Reported, not raised. The scorecard is still worth reading when the
        # inbox is unreachable; it just has to say so.
        return {"unavailable": f"{type(exc).__name__}: {exc}"[:200]}


def _experiment_board() -> dict[str, Any]:
    """Running revenue experiments, or an honest statement that they cannot be read."""
    import sys  # module-local: runtime.py has no top-level sys import

    service = _COMPANY_SERVICES / "experiments"
    if not service.is_dir():
        return {"unavailable": "floors/_services/experiments is not present"}
    for path in (service, _COMPANY_SERVICES / "revenue"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    try:
        import experiment  # type: ignore
        return experiment.board(_COMPANY_SERVICES.parents[1] / "data" / "company.db")
    except Exception as exc:  # noqa: BLE001
        return {"unavailable": f"{type(exc).__name__}: {exc}"[:300]}


def _run_zeus(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 11 - the company scorecard, and what to do about what it shows.

    Money first, production second, deliberately. Books published and reels
    produced are the numbers ONE has always been able to show; they are also
    the numbers that stayed high while revenue stayed at zero, which is exactly
    how a production company mistakes itself for a business.
    """
    stages.set_stage("zeus", stages.RESEARCHING, "Collecting sales, then reading the scorecard")
    collected = _drain_inbox()
    money = _money_board()

    if money.get("unavailable"):
        stages.clear_stage("zeus")
        return {"agent": "ZEUS", "mode": "scorecard", "_blocked": True,
                "blocked_reason": money["unavailable"],
                "content": ("The company scorecard could not be read, so nothing is "
                            "reported. An unreadable board is not a board of zeros.")}

    experiments = _experiment_board()
    businesses = money.get("businesses", [])
    unmeasured = [b for b in businesses if b["status"] == "no_source_connected"]

    # Production, for contrast only. This is the half ONE has always counted.
    recent = list_jobs(limit=200)
    produced = len([j for j in recent if j.get("status") == "completed"
                    and j.get("mode") not in ("watch", "plan")])

    routed: list[dict[str, Any]] = []
    escalate: list[dict[str, Any]] = []
    for business in unmeasured:
        floor_id = business["floor_id"]
        blocked = business.get("blocked_sources") or []
        collector = _COLLECTORS.get(floor_id)
        if collector is None:
            escalate.append({
                "floor_id": floor_id, "business": business["name"],
                "why": "no floor agent can collect this yet",
                "needs": [b["blocked_on"] for b in blocked] or
                         ["a revenue source has never been declared for this business"],
            })
            continue
        agent_id, instruction = collector
        # Routing, not doing. ZEUS says what is needed and to whom; the floor
        # decides how, which is its own charter's boundary.
        worker = enqueue_job(agent_id, json.dumps({
            "workflow": "revenue_collection", "floor_id": floor_id,
            "business": business["name"], "objective": instruction,
            "blocked_on": [b["blocked_on"] for b in blocked],
            "requested_by": "zeus",
        }), mode="execute", tier="fast")
        routed.append({"floor_id": floor_id, "business": business["name"],
                       "agent": agent_id.upper(), "job_id": worker["id"]})

    lines = [
        "# ZEUS - Company Scorecard", "",
        f"Generated {money['generated_at']}", "",
        "## Money", "",
        f"- Earned revenue: {money['currency']} {money['earned_revenue']}",
        f"- This month: {money['currency']} {money['revenue_mtd']}",
        f"- Unverified (recorded, no payment reference): {money['currency']} {money['unverified_revenue']}",
        f"- Businesses able to report a sale: {money['businesses_measuring']} of {money['businesses_total']}",
        "",
        "## Production, for contrast", "",
        f"- Jobs completed in the last {len(recent)} records: {produced}",
        "",
        "A high production number beside a zero revenue number is not a mixed",
        "result. It is one result: the company can make things and cannot yet",
        "tell whether anyone wants them.",
        "", "## Business lines", "",
    ]
    for business in businesses:
        lines.append(f"- {business['name']}: {money['currency']} {business['earned']} "
                     f"({business['status']})")
        for blocked in business.get("blocked_sources") or []:
            lines.append(f"    blocked: {blocked['blocked_on']}")
    if not experiments.get("unavailable"):
        awaiting = experiments.get("awaiting_decision") or []
        lines += ["", "## Experiments", "",
                  f"- Running: {len(experiments.get('running') or [])}",
                  f"- Awaiting a verdict now: {len(awaiting)}",
                  f"- Concluded: SCALE {experiments.get('profitable', 0)}, "
                  f"KILL {experiments.get('killed', 0)}, "
                  f"INCONCLUSIVE {experiments.get('inconclusive', 0)}"]
        for item in awaiting:
            lines.append(f"    {item['experiment_id']} {item['label']}: "
                         f"{item['verdict']} - {item['verdict_reason']}")
        if not (experiments.get("running") or experiments.get("concluded")):
            lines.append("    No experiment has ever been run. Every revenue number "
                         "above is therefore unexplained rather than disappointing.")

    if routed:
        lines += ["", "## Collection routed", ""]
        lines += [f"- {r['business']} -> {r['agent']} ({r['job_id']})" for r in routed]
    if escalate:
        lines += ["", "## For OLYMPUS", "",
                  "These cannot be fixed by routing work. Each needs an account or a",
                  "decision that only the Chairman can make.", ""]
        for item in escalate:
            lines.append(f"- {item['business']}: {item['why']}")
            lines += [f"    needs: {need}" for need in item["needs"]]

    output_dir = _home() / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job['id']}-scorecard.md"
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    stages.clear_stage("zeus")
    headline = (f"{money['businesses_measuring']} of {money['businesses_total']} businesses "
                f"can report a sale; earned {money['currency']} {money['earned_revenue']}")
    return {
        "agent": "ZEUS", "mode": "scorecard",
        "money": {k: v for k, v in money.items() if k != "businesses"},
        "businesses": businesses,
        "production_completed": produced,
        "inbox": collected,
        "experiments": {k: v for k, v in experiments.items() if k != "running"},
        "experiments_awaiting_decision": experiments.get("awaiting_decision") or [],
        "collection_routed": routed,
        "for_olympus": escalate,
        "output": str(output_path),
        "content": headline,
    }


def _run_athena(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 10 - Venture & Opportunity Lab. Pending LAO integration."""
    return _local_plan(job)


def _run_daedalus(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 9 - Micro-SaaS & AI Product Factory only."""
    return _local_plan(job)


def _run_apollo(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 6 - Digital Products & Education. Pending LAO integration."""
    return _local_plan(job)


KDP_PROCESS_NAME = "KDP Book Factory - Full Manuscript Draft"
# Confirmed live against LAO's own /processes list (2026-08-14), not guessed --
# LAO matches on the exact display name, so a near-miss silently fails to start.
IA_PROCESS_NAME = "ImagineIndia Reel - Twice Daily Production"
# Added 2026-09-04, per explicit user direction ("Wire MUSE to it too" / "So
# that MUSE hi kewal imagineindia ko drive kare, rest agent rest channel ko"):
# MUSE stays the SOLE ImagineIndia-brand worker on Floor 4, now driving TWO
# LAO processes instead of one -- the existing video reel, and this new
# static before/after square-image post. Every other Floor 4 worker
# (FABULA/LUMIO/PRAXIS/TESSERA) is untouched; their brands are unaffected.
IA_BEFORE_AFTER_PROCESS_NAME = "ImagineIndia Before/After Post"
# Added 2026-09-13, same day as the editorialPriority/Angle reel wiring was
# reverted (see _run_muse's reel branch below) -- a separate, much lighter
# LAO process: imagineindia-trend-spotlight, single Leonardo-animated image
# instead of the main reel's 5-frame Bible structure, so IRIS's research
# has somewhere it can genuinely drive the visual content.
IA_TREND_SPOTLIGHT_PROCESS_NAME = "ImagineIndia Trend Spotlight"
# Added 2026-09-18 after the Purohit Ji Ka Katla / Tripolia Bazaar fire reel
# hit 216k views (vs an ~8.9k median) -- a THIRD separate LAO process, same
# 5-frame production complexity as the main reel but a crisis-hook/reveal
# story grammar grounded in a real, current, specific local incident IRIS
# researches, with no location catalogue at all.
IA_NEWS_HOOK_PROCESS_NAME = "ImagineIndia News Hook Reel"
# Matches the imagineindia-instagram-reel package's own input_schema default
# for locationManifestPath (package.json). Duplicated here (not read from the
# package) only so _peek_next_ia_location below can predict a location
# without asking LAO to run anything -- see that function's docstring.
IA_LOCATIONS_MANIFEST_PATH = r"C:\Users\pc\Documents\LAO\imagineindia\IA_Locations.json"


def _find_lao_robot_config() -> Path:
    """Find the active LAO robot config across desktop-session layouts.

    Service restarts do not always inherit the same HOME used by the desktop
    host.  Prefer an explicit path, then LOCALAPPDATA/USERPROFILE and finally
    Path.home.  Only an existing file is returned.
    """
    import glob

    explicit = os.environ.get("LAO_ROBOT_CONFIG", "").strip()
    candidates: list[str] = [explicit] if explicit else []
    roots = {
        os.environ.get("LOCALAPPDATA", "").strip(),
        str(Path(os.environ.get("USERPROFILE", "")) / "AppData/Local") if os.environ.get("USERPROFILE") else "",
        str(Path.home() / "AppData/Local"),
    }
    suffix = ("Packages/Claude_*/LocalCache/Roaming/Claude/"
              "local-agent-mode-sessions/**/lao-platform/robot-worker/config.local.json")
    for root in filter(None, roots):
        candidates.extend(glob.glob(str(Path(root) / suffix), recursive=True))
    existing = [Path(item) for item in candidates if item and Path(item).is_file()]
    if not existing:
        raise RuntimeError("LAO production robot config was not found")
    # Newest session wins; stale Claude session directories can remain for weeks.
    return max(existing, key=lambda item: item.stat().st_mtime)


def _muse_publish_facebook(image_path: str, caption: str) -> dict[str, Any]:
    """Publish one local image through Meta Graph using LAO's encrypted vault.

    The secret is resolved robot-to-vault in memory and is never copied into
    ONE. Exact-caption reconciliation makes a retry safe against duplicates.
    """
    import urllib.parse
    import urllib.request

    config_path = _find_lao_robot_config()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    folder_id = os.environ.get("LAO_ASSET_FOLDER_ID", "446427d7-5722-4d59-a487-8de321325cbc")
    asset_name = os.environ.get("LAO_FACEBOOK_PUBLISH_ASSET", "imagineIndiaFacebookPublishingToken")
    resolve_url = (str(config["orchestrator_url"]).rstrip("/") + "/assets/resolve/" +
                   urllib.parse.quote(asset_name) + "?folder_id=" + urllib.parse.quote(folder_id))
    request = urllib.request.Request(resolve_url, headers={"Authorization": "Bearer " + config["robot_token"]})
    with urllib.request.urlopen(request, timeout=30) as response:
        credential = json.loads(response.read())["value"]
    token = credential if isinstance(credential, str) else str(credential.get("password") or "")
    page_id = os.environ.get("IMAGINEINDIA_FACEBOOK_PAGE_ID", "1208655322324462")
    if not token or not page_id:
        raise RuntimeError("ImagineIndia Facebook publishing credential is incomplete")

    # Reconcile before create: exact same caption on the Page means this
    # logical delivery already landed and must not be posted twice.
    graph = "https://graph.facebook.com/v20.0"
    auth_headers = {"Authorization": f"Bearer {token}"}
    recent = httpx.get(f"{graph}/{page_id}/photos", params={
        "type": "uploaded", "fields": "id,name,created_time,link", "limit": 25,
    }, headers=auth_headers, timeout=60)
    recent.raise_for_status()
    for row in recent.json().get("data", []):
        if str(row.get("name") or "").strip() == caption.strip():
            return {"status": "already_published", "post_id": row.get("id"),
                    "permalink": row.get("link") or "", "verified": True}

    with Path(image_path).open("rb") as image:
        published = httpx.post(f"{graph}/{page_id}/photos",
            data={"caption": caption, "published": "true"}, headers=auth_headers,
            files={"source": (Path(image_path).name, image, "image/jpeg")}, timeout=180)
    published.raise_for_status()
    post_id = str(published.json().get("post_id") or published.json().get("id") or "")
    if not post_id:
        raise RuntimeError("Facebook accepted no verifiable post id")
    verified = httpx.get(f"{graph}/{post_id}", params={
        "fields": "id,permalink_url,created_time",
    }, headers=auth_headers, timeout=60)
    verified.raise_for_status()
    proof = verified.json()
    return {"status": "published", "post_id": post_id,
            "permalink": proof.get("permalink_url") or "", "verified": proof.get("id") == post_id}


def _sanjeevani_research() -> Any | None:
    """Load only Sanjeevani's reusable library, never its app or database."""
    import importlib.util
    import sys
    path = Path(os.environ.get(
        "SANJEEVANI_RESEARCH_LIBRARY",
        r"E:\ONE-SUITE\sanjeevani\research_library.py",
    ))
    if not path.is_file():
        return None
    key = "sanjeevani_reusable_research"
    cached = sys.modules.get(key)
    if cached is not None:
        return cached
    try:
        spec = importlib.util.spec_from_file_location(key, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(key, None)
        return None


def _local_research(prompt: str, max_tokens: int = 2200,
                    evidence: dict[str, Any] | None = None) -> tuple[str, str]:
    """Interpret captured evidence with a local model; never spends API money.

    Discovery is performed separately by allowlisted collectors.  Ollama gets
    only that captured evidence, so it cannot claim that it browsed the web or
    introduce uncited sources. Paid research is an explicit opt-in fallback.
    """
    base = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    preferred = os.environ.get("ONE_LOCAL_RESEARCH_MODEL", "qwen3.5:9b").strip()
    try:
        reusable = _sanjeevani_research()
        if reusable is not None:
            result = reusable.ollama_synthesize(
                prompt, evidence or {"eligible": [], "catalog_evidence": []},
                base_url=base, preferred_model=preferred, max_tokens=max_tokens,
            )
            return str(result["text"]), ""
        # Compatibility fallback only when the canonical Sanjeevani library is
        # unavailable. It does not gain network authority.
        tags = httpx.get(base + "/api/tags", timeout=10).json().get("models", [])
        installed = [str(item.get("name") or item.get("model") or "") for item in tags]
        model = preferred if preferred in installed else next(
            (name for name in ("qwen3.5:9b", "qwen3:8b", "ibm/granite4.1:3b", "phi4-mini:latest")
             if name in installed), ""
        )
        if not model:
            return "", "No approved local research model is installed in Ollama"
        response = httpx.post(
            base + "/api/chat",
            json={
                "model": model, "stream": False, "think": False,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": 0.1, "num_predict": max_tokens},
            },
            timeout=300,
        )
        response.raise_for_status()
        text = str((response.json().get("message") or {}).get("content") or "").strip()
        return (text, "") if text else ("", f"Local model {model} returned no text")
    except Exception as exc:  # noqa: BLE001 - caller records an honest block
        return "", f"Local research failed: {type(exc).__name__}: {exc}"


def _research_synthesis(prompt: str, max_tokens: int = 2200,
                        evidence: dict[str, Any] | None = None) -> tuple[str, str]:
    """Sanjeevani/local-only research for every company floor head.

    This is a hard product boundary, not a preference flag: autonomous floor
    research must never spend Anthropic/OpenAI/Gemini (or another cloud-model)
    credits. A failed local run stops honestly instead of silently buying a
    fallback response.
    """
    text, note = _local_research(prompt, max_tokens=max_tokens, evidence=evidence)
    if text:
        return text, ""
    return "", note + "; cloud-model fallback is forbidden for floor heads"


# source_url is deliberately absent. Measured 2026-09-24: the 53 items carried
# 16,371 chars of URL - half the bundle - and these are Google News RSS links,
# base64 blobs up to 806 chars that tokenise at roughly one token per character.
# The prompts tell the model to cite the evidence_id in square brackets, and
# _evidence_urls() maps those ids back to real URLs afterwards, so nothing that
# reaches the brief is lost.
#
# That claim was only true of the media floor until 2026-10-14. This floor's
# own contract asked for "URLs or named current sources" - one it could not
# supply and one nothing could check - so every KDP run obeyed its prompt and
# failed the provenance gate. Both prompts now ask for the ids.
# Keys whose values are links. Dropped from anything handed to a model that
# is being asked to cite ids: a link is the wrong answer and a tempting one.
_URL_KEYS = frozenset({"url", "source_url", "link", "permalink",
                       "canonical_url", "source_urls"})
_RADAR_ITEM_FIELDS = ("evidence_id", "title", "age_hours",
                      "freshness_bucket", "freshness_eligible", "role", "source_type")
_RADAR_CANDIDATE_FIELDS = ("topic", "score", "build_eligible", "blockers")
_RADAR_WINNER_FIELDS = ("topic", "score", "build_eligible", "dimensions", "blockers")


def _cited_sources_block(snapshot: dict[str, Any], brief: str) -> str:
    """The cited evidence ids, expanded back into their real source URLs."""
    urls = _evidence_urls(snapshot, brief)
    if not urls:
        return ""
    rows = chr(10).join("- `" + eid + "` " + url for eid, url in sorted(urls.items()))
    return chr(10) + "## Sources cited above" + chr(10) * 2 + rows + chr(10)

def _evidence_block(brief: str) -> str:
    """Everything written under "EVIDENCE:", not just the rest of that line.

    _marker deliberately stops at the newline (see its own docstring), which
    is right for one-line fields and wrong for this one: evidence is written
    as a bullet list under the label, so the label's own line is blank and
    _marker returned "". The gate then reported "direct evidence URLs: 0"
    about a field it had never actually read.
    """
    match = re.search(r"^[ \t]*\**EVIDENCE\**[ \t]*:", brief, re.MULTILINE | re.IGNORECASE)
    if not match:
        return ""
    rest = brief[match.end():]
    # Stops at the next ALL-CAPS marker line, which is how this contract
    # separates fields.
    end = re.search(r"^[ \t]*\**[A-Z][A-Z_]{3,}\**[ \t]*:", rest, re.MULTILINE)
    return rest[:end.start()].strip() if end else rest.strip()


def _unknown_cited_ids(snapshot: dict[str, Any], evidence: str) -> int:
    """Bracketed ids that no radar item in this run carries.

    Distinct from citing nothing at all, and far more telling: it means the
    model produced identifier-shaped text rather than reading one. Seen twice
    on 2026-10-14 - first a base64 fragment it had never been shown, then the
    prompt's own specimen id copied verbatim. Counting them separately keeps
    "cited nothing" and "cited something invented" from reading alike.
    """
    known = {str(item.get("evidence_id") or "")
             for item in (snapshot.get("items") or []) if isinstance(item, dict)}
    cited = set(re.findall(r"\[([A-Za-z0-9_\-]{8,})\]", evidence or ""))
    return len(cited - known)


def _unresolved_citations(snapshot: dict[str, Any], evidence: str) -> int:
    """Quoted sources in the evidence that this run never actually collected.

    Measured on run hermes-a75ab9b40ca8 (2026-10-10): the snapshot held 48
    finance and retirement items, and the model's evidence cited 26 quoted
    mental-health headlines, none of which appeared in it. The gate rejected
    the run, correctly - but reported it as missing URLs, which reads like a
    formatting nit rather than fabricated provenance. Counting these makes
    the difference legible in the refusal.
    """
    titles = [str(item.get("title") or "").strip().lower()
              for item in (snapshot.get("items") or []) if isinstance(item, dict)]
    unresolved = 0
    for quote in re.findall(r"[\"“]([^\"”]{15,200})[\"”]", evidence):
        probe = quote[:60].lower()
        if not any(probe in title or title[:60] in quote.lower() for title in titles if title):
            unresolved += 1
    return unresolved


def _evidence_urls(snapshot: dict[str, Any], text: str) -> dict[str, str]:
    """Map every evidence_id the model cited back to its real source_url.

    The ids travel to the model; the URLs stay here. Only ids actually present
    in the snapshot are returned, so a hallucinated id resolves to nothing
    rather than to a plausible-looking link.
    """
    known = {str(item.get("evidence_id") or ""): str(item.get("source_url") or "")
             for item in (snapshot.get("items") or []) if isinstance(item, dict)}
    known.pop("", None)
    cited = set(re.findall(r"[0-9a-f]{20}", str(text or "")))
    return {eid: url for eid, url in known.items() if eid in cited and url}


def _without_urls(value: Any) -> Any:
    """The same structure with every URL taken out of it.

    The winner row goes into the commission prompt whole, and its persistence
    evidence carries one Google News link per item - 66 of them on 2026-10-14,
    against zero evidence_ids, in 30,535 characters. The prompt asks the model
    to end each claim with "the evidence_id of the radar item it comes from",
    and those links were the only identifier-shaped strings sitting next to the
    facts it was reasoning about. It copied them: two of the three ids the
    16:30 run cited are verbatim Google News URL fragments from this payload,
    and the third, once it was following the pattern, appears nowhere in the
    snapshot at all. Five runs were refused by the provenance gate for this.

    The real evidence_ids live on the radar items, which reach the model as
    their own bundle. Taking the links out leaves nothing else to reach for -
    and takes most of the payload's size with them, which the context window
    has been short of before (see research_evidence above).
    """
    if isinstance(value, dict):
        return {key: _without_urls(item) for key, item in value.items()
                if key not in _URL_KEYS}
    if isinstance(value, list):
        return [_without_urls(item) for item in value]
    if isinstance(value, str) and value.strip().lower().startswith(("http://", "https://")):
        return ""
    return value


def _compact_radar(snapshot: dict[str, Any], *, max_items: int = 30,
                   include_items: bool = True) -> dict[str, Any]:
    """The demand snapshot cut down to what a local model can actually hold.

    Keeps every field the prompt tells the model it may cite -- the evidence_id
    and source_url above all -- and drops what it is forbidden to quote anyway:
    raw_signal, score_reasons, and each candidate's own nested evidence bundle.
    Roughly 310,000 chars becomes roughly 37,000.
    """
    if not isinstance(snapshot, dict):
        return {}
    items = [
        {key: item.get(key) for key in _RADAR_ITEM_FIELDS}
        for item in (snapshot.get("items") or [])[:max_items]
        if isinstance(item, dict)
    ]
    candidates = [
        {key: row.get(key) for key in _RADAR_CANDIDATE_FIELDS}
        for row in (snapshot.get("candidates") or [])
        if isinstance(row, dict)
    ]
    winner = snapshot.get("winner") or {}
    return {
        "captured_at": snapshot.get("captured_at"),
        "markets": snapshot.get("markets"),
        "queries": snapshot.get("queries"),
        "freshness_counts": snapshot.get("freshness_counts"),
        "freshness_policy": snapshot.get("freshness_policy"),
        "source_health": snapshot.get("source_health"),
        "corroboration": snapshot.get("corroboration"),
        "commissioning_eligible": snapshot.get("commissioning_eligible"),
        # The prompt copy leaves these out: the same rows already travel as the
        # untrusted-evidence bundle, and sending them twice is what pushed the
        # payload past the context window in the first place.
        "items": items if include_items else "supplied separately as UNTRUSTED EVIDENCE",
        "item_count_total": len(snapshot.get("items") or []),
        "catalog_evidence": (snapshot.get("catalog_evidence") if include_items
                             else "supplied separately as UNTRUSTED EVIDENCE"),
        "candidates": candidates,
        "winner": {key: winner.get(key) for key in _RADAR_WINNER_FIELDS} if isinstance(winner, dict) else {},
    }


def _marker(text: str, key: str, default: str = "") -> str:
    """Extract "KEY: value" from free-form LLM synthesis output.

    Bug fixed 2026-09-18: the original regex used bare \\s* around the
    colon and value, and \\s matches newlines -- so a marker with an EMPTY
    value (no content on its own line) let \\s* silently cross into the
    NEXT line and capture that line's own "OTHER_KEY:" label text as if it
    were this key's value. Every caller before the imagineindia-news-hook-
    reel wiring always had non-empty values for every marker it asked for,
    so this never surfaced -- PLACE/INCIDENT_SUMMARY/SEARCH_TERMS are the
    first markers ever deliberately allowed to come back empty. Fixed by
    restricting internal whitespace to space/tab only ([ \\t]*), which
    cannot cross a newline, so an empty-valued line correctly fails to
    match and this returns `default` instead of leaking the next line.
    """
    match = re.search(
        rf"^[ \t]*\**{re.escape(key)}\**[ \t]*:[ \t]*\**(.+?)\**[ \t]*$",
        text, re.MULTILINE | re.IGNORECASE,
    )
    return match.group(1).strip() if match else default


def _publishing_skill_text() -> str:
    """Load HERMES's floor-owned method; runtime code is not its policy owner."""
    root = floors_bridge.floors_root()
    if root is None:
        return ""
    base = root / "floor_05_publishing" / "head" / "hermes" / "skills" / "publishing-demand-radar"
    parts: list[str] = []
    for path in (base / "SKILL.md", base / "references" / "evidence-and-scoring.md",
                 base / "references" / "signal-sources.md"):
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n\n".join(parts)[:16000]


def _delivered_book_lane(run_dir: str, title: str) -> dict[str, Any]:
    """Is the book LAO actually wrote still inside the catalogue lane?

    The commissioning gate judges the brief. Nothing judged the book until
    this: LAO is handed `mode`, `region` and a one-line `topicOverride`, and
    nothing else - no lane, no series, no rejection list - so it is free to
    drift, and it does. On 2026-10-23 a commission for "The Business Plan
    Workbook" came back as "The Venture Ledger", a startup-finance book built
    around two invented people rebuilding a cloud kitchen.

    Read what was delivered, not what was asked for.
    """
    meta: dict[str, Any] = {}
    path = Path(run_dir) / "kdp_metadata.json" if run_dir else None
    if path is not None and path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
        except (OSError, ValueError):
            meta = {}

    keywords = meta.get("keywords")
    identity = "\n".join(str(part) for part in (
        meta.get("title") or title,
        meta.get("subtitle") or "",
        " ".join(str(k) for k in keywords) if isinstance(keywords, list) else (keywords or ""),
    ) if part)

    verdict = publishing_strategy.authority_fit(identity)
    return {
        "passed": bool(verdict["passed"]),
        "matches": verdict["matches"],
        "delivered_title": str(meta.get("title") or title),
        "read_metadata": bool(meta),
        # A missing kdp_metadata.json is not a pass. It is a book nobody can
        # check, and this gate exists precisely because the unchecked ones
        # were the ones that drifted.
        "identity": identity[:400],
    }


def _media_skill_text() -> str:
    """Load IRIS's floor-owned trend-research method; same pattern as
    _publishing_skill_text -- runtime code is not its policy owner. Added
    2026-09-12 after a live comparison showed a single blended Sanjeevani
    query surfaces almost nothing eligible (see the skill's own docstring
    for the category-query discipline this replaces it with)."""
    root = floors_bridge.floors_root()
    if root is None:
        return ""
    base = root / "floor_04_media" / "head" / "ia" / "skills" / "imagineindia-trend-radar"
    parts: list[str] = []
    for path in (base / "SKILL.md", base / "references" / "evidence-and-scoring.md",
                 base / "references" / "signal-sources.md"):
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n\n".join(parts)[:16000]


_IA_PEEK_LANDMARK_TYPES = frozenset({"landmark"})
_IA_PEEK_LOCAL_ICON_TYPES = frozenset(
    {"market", "station", "road", "urban_plaza", "transit_hub", "heritage_plaza"}
)
_IA_PEEK_WATER_TYPES = frozenset({"river", "lake", "waterfront"})
_IA_PEEK_IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def _ia_peek_days_since(used_date: str | None, today) -> int:
    if not used_date:
        return 10**9
    try:
        d = datetime.strptime(used_date, "%Y-%m-%d").date()
    except Exception:  # noqa: BLE001
        return 10**9
    return (today - d).days


def _ia_peek_water_blocked_this_month(manifest: dict, today) -> bool:
    this_month = today.strftime("%Y-%m")
    for zone_entries in manifest.get("zones", {}).values():
        for entry in zone_entries:
            if entry.get("type") in _IA_PEEK_WATER_TYPES and str(entry.get("used_date") or "").startswith(this_month):
                return True
    return False


def _ia_peek_candidate_weight(entry: dict, weights: dict | None) -> float:
    """Same as the LAO engine's _ia_candidate_weight and imagineindia_learning.candidate_weight."""
    if not weights:
        return 1.0
    weight = float((weights.get("types") or {}).get(str(entry.get("type") or ""), 1.0))
    if entry.get("sacred"):
        weight *= float(weights.get("sacred") or 1.0)
    weight *= float((weights.get("locations") or {}).get(str(entry.get("id") or ""), 1.0))
    return round(weight, 4)


def _ia_peek_pick_from_zone(zone_name: str, manifest: dict, today, cooldown_days: int, water_blocked: bool,
                            weights: dict | None = None):
    entries = manifest.get("zones", {}).get(zone_name, [])
    state_last_used: dict[str, str] = {}
    for entry in entries:
        used_date = entry.get("used_date")
        state = entry.get("state")
        if used_date and state:
            if state not in state_last_used or used_date > state_last_used[state]:
                state_last_used[state] = used_date
    for tier_types in (None, _IA_PEEK_LANDMARK_TYPES, _IA_PEEK_LOCAL_ICON_TYPES, _IA_PEEK_WATER_TYPES):
        if tier_types is _IA_PEEK_WATER_TYPES and water_blocked:
            continue
        if tier_types is None:  # density-first pass, mirrors workflow_engine._ia_pick_from_zone
            tier_entries = [e for e in entries if int(e.get("density") or 0) >= 5
                            and not (water_blocked and e.get("type") in _IA_PEEK_WATER_TYPES)]
        else:
            tier_entries = [e for e in entries if e.get("type") in tier_types]
        if not tier_entries:
            continue
        eligible = [e for e in tier_entries if _ia_peek_days_since(e.get("used_date"), today) >= cooldown_days]
        if not eligible:
            continue
        eligible.sort(key=lambda e: (int(e.get("density") or 3),
                                     round(_ia_peek_candidate_weight(e, weights) * 10) / 10,
                                     _ia_peek_days_since(state_last_used.get(e.get("state")), today)),
                      reverse=True)
        return eligible[0]
    return None


def _refresh_imagineindia_learning() -> str:
    """Once a day, before IRIS predicts ImagineIndia's next location: read every reel's
    Instagram insights, relearn, and rewrite IA_Performance_Weights.json - the file
    LAO's location picker orders eligible places by. Also refreshes ImagineIndia's
    Sanjeevani hook library and reel-format scout. Read-only toward Instagram;
    best-effort, so a failure here never stops IRIS. Returns a one-line summary."""
    learning = floors_bridge.load("floor_04_media", "imagineindia_learning")
    trends = floors_bridge.load("floor_04_media", "imagineindia_trends")
    media = floors_bridge.load("floor_04_media", "aibyvineet_publish")
    if learning is None or media is None:
        return "ImagineIndia learning modules are not available"
    brand_dir = _home() / "agent_outputs" / "imagineindia"
    now = datetime.now(timezone.utc)
    notes: list[str] = []
    if learning.stale(brand_dir, now):
        from openjarvis.core import social_accounts

        account = social_accounts.get_account("imagineindia", "instagram")
        if account is None:
            return "ImagineIndia's Instagram account is not in ONE's vault"
        stages.set_stage("ia", stages.EXECUTING, "Reading how ImagineIndia's reels did on Instagram")
        get = media.graph_reader(token=account.token,
                                 graph_base=social_accounts.PLATFORMS["instagram"]["graph_base"])
        result = learning.refresh(brand_dir, get, IA_LOCATIONS_MANIFEST_PATH, now)
        learned = result["learning"]
        notes.append(f"{learned['scored_reels']} reels measured, median {learned['median_views']:,} views, "
                     f"{learned['over_1m']} over 1M; location weights rewritten")
    if trends is not None:
        cycle = trends.trends.run_cycle(
            brand_dir, now=now, profile=trends.PROFILE,
            video_search=_kairos_video_search if _sanjeevani_reel() is not None else None,
            web_search=_kairos_web_search if _sanjeevani_research() is not None else None,
            read_page=_kairos_read_page if _sanjeevani_research() is not None else None,
            stage=lambda detail: stages.set_stage("ia", stages.EXECUTING, detail))
        proposals = [p["name"] for p in (cycle.get("layout_scout") or {}).get("proposals") or []]
        if cycle.get("scout_refreshed") and proposals:
            notes.append("new reel formats for the Chairman: " + ", ".join(proposals))
    return "; ".join(notes)


def _peek_next_ia_location(manifest_path: str, *, cooldown_days: int = 7) -> dict[str, Any] | None:
    """Read-only prediction of which real place LAO's own select_next_ia_location
    action (workflow_engine.py, the LAO robot -- a different process IRIS has
    no direct handle to) will actually pick next. Ported line-for-line from
    that function's algorithm (day-of-week zone -> landmark/local-icon/water
    tier -> 7-day cooldown -> state fairness -> once-a-month water cap) so the
    prediction matches production, not an approximation.

    Added 2026-09-13 after live verification of the editorialPriority/Angle
    wiring showed it structurally couldn't work: the IA Bible requires Frame
    1's conflict to be a real, LOCAL problem at whatever location the
    deterministic rotation lands on (Golden Temple, Red Fort, ...) -- an
    abstract macro-trend theme researched independently of any specific place
    almost never has an honest connection to a random pick, so ChatGPT was
    correctly declining it nearly every run. Predicting the actual next
    location lets IRIS's research target that real place's own current
    situation instead, giving the connection a genuine chance of being true.

    NEVER writes to the manifest -- this is the same non-destructive peek the
    LAO engine itself already supports via mark_used=False (used by its own
    chatgpt-dryrun package), just re-implemented here in-process since IRIS
    cannot invoke a single LAO workflow step directly, only start/poll a full
    job. Must be kept in sync with workflow_engine.py's
    _select_next_ia_location / _ia_pick_from_zone / _ia_water_blocked_this_month
    if that algorithm ever changes -- this is a deliberate, documented
    duplication, not the source of truth, and a real LAO run between this
    peek and MUSE's actual dispatch (another manual trigger, a dry-run) can
    still make the prediction stale; downstream still treats it as a
    prediction to check, never a fact to assume.

    Returns None on any read/parse problem (missing file, malformed JSON,
    empty manifest) rather than raising, so a manifest issue degrades IRIS
    back to theme-only research instead of failing the whole run.
    """
    try:
        path = Path(manifest_path)
        if not path.is_file():
            return None
        manifest = json.loads(path.read_text(encoding="utf-8"))
        zone_order = manifest.get("zone_order") or list(manifest.get("zones", {}).keys())
        if not zone_order:
            return None
        now_ist = datetime.now(_IA_PEEK_IST)
        today = now_ist.date()
        weekday = now_ist.weekday()
        day_zone_map = {i: zone_order[i] for i in range(min(6, len(zone_order)))}
        water_blocked = _ia_peek_water_blocked_this_month(manifest, today)
        try:
            weights = json.loads(path.with_name("IA_Performance_Weights.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - no weights file: plain state-fairness order, as LAO does
            weights = None

        chosen = None
        chosen_zone = None
        if weekday in day_zone_map:
            chosen_zone = day_zone_map[weekday]
            chosen = _ia_peek_pick_from_zone(chosen_zone, manifest, today, cooldown_days, water_blocked, weights)
        else:
            best_zone, best_count = None, -1
            for zone_name in zone_order:
                entries = manifest.get("zones", {}).get(zone_name, [])
                count = sum(
                    1 for e in entries
                    if e.get("type") in (_IA_PEEK_LANDMARK_TYPES | _IA_PEEK_LOCAL_ICON_TYPES)
                    and _ia_peek_days_since(e.get("used_date"), today) >= cooldown_days
                )
                if count > best_count:
                    best_zone, best_count = zone_name, count
            if best_zone:
                chosen_zone = best_zone
                chosen = _ia_peek_pick_from_zone(best_zone, manifest, today, cooldown_days, water_blocked, weights)

        if chosen is None:
            for zone_name in zone_order:
                if zone_name == chosen_zone:
                    continue
                candidate = _ia_peek_pick_from_zone(zone_name, manifest, today, cooldown_days, water_blocked, weights)
                if candidate is not None:
                    chosen, chosen_zone = candidate, zone_name
                    break

        if chosen is None:
            all_entries = [
                (zone_name, entry)
                for zone_name in zone_order
                for entry in manifest.get("zones", {}).get(zone_name, [])
            ]
            if not all_entries:
                return None
            all_entries.sort(key=lambda ze: _ia_peek_days_since(ze[1].get("used_date"), today), reverse=True)
            chosen_zone, chosen = all_entries[0]

        if chosen is None:
            return None
        return {
            "name": chosen.get("name"),
            "state": chosen.get("state"),
            "type": chosen.get("type"),
            "zone": chosen_zone,
        }
    except Exception:  # noqa: BLE001
        return None


# The four category queries from imagineindia-trend-radar's
# references/signal-sources.md. Kept here (not re-derived from the skill
# text) so a change to the skill's prose can't silently change what actually
# gets queried without a matching code review -- the skill document is the
# explanation of why these four and this shape; this tuple is what runs.
_MEDIA_TREND_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("heritage_monument", "India heritage monument temple restoration controversy news"),
    ("civic_infra", "India road construction traffic infrastructure protest news"),
    ("festival", "India festival pilgrimage crowd temple news"),
    ("viral_format", "India viral AI photo trend social media"),
    # Added 2026-09-18 after a direct comparison: the 4 categories above
    # structurally cannot surface a fire/collapse/safety incident (the
    # Purohit Ji Ka Katla fire and the Surat Salasar Textile Market fire
    # both fell entirely outside heritage_monument's temple-only scope and
    # civic_infra's road/traffic-only scope). This is imagineindia-news-
    # hook-reel's primary source category -- without it, that format's own
    # commissioning_eligible gate can never fire on the exact story type it
    # exists for.
    ("disaster_incident", "India market fire building collapse accident news today"),
)


def _sanjeevani_trends() -> Any | None:
    """Sanjeevani's trend_discovery module -- additive, lives next to
    research_library.py (Sanjeevani is the single source of information; ONE
    only loads and calls it, same pattern as _sanjeevani_research)."""
    import importlib.util
    import sys
    lib_path = Path(os.environ.get(
        "SANJEEVANI_RESEARCH_LIBRARY", r"E:\ONE-SUITE\sanjeevani\research_library.py"))
    path = lib_path.with_name("trend_discovery.py")
    if not path.is_file():
        return None
    key = "sanjeevani_trend_discovery"
    cached = sys.modules.get(key)
    if cached is not None:
        return cached
    try:
        spec = importlib.util.spec_from_file_location(key, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(key, None)
        return None


def _sanjeevani_travel() -> Any | None:
    """Sanjeevani's travel_discovery module (scored, news-led travel stories); same loading pattern as above."""
    import importlib.util
    import sys
    lib_path = Path(os.environ.get(
        "SANJEEVANI_RESEARCH_LIBRARY", r"E:\ONE-SUITE\sanjeevani\research_library.py"))
    path = lib_path.with_name("travel_discovery.py")
    if not path.is_file():
        return None
    key = "sanjeevani_travel_discovery"
    cached = sys.modules.get(key)
    if cached is not None:
        return cached
    try:
        spec = importlib.util.spec_from_file_location(key, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(key, None)
        return None


# The Chairman's rule (2026-10-08): a story about India or Indian travellers is told in Hinglish with the Hindi in
# Devanagari; a story from outside India is told entirely in English. Every stage reads the video's language from
# here - script, voice lexicon, spoken-language tag, subtitles - so the two never disagree.
SONIA_LANGUAGES: dict[str, dict[str, Any]] = {
    "hinglish": {
        "label": "Hinglish (Hindi in Devanagari)",
        "targetLanguage": ("Natural conversational Hinglish; Hindi words in Devanagari, "
                           "English terms and official place names in Latin"),
        "scriptRule": "",  # the package's own Devanagari rule
        "lexicon": True,
    },
    "en": {
        "label": "English",
        "targetLanguage": "Natural conversational English, warm and clear for Indian travellers; no Hindi",
        "scriptRule": (
            "SCRIPT AND PRONUNCIATION RULE - mandatory for every spoken line: write the whole narration in natural, "
            "conversational English. Use no Hindi or Hinglish words and no Devanagari script at all. Keep brand "
            "names, airline names and official place names in their usual spelling. Prefer short, plain words that "
            "a voice reads naturally; spell out symbols and abbreviations that would sound awkward when spoken. "
            "Before returning, scan every narration line and remove any Hindi word that slipped in."),
        "lexicon": False,
    },
}


_BARE_CUE = re.compile(r"(?m)^[ \t]*\[?[ \t]*(\d{1,2}):(\d{2})[ \t]*[–—-][ \t]*(\d{1,2}):(\d{2})[ \t]*\]?[ \t]*$")


def normalize_script_cues(script: str) -> str:
    """Rewrite every cue line as [m:ss–m:ss], the one shape the voice, SEO and subtitle parsers all read.

    The first English script (Air France, 2026-10-08) wrote its cues as bare "00:00 – 00:30" lines. The robot's
    ElevenLabs step only splits on bracketed cues, so it sent all 12,974 characters in one request and ElevenLabs
    refused anything over 10,000; the chapter and subtitle parsers would have missed them too."""
    return _BARE_CUE.sub(lambda m: f"[{int(m[1])}:{m[2]}–{int(m[3])}:{m[4]}]", script or "")


def sonia_video_language(pick: dict[str, Any]) -> str:
    """'hinglish' when the chosen story concerns India or Indian travellers, otherwise 'en'."""
    india = bool(pick.get("india_angle")) or str(pick.get("destination") or "").strip().lower() == "india"
    return "hinglish" if india else "en"


def sonia_language_profile(payload_or_record: dict[str, Any] | None) -> dict[str, Any]:
    """The language profile a job or plan record carries; older runs without one were Hinglish."""
    key = str((payload_or_record or {}).get("language") or "hinglish").strip().lower()
    return SONIA_LANGUAGES.get(key, SONIA_LANGUAGES["hinglish"]) | {"key": key if key in SONIA_LANGUAGES else "hinglish"}


_SONIA_TRAVEL_INTENT = re.compile(
    r"\b(?:visa|e-?visa|entry rule|passport|immigration|touris(?:m|t)|travell?er|travel advisory|"
    r"hotel|resort|hostel|stay|itinerary|attraction|things to do|best time to visit|weather advisory|"
    r"airline|airport|airfare|ticket fare|flight cancellations?|scheduled flights?|passenger flights?|"
    r"direct flights?|new flight route|route launch|train|railway|"
    r"cruise|ferry|booking|baggage|transit|layover|road trip)\b", re.I)


def _sonia_has_travel_intent(candidate: dict[str, Any]) -> bool:
    """A place in a headline is not a travel story.

    The Queen Suthida fighter-flight story scored for Thailand and YouTube
    velocity despite changing no traveller decision. Require an explicit
    trip-planning, destination, transport or entry signal before commission.
    """
    text = " ".join([str(candidate.get("title") or ""),
                     *[str(v) for v in candidate.get("headlines") or []]])
    return bool(_SONIA_TRAVEL_INTENT.search(text))


_STORY_STOP = {"the", "a", "an", "to", "of", "in", "on", "for", "and", "or", "its", "it",
               "with", "from", "by", "as", "at", "is", "are", "new", "now", "this", "that",
               "what", "how", "why", "you", "your", "check", "travel", "flights", "flight"}


def _story_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", str(text or "").casefold())
    return {w for w in words if len(w) > 2 and w not in _STORY_STOP}


def _sonia_repeats_recent_story(headline: str, recent_titles: list[str],
                                *, overlap: float = 0.4) -> str:
    """The recent title this headline retells, or '' when it is a new story.

    The policy has two different rules and they are not the same window:
    same_day_destination_reuse is about the destination and lasts a day, while
    duplicate_window_days is about the story and lasts a month. Applying the
    month to the destination blocks every popular country - on 2026-10-17 it
    left Japan, Singapore, Thailand, Vietnam and the UAE all "covered in the
    last 38 videos" and no story could be commissioned at all.

    So the month is applied here, to the story itself. "Air India Adds
    Non-stop Delhi To Osaka Flights To Its February 2027 Roster" and
    yesterday's "Japan Flights 2027: Delhi to Osaka vs Tokyo Direct Routes"
    share delhi, osaka and 2027; a different Japan story does not.
    """
    wanted = _story_tokens(headline)
    if len(wanted) < 3:
        return ""
    for title in recent_titles:
        seen = _story_tokens(title)
        if not seen:
            continue
        shared = wanted & seen
        # Measured against the shorter of the two, and with a floor on the
        # count. A news headline carries a lot of filler the title of a Short
        # does not: the Osaka pair shares delhi, osaka and 2027, which is
        # three of the seven words in the shorter one but only three of ten in
        # the longer, so a one-sided ratio missed it.
        if len(shared) >= 3 and len(shared) / min(len(wanted), len(seen)) >= overlap:
            return title
    return ""


def _sonia_content_policy() -> dict[str, Any]:
    """VISTA's own content policy, as data rather than as a document.

    floor_12_youtube_studio/agents/vista/content-policy.json has declared
    duplicate_window_days, same_day_destination_reuse and the weekday hooks
    since the floor was written, and no code had ever read it - the same shape
    as Floor 05's capabilities.yaml, which left IMPRIMATUR dormant. Read now,
    with the file's own numbers as the defaults so a missing file changes
    nothing.
    """
    root = floors_bridge.floors_root()
    if root is not None:
        path = (root / "floor_12_youtube_studio" / "agents" / "vista" / "content-policy.json")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"duplicate_window_days": 30}


def _sonia_recent_topics(prior: list[str], *, limit: int = 25,
                         include_shorts: bool = False,
                         within_days: float | None = None) -> list[str]:
    """Merge durable upload and commission history into IRIS's variety gate.

    Obsidian ``ANGLE:`` notes are useful memory, but they are not the delivery
    ledger. A successful upload can lack that prose marker, and a failed
    production still needs to reserve its topic so the next trigger does not
    commission the same story again. Read both authorities before discovery.
    """
    # (when, title): everything is ordered by recency before it is used, because
    # the caller only looks at the first few. The Osaka Short of 2026-10-16 sat
    # at position 25 of 25 - it reached the list only through the upload ledger,
    # which was appended last - so the next day's check never saw it and
    # commissioned the same story again.
    dated: list[tuple[float, str]] = []
    found: list[str] = []
    output_dir = _home() / "agent_outputs"
    try:
        rankings = sorted(
            output_dir.glob("*-yatra-story-ranking.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        job_ids = [path.name.removesuffix("-yatra-story-ranking.json") for path in rankings[:limit * 3]]
        job_tasks: dict[str, str] = {}
        if job_ids:
            placeholders = ",".join("?" for _ in job_ids)
            try:
                db = _connect()
                try:
                    job_tasks = {
                        str(row["id"]): str(row["task"] or "")
                        for row in db.execute(
                            f"SELECT id, task FROM jobs WHERE id IN ({placeholders})", tuple(job_ids),
                        )
                    }
                finally:
                    db.close()
            except (OSError, sqlite3.Error):
                job_tasks = {}
        for path in rankings[:limit * 3]:
            job_id = path.name.removesuffix("-yatra-story-ranking.json")
            task = job_tasks.get(job_id)
            if (not include_shorts) and task is not None and not (
                "Sonia Travel Vlogs - Every other day 00:30 IST" in task
                or "completed through YATRA" in task
            ):
                # VISTA Shorts use the same research helper and filename
                # suffix, and their daily slot must not evict a week of
                # long-form history from YATRA's repeat window. But a Short
                # asking what has already been covered has to see the other
                # Shorts - skipping them is what let 17 October repeat 16
                # October's Delhi-Osaka story - so the caller says which it is.
                continue
            row = json.loads(path.read_text(encoding="utf-8"))
            title = str(row.get("pick") or "").strip()
            if title:
                dated.append((path.stat().st_mtime, title))
            if len(dated) >= limit * 2:
                break
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    ledger_path = Path(os.environ.get(
        "ONE_SONIA_UPLOAD_LEDGER",
        r"C:\Users\pc\Documents\LAO\yatra-upload\upload-ledger.json",
    ))
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        rows = ledger.values() if isinstance(ledger, dict) else ledger
        for row in rows:
            title = str((row or {}).get("title") or "").strip()
            if not title:
                continue
            when = 0.0
            try:
                when = datetime.fromisoformat(str((row or {}).get("uploaded_at") or "")).timestamp()
            except ValueError:
                when = 0.0
            dated.append((when, title))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    dated.sort(key=lambda row: row[0], reverse=True)
    if within_days is not None:
        edge = datetime.now(timezone.utc).timestamp() - within_days * 86400
        # An undated entry (a memory note) keeps its place rather than being
        # dropped for having no clock.
        dated = [row for row in dated if row[0] == 0.0 or row[0] >= edge]
    found = [title for _, title in dated]
    found.extend(str(value).strip() for value in prior if str(value).strip())
    unique: list[str] = []
    seen: set[str] = set()
    for title in found:
        key = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(title)
    return unique[:limit]


def _sonia_brief_repeat(brief: str, prior: list[str], *, window: int = 120) -> str:
    """Return the recent title that repeats an evergreen fallback destination.

    News discovery owns its own destination gate.  Search-demand fallback is
    model-written, so it needs an independent deterministic gate before any
    narration or paid voice work begins.  Require the brief's explicit
    Destination/Topic field and compare that destination with the last week of
    durable uploads/commissions.  An absent field is unsafe rather than an
    invitation to guess.
    """
    match = re.search(
        r"(?im)^\s*(?:\*{0,2})destination(?:\s*/\s*topic)?(?:\*{0,2})\s*:\s*(.+?)\s*$",
        brief or "",
    )
    if not match:
        return "missing explicit Destination/Topic field"
    explicit_place = re.split(r"\s*[|–—(]\s*", match.group(1), maxsplit=1)[0]
    destination = re.sub(r"[^a-z0-9]+", " ", explicit_place.casefold()).strip()
    destination = re.sub(r"\b(?:specifically|general|destination|topic)\b.*$", "", destination).strip()
    if not destination:
        return "missing explicit Destination/Topic field"
    # ``prior`` interleaves uploaded titles with reserved/failed commissions
    # and their research headlines. A count of seven rows is not seven channel
    # uploads: the live 11-Oct Thailand Short was row 45 on 20-Oct even though
    # it was only nine uploads old. Scan the bounded 30-day calendar supplied
    # by the caller instead of an arbitrary first-page slice.
    for title in prior[:max(1, window)]:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(title).casefold()).strip()
        if re.search(rf"\b{re.escape(destination)}\b", normalized):
            return str(title)
    return ""


def _sonia_brief_headline_error(brief: str) -> str:
    """Return a deterministic error when HELIOS did not select a story.

    Validate at the evergreen-selection boundary so an incomplete model brief
    is reselected from the same evidence instead of reaching VISTA and failing
    after the handoff. Keep this aligned with the explicit headline evidence
    accepted by ``_vista_spec_from_brief``; never derive a title from a place.
    """
    text = str(brief or "")
    patterns = (
        r"(?im)^\s*(?:\*\*)?Chosen headline:(?:\*\*)?\s*(\S[^\r\n]*)$",
        r"(?im)^\s*Chosen from today's scored travel news:\s*(.+?)\s*\(score",
        r'(?im)^\s*(?:\*\*)?Strongest Truthful Hook:(?:\*\*)?\s*(\S[^\r\n]*)$',
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match and match.group(1).strip(' *"'):
            return ""
    return "missing explicit Chosen headline field"


def _sonia_unique_evergreen_brief(
    brief: str,
    note: str,
    *,
    prompt: str,
    evidence: dict[str, Any],
    recent: list[str],
    max_attempts: int = 3,
    synthesize: Any = None,
) -> tuple[str, str, str, list[dict[str, str]]]:
    """Reselect a unique evergreen candidate from the collected evidence."""
    synthesize = synthesize or _research_synthesis
    attempts: list[dict[str, str]] = []
    current_brief, current_note = brief or "", note or ""
    forbidden: list[str] = []
    total = max(1, int(max_attempts))
    for attempt_number in range(1, total + 1):
        if not current_brief or "COMMISSION: NO" in current_brief.upper():
            return current_brief, current_note, "", attempts
        repeat = _sonia_brief_repeat(current_brief, recent)
        headline_error = _sonia_brief_headline_error(current_brief)
        rejection = repeat or headline_error
        if not rejection:
            return current_brief, current_note, "", attempts
        destination_match = re.search(
            r"(?im)^\s*(?:\*{0,2})destination(?:\s*/\s*topic)?(?:\*{0,2})\s*:\s*(.+?)\s*$",
            current_brief,
        )
        destination = ""
        if destination_match:
            destination = re.split(r"\s*[|–—(]\s*", destination_match.group(1), maxsplit=1)[0].strip()
        if destination and destination.casefold() not in {value.casefold() for value in forbidden}:
            forbidden.append(destination)
        attempts.append({
            "attempt": str(attempt_number),
            "destination": destination,
            "repeated_title": repeat,
            "contract_error": headline_error,
        })
        if attempt_number >= total:
            return current_brief, current_note, rejection, attempts
        rejection_context = (
            "The previous candidate repeated a recent upload "
            + json.dumps(repeat, ensure_ascii=False)
            if repeat else
            "The previous candidate omitted the mandatory explicit Chosen headline field"
        )
        retry_prompt = (
            prompt
            + "\n\nCANDIDATE REJECTION: " + rejection_context
            + ". Select a complete, materially different destination AND topic using ONLY the same supplied evidence. "
            + "Do not return any previously rejected destination in this run. Forbidden destinations: "
            + json.dumps(forbidden, ensure_ascii=False)
            + ". Preserve the mandatory explicit Destination/Topic and Chosen headline fields. "
            + "If the evidence cannot support a unique alternative, end with COMMISSION: NO."
        )
        current_brief, current_note = synthesize(retry_prompt, evidence=evidence)
    return current_brief, current_note, "", attempts


def _vista_same_day_commissions(*, now: datetime | None = None) -> list[dict[str, str]]:
    """Return today's live/finished VISTA stories from the durable job ledger.

    VISTA runs one daily peak slot. Memory is prose, not a reliable
    concurrency/deduplication primitive: the 13:00 brief used to be invisible
    to the 18:00 picker because ``memory.prior_titles`` only reads ``ANGLE:``
    records. The queue already contains the typed headline and destination
    before VISTA starts, so use it as the authority.
    """
    ist = ZoneInfo("Asia/Kolkata")
    local_day = (now or datetime.now(ist)).astimezone(ist).date()
    rows: list[dict[str, str]] = []
    db = _connect()
    try:
        jobs = db.execute(
            "SELECT id, task, created_at FROM jobs "
            "WHERE agent_id = 'vista' AND status IN ('queued', 'running', 'completed') "
            "ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    finally:
        db.close()
    for job in jobs:
        try:
            created = datetime.fromisoformat(str(job["created_at"]))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created.astimezone(ist).date() != local_day:
                continue
            payload = json.loads(str(job["task"] or "{}"))
            if payload.get("brand") != "sonia_travel_vlogs" or payload.get("content_format") != "youtube_short":
                continue
            story = (payload.get("production_spec") or {}).get("story") or {}
            headline = str(story.get("headline") or "").strip()
            destination = str(story.get("destination") or "").strip()
            if headline or destination:
                rows.append({"job_id": str(job["id"]), "headline": headline, "destination": destination})
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return rows


def _vista_repeat_story(story: dict[str, Any], commissions: list[dict[str, str]]) -> dict[str, str] | None:
    """Find an exact same-day headline or destination repeat."""
    normal = lambda value: re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
    headline = normal(story.get("headline"))
    destination = normal(story.get("destination"))
    for prior in commissions:
        if headline and headline == normal(prior.get("headline")):
            return prior
        if destination and destination == normal(prior.get("destination")):
            return prior
    return None


def _sonia_story_pick(reusable: Any, prior: list[str], job_id: str, travel: Any | None = None,
                      *, check_all_prior: bool = False,
                      recent_stories: list[str] | None = None) -> dict[str, Any]:
    """Choose today's Sonia Travel Vlogs story from scored, fresh travel news (any country, Indian viewer).

    Returns {"status": "picked", ...} with the evidence and prompt for the write-up, {"status": "none", "reason": ...}
    when discovery worked but nothing is commissionable today, or {"status": "unavailable"} when the module could not
    run (the caller then falls back to the old single-query research). CODE picks; the model only writes up."""
    travel = travel or _sanjeevani_travel()
    if travel is None:
        return {"status": "unavailable"}
    max_age = float(os.environ.get("ONE_SONIA_MAX_EVENT_AGE_HOURS", "96"))
    min_outlets = int(os.environ.get("ONE_SONIA_MIN_OUTLETS", "2"))
    try:
        found = travel.discover(reusable, top_n=12, max_event_age_hours=max_age, youtube=travel.sanjeevani_youtube())
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"[:200]}
    if not found.get("candidates"):
        return {"status": "unavailable", "error": "travel discovery returned no destination stories"}
    # choose() compares a story against recent_titles[:recent_window], so the
    # window is a count of titles, not a span of time. For a Short the caller
    # has already cut the list to the policy's duplicate window by date, and
    # all of it must be checked: VISTA publishes three a day, so seven titles
    # is two days, and 17 October repeated 16 October because the Short it
    # would have matched sat at position 25.
    recent_window = (len(prior) if check_all_prior
                     else int(os.environ.get("ONE_SONIA_RECENT_DESTINATION_WINDOW", "7")))
    pick, ranking = travel.choose(
        found, list(prior), min_outlets=min_outlets, recent_window=recent_window,
    )
    for candidate in ranking:
        if candidate.get("eligible") and not _sonia_has_travel_intent(candidate):
            candidate["eligible"] = False
            candidate.setdefault("verdict", []).append("outside Sonia niche: no traveller decision or destination utility")
        # The policy's duplicate window, applied to the story rather than to
        # the country: 17 October retold 16 October's Delhi-Osaka story, and
        # the destination gate could not have caught it without blocking Japan
        # for a month.
        if candidate.get("eligible") and recent_stories:
            repeat = _sonia_repeats_recent_story(
                str(candidate.get("headline") or ""), recent_stories)
            if repeat:
                candidate["eligible"] = False
                candidate.setdefault("verdict", []).append(
                    f"already covered: {repeat[:70]}")
    if pick is not None and not _sonia_has_travel_intent(pick):
        pick = next((candidate for candidate in ranking if candidate.get("eligible")
                     and _sonia_has_travel_intent(candidate)), None)
    # Sunday's community poll lets viewers choose the next video. Their winner is taken when it is one of today's
    # commissionable stories (same freshness and outlet gates as any pick); otherwise the score decides as usual.
    viewer_vote = None
    try:
        from openjarvis.one_agents import sonia_community
        community = sonia_community.load()
        vote = community.viewer_vote()
        if vote:
            names = {str(vote.get("place") or "").lower(), str(vote.get("country") or "").lower()} - {""}
            voted = [c for c in ranking if c.get("eligible") and str(c.get("destination") or "").lower() in names]
            if voted:
                pick = max(voted, key=lambda c: c["score"])
                community.mark_vote_used(vote["post_id"], job_id)
                viewer_vote = {"caption": vote.get("caption"), "votes": vote.get("votes"), "total": vote.get("total")}
    except Exception:  # noqa: BLE001 - the vote is a bonus; discovery stands on its own
        viewer_vote = None

    def brief_row(c: dict[str, Any]) -> dict[str, Any]:
        return {"title": c["title"], "destination": c["destination"], "score": c["score"], "outlets": c["n_sources"],
                "latest_age_hours": c.get("latest_age_hours"), "breakdown": c.get("breakdown"),
                "first_report_age_hours": (c.get("first_report") or {}).get("age_hours"),
                "demand": c.get("demand"), "verdict": c.get("verdict")}

    output_dir = _home() / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    ranking_path = output_dir / f"{job_id}-yatra-story-ranking.json"
    ranking_path.write_text(json.dumps({
        "freshness": found.get("freshness"), "sources_ok": len(found.get("sources_ok") or []),
        "sources_failed": found.get("sources_failed"), "pool_fresh_headlines": found.get("pool_fresh"),
        "destination_stories": found.get("clusters"), "max_event_age_hours": max_age, "min_outlets": min_outlets,
        "pick": pick["title"] if pick else None, "viewer_vote": viewer_vote,
        "ranking": [brief_row(c) for c in ranking],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if pick is None:
        top = "; ".join(f"{c['destination']}: {c['title'][:60]} ({'; '.join(c['verdict'])})" for c in ranking[:3])
        return {"status": "none", "ranking_path": str(ranking_path),
                "reason": (f"no travel story today is fresh (first report within {max_age:.0f}h), verified, covered by "
                           f">= {min_outlets} outlets, with a clear destination and not a repeat of the last "
                           f"{recent_window} commissioned videos. "
                           f"Closest: {top}")}
    urls = pick.get("urls") or []
    fastest = (pick.get("demand") or {}).get("fastest") or {}
    # ollama_synthesize hands the model ONLY evidence["eligible"], ["catalog_evidence"], ["counts"] and ["policy"] and
    # silently drops every other key. The first version of this put the story under "chosen_story", so the model saw
    # zero eligible items and answered "INSUFFICIENT DATA ... COMMISSION: NO". Everything it must use therefore goes
    # into eligible rows (each row is serialised whole) and the policy text. The (very long) news URLs stay out.
    evidence = [{"evidence_id": f"story-{i}", "title": h, "url": urls[i] if i < len(urls) else "",
                 "source": "Sanjeevani travel discovery", "role": "scored_news_story", "source_type": "news",
                 "age_hours": pick.get("latest_age_hours"), "freshness_bucket": "within 96h", "freshness_eligible": True,
                 "outlets_covering_the_story": pick["n_sources"], "destination": pick["destination"]}
                for i, h in enumerate(pick["headlines"][:6])]
    receipt = {"evidence_id": "selection", "title": f"Why Sanjeevani chose: {pick['title']}", "role": "scoring_receipt",
               "source_type": "sanjeevani_scoring", "freshness_eligible": True, "destination": pick["destination"],
               "viral_score": pick["score"], "score_breakdown": pick.get("breakdown"), "outlets": pick["sources"][:8],
               "latest_report_age_hours": pick.get("latest_age_hours"),
               "first_report_age_hours": (pick.get("first_report") or {}).get("age_hours"),
               "fastest_fresh_youtube_video": ({"title": fastest.get("title"), "views_per_hour": fastest.get("views_per_hour"),
                                                "age_hours": fastest.get("age_hours")} if fastest else None),
               "other_stories_ranked_lower_do_not_use_as_topics": [
                   {"title": c["title"], "destination": c["destination"], "score": c["score"]}
                   for c in ranking if c["title"] != pick["title"]][:4]}
    evidence.append(receipt)
    synthesis_evidence = {
        "eligible": evidence, "catalog_evidence": [],
        "counts": {"story_headlines": len(evidence) - 1, "outlets": pick["n_sources"]},
        "policy": "One story was chosen by code from today's scored travel news; the model only writes it up. Score = "
                  "outlets covering it + India angle + how much Indians travel there + actionable words (visa, fee, "
                  "flight, route, rule) + hook words + Google Trends match + freshness, plus a bonus for the fastest "
                  "YouTube video of the last 48 h (views per hour). Views are context, not proof. The 'selection' row "
                  "carries the scoring receipt; the 'story-N' rows are the dated headlines.",
    }
    prompt = (
        "You are IRIS, Media floor head. Sanjeevani scored today's latest travel news from every country for Indian "
        f"viewers and CODE chose ONE story: \"{pick['title']}\" (destination: {pick['destination']}). Commission a "
        "Sonia Travel Vlogs video about THIS story only, from ONLY the evidence supplied. Produce a structured "
        "TrendBrief containing: discovery date; target viewer; destination/topic (this single destination, never a "
        "list of countries); why this story was chosen (use the 'selection' evidence row: its score breakdown and the YouTube velocity); viral "
        "search terms; why-now signal; evidence IDs; strongest truthful hook; locations/scenes worth showing; "
        "practical flight/hotel/visa questions; volatile facts requiring same-day official verification; and "
        "explicit exclusions. Never widen the topic to the runner-ups, never invent a trend, a number or a quote, and "
        "never imply Sonia visited. End with COMMISSION: YES or NO. "
        f"Avoid prior topics: {json.dumps(prior[:15], ensure_ascii=False)}")
    return {"status": "picked", "pick": pick, "ranking_path": str(ranking_path), "evidence": evidence,
            "synthesis_evidence": synthesis_evidence, "prompt": prompt}


_NEWS_HOOK_GENERIC = {"road", "marg", "market", "bazaar", "bazar", "chowk", "nagar", "city",
                      "bridge", "flyover", "bypass", "highway", "station", "complex", "area",
                      "near", "the", "and", "block", "sector", "colony", "gali", "lane"}


def _news_hook_ledger_path() -> Path:
    return Path(IA_LOCATIONS_MANIFEST_PATH).with_name("NewsHook_Ledger.json")


def _news_hook_ledger_load() -> list[dict[str, Any]]:
    try:
        data = json.loads(_news_hook_ledger_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _news_hook_place_tokens(place: str) -> list[str]:
    words = re.findall(r"[a-z0-9]{3,}", place.lower())
    return [w for w in words if w not in _NEWS_HOOK_GENERIC]


def _news_hook_already_covered(text: str, ledger: list[dict[str, Any]], *, days: int = 14) -> str:
    """The ledger entry this story repeats, or "". A place covered inside `days`
    is skipped: a real incident trends 2-3 days, so without this the same story
    is picked on consecutive runs. A place needs ALL its distinctive words (max
    two) in the headlines, so a city name alone never blocks a different story."""
    now = datetime.now(timezone.utc)
    low = text.lower()
    for row in ledger:
        try:
            when = datetime.fromisoformat(str(row.get("at")))
        except ValueError:
            continue
        if (now - when).days >= days:
            continue
        tokens = _news_hook_place_tokens(str(row.get("place") or ""))[:2]
        if tokens and all(re.search(rf"\b{re.escape(t)}\b", low) for t in tokens):
            return str(row.get("place"))
    return ""


def _news_hook_ledger_record(place: str, summary: str, job_id: str) -> None:
    """Called when IRIS briefs MUSE: the tracker for a package that has no
    location catalogue to mark used. Never raises -- tracking must not stop a run."""
    try:
        ledger = _news_hook_ledger_load()
        ledger.append({"place": place, "summary": summary[:300], "job_id": job_id,
                       "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        _news_hook_ledger_path().write_text(
            json.dumps(ledger[-200:], indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _iris_news_hook_discovery(avoid: str) -> dict[str, Any]:
    """News-hook research via Sanjeevani's trend_discovery (2026-09-19) instead
    of five fixed keyword queries + a 9B model choosing an incident out of a raw
    evidence dump.

    Sanjeevani finds, clusters, fit-scores and AGE-VERIFIES today's India-wide
    trending stories. CODE then picks the candidate (fresh, verified, not
    sacred, no politics/crime words, covered by >= ONE_NEWS_HOOK_MIN_OUTLETS
    outlets, highest score) -- a first version let the local model pick and it
    chose a police-misconduct story over a 7-outlet highway-crash story, and on
    another run answered "none" for the same input, so choosing is not the
    model's job. The model only WRITES UP the chosen story from its own
    headlines. Returns {"brief","pick","note","summary"}; brief=="" means
    nothing usable today. `avoid` is accepted for signature symmetry."""
    trends = _sanjeevani_trends()
    lib = _sanjeevani_research()
    if trends is None or lib is None:
        return {"brief": "", "pick": None, "summary": {},
                "note": "Sanjeevani trend_discovery unavailable -- cannot run trend discovery"}
    max_age = float(os.environ.get("ONE_NEWS_HOOK_MAX_EVENT_AGE_HOURS", "72"))
    min_outlets = int(os.environ.get("ONE_NEWS_HOOK_MIN_OUTLETS", "3"))
    try:
        found = trends.discover(lib, top_n=15, max_event_age_hours=max_age)
    except Exception as exc:  # noqa: BLE001
        return {"brief": "", "pick": None, "summary": {},
                "note": f"Trend discovery failed: {type(exc).__name__}: {exc}"[:300]}
    sacred = re.compile(r"\b(temple|mandir|mosque|masjid|gurdwara|church|dargah|shrine|ghat|"
                        r"immersion|visarjan|puja|navratri|kanwar|yatra|pilgrim|idol|ganesh)\b", re.I)
    summary = {
        "pool_fresh_headlines": found["pool_fresh"], "clusters": found["clusters"],
        "sources_ok": len(found["sources_ok"]), "sources_failed": found["sources_failed"],
        "x_trends_sample": found["x_trends_sample"][:8],
        "max_event_age_hours": max_age, "min_outlets": min_outlets,
        "candidates": [
            {"title": c["title"], "sources": c["n_sources"], "score": c["score"],
             "first_report_age_hours": (c.get("first_report") or {}).get("age_hours"),
             "verified": c["verified"], "stale": c["stale"]}
            for c in found["candidates"]],
    }
    eligible = [c for c in found["candidates"]
                if c["verified"] and not c["stale"]
                and c["n_sources"] >= min_outlets
                and c["positive_hits"] >= 1 and c["negative_hits"] == 0
                and not sacred.search(" ".join(c["headlines"]))]
    ledger = _news_hook_ledger_load()
    repeats = []
    for c in list(eligible):
        hit = _news_hook_already_covered(" ".join(c["headlines"]), ledger)
        if hit:
            eligible.remove(c)
            repeats.append({"title": c["title"], "already_covered": hit})
    summary["skipped_already_covered"] = repeats
    if not eligible:
        return {"brief": "", "pick": None, "summary": summary,
                "note": f"No trending story today is fresh (<= {max_age:.0f}h since first "
                        f"report), verified, covered by >= {min_outlets} outlets, and a "
                        "visible place-based civic story (stale, thin, sacred-site or "
                        "non-visual stories were skipped)."}
    pick = eligible[0]
    age = (pick.get("first_report") or {}).get("age_hours")
    summary["picked"] = {"title": pick["title"], "first_report": pick.get("first_report"),
                         "outlets": pick["n_sources"]}
    prompt = (
        "You are IRIS, head of Media & Content at ImagineIndia.\n\n"
        f"Today's story (code-verified: first reported ~{age}h ago, covered by "
        f"{pick['n_sources']} outlets):\n"
        + "\n".join(f"- {h}" for h in pick["headlines"][:5]) +
        "\n\nWrite the reel brief from these headlines ONLY: no invented numbers, "
        "causes, people or places. PLACE = ONE place named in the headlines, with its "
        "city (if only a road/bypass/bridge is named, use that with the city). "
        "ANGLE = the systemic/infrastructure question this story raises, phrased as a "
        "question if the headlines do not state a cause -- never invent a cause. "
        "Deaths/injuries may be in the story; the reel never centres victims.\n\n"
        "Reply with ONLY these lines, nothing else:\n"
        "PLACE: <one place, with city>\n"
        "INCIDENT_SUMMARY: <what happened, headline facts only>\n"
        "SEARCH_TERMS: <comma-separated real search phrases from the headlines>\n"
        "PRIORITY: <one line -- what this reel should optimise for>\n"
        "REGION: rotation\n"
        "ANGLE: <one line -- the systemic question>\n"
        "VIRAL_SCORE: <0-100>\n"
        "SACRED_SITE: none\n"
        "BRIEF: <4-8 lines: audience, why now, honest risk>"
    )
    text, err = _research_synthesis(prompt, evidence={"eligible": [], "catalog_evidence": []})
    if not text:
        return {"brief": "", "pick": None, "summary": summary, "note": err or "model returned nothing"}
    return {"brief": text, "pick": pick, "summary": summary, "note": ""}


def _compact_media_evidence(evidence: dict[str, Any], *, max_per_category: int = 5) -> dict[str, Any]:
    """Strips each eligible item to the fields a synthesis prompt actually
    needs before it goes into the model's context.

    Added 2026-09-12 after a live failure: the first category-query version
    of _run_iris injected the FULL merged evidence dict (raw_signal,
    captured_at, evidence_score, score_reasons and all) for up to ~100 items
    across four categories, on top of the full three-file skill text. The
    local model's response abandoned the required output shape entirely
    (PRIORITY/ANGLE came back empty) and invented an unrelated, ungrounded
    "digital heritage" narrative with fabricated individuals -- exactly the
    failure this skill's evidence discipline exists to prevent. Shrinking
    what actually reaches the model's context is the direct fix; the
    shape-check below is the safety net for whenever it still slips.

    Changed 2026-09-19 from a flat [:max_items] slice on the merged list to
    a per-category cap: confirmed live that viral_format's ~11 items (the
    same recurring AI-trend meme, which is why it is the one category that
    reliably clears commissioning_eligible's item-count bar) filled almost
    the entire old 20-item budget on their own, crowding out
    disaster_incident's real, specific, dated incidents (a Belagavi fire, a
    Thaiyur gas-leak fire) entirely or near-entirely depending on category
    order -- IRIS's own synthesis kept defaulting to the generic viral_
    format theme not because it was the best PLACE candidate, but because
    it was numerically the only thing reliably in context. A specific
    single-event story does not need many items to be real; it needs ONE
    good one. Capping per category instead of on the flat merge guarantees
    every category gets a fair, bounded slice regardless of its raw volume
    or position in _MEDIA_TREND_CATEGORIES."""
    by_category: dict[str, list[dict[str, Any]]] = {}
    for item in (evidence.get("eligible") or []):
        by_category.setdefault(str(item.get("category") or ""), []).append(item)
    trimmed = []
    for items in by_category.values():
        for item in items[:max_per_category]:
            trimmed.append({
                "evidence_id": item.get("evidence_id"),
                "category": item.get("category"),
                "title": item.get("title"),
                "source_url": item.get("source_url"),
                "published_at": item.get("published_at"),
                "freshness_bucket": item.get("freshness_bucket"),
            })
    return {
        "eligible": trimmed,
        "categories": evidence.get("categories", {}),
        "errors": evidence.get("errors", []),
    }


def _media_trend_evidence(reusable: Any) -> dict[str, Any]:
    """Runs each imagineindia-trend-radar category query separately and
    merges them, tagging every item with which category found it. Replaces
    a single blended collect() call, which returned almost nothing eligible
    in the live 2026-09-12 comparison that led to this skill."""
    merged: dict[str, Any] = {"eligible": [], "catalog_evidence": [], "categories": {}, "errors": []}
    for category, query in _MEDIA_TREND_CATEGORIES:
        try:
            snapshot = reusable.collect(query, markets=["IN"])
            items = list(snapshot.get("eligible") or [])
            for item in items:
                item["category"] = category
            merged["eligible"].extend(items)
            merged["categories"][category] = {
                "query": query,
                "eligible_count": len(items),
                "commissioning_eligible": bool(
                    (snapshot.get("corroboration") or {}).get("commissioning_eligible")
                ),
            }
        except Exception as exc:  # one category failing must not sink the others
            merged["errors"].append({"category": category, "query": query,
                                     "error": f"{type(exc).__name__}: {exc}"[:400]})
            merged["categories"][category] = {"query": query, "eligible_count": 0,
                                              "commissioning_eligible": False,
                                              "error": f"{type(exc).__name__}: {exc}"[:400]}
    return merged


def _publishing_event(job: dict[str, Any], *, agent: str, event_type: str,
                      stage: str, summary: str, details: dict[str, Any] | None = None,
                      status: str = "running") -> None:
    """Best-effort live projection. Execution never depends on dashboard storage."""
    payload = _json_task(job)
    mission_id = str(payload.get("mission_id") or payload.get("origin_job") or job.get("id") or "")
    if not mission_id:
        return
    try:
        ledger = floors_bridge.load("floor_05_publishing", "publishing_mission_ledger")
        if ledger is not None:
            ledger.record(_home() / "publishing_missions.db", mission_id=mission_id,
                          objective=str(payload.get("objective") or payload.get("request") or job.get("task") or "")[:1000],
                          job_id=str(job.get("id") or ""), agent_id=agent.lower(),
                          event_type=event_type, stage=stage, summary=summary,
                          details=details or {}, status=status)
    except Exception:
        pass


def _fresh_research_quorum(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic commissioning decision before any model runs."""
    eligible = list(snapshot.get("items") or [])
    sources = {str(row.get("source_type") or "") for row in eligible
               if row.get("source_type")}
    demand_items = [row for row in eligible if row.get("role") == "demand_discovery"]
    catalog_items = list(snapshot.get("catalog_evidence") or [])
    contract = snapshot.get("corroboration") or {}
    minimum_items = int(contract.get("minimum_items") or 3)
    minimum_sources = int(contract.get("minimum_source_types") or 2)
    floor_owned = snapshot.get("contract") == "one.floor05.book-demand/v1"
    passed = bool(snapshot.get("commissioning_eligible")) if floor_owned else (
        len(eligible) >= minimum_items and len(sources) >= minimum_sources
        and bool(demand_items) and bool(catalog_items)
    )
    return {
        "passed": passed,
        "eligible_items": len(eligible), "eligible_sources": len(sources),
        "demand_items": len(demand_items), "catalog_items": len(catalog_items),
        "minimum_items": minimum_items, "minimum_sources": minimum_sources,
        "candidate_count": len(snapshot.get("candidates") or []),
        "winner_score": (snapshot.get("winner") or {}).get("score"),
        "floor_owned": floor_owned,
    }


def _reconcile_publishing_projection() -> None:
    """Close ledger missions whose queue job is already terminal.

    The queue is execution truth; the publishing ledger is a UI/audit
    projection.  A worker crash between those two writes must not leave the
    building claiming that HERMES is researching forever.
    """
    try:
        ledger = floors_bridge.load("floor_05_publishing", "publishing_mission_ledger")
        if ledger is None:
            return
        ledger_path = _home() / "publishing_missions.db"
        with _connect() as db:
            for mission in ledger.missions(ledger_path, limit=200):
                if mission.get("status") != "running":
                    continue
                row = db.execute(
                    "SELECT status,error FROM jobs WHERE id=?", (mission["mission_id"],)
                ).fetchone()
                if row is None or row["status"] in {"queued", "running"}:
                    continue
                queue_status = str(row["status"])
                terminal = "completed" if queue_status == "completed" else "blocked"
                last_type = (mission.get("events") or [{}])[-1].get("event_type", "")
                # A completed queue row without a completed ledger event means
                # the handler returned an old/fallback result, not governed
                # research. Fail closed rather than laundering it as success.
                if terminal == "completed" and last_type not in {
                    "research_only_completed", "commissioned", "research_completed"
                }:
                    terminal = "blocked"
                ledger.record(
                    ledger_path, mission_id=mission["mission_id"],
                    objective=mission.get("objective", ""), job_id=mission["mission_id"],
                    agent_id=str(mission.get("current_agent") or "hermes"),
                    event_type="state_reconciled", stage="queue_terminal",
                    summary=f"Mission reconciled with terminal queue state: {queue_status}",
                    details={"queue_status": queue_status, "last_event": last_type,
                             "error": str(row["error"] or "")[:1000]},
                    status=terminal,
                )
    except Exception as exc:
        print(f"[one-agents] publishing reconciliation skipped: {exc}", flush=True)


# The drafting pipeline has no research capability. SCRIBE writes from an
# outline; nothing in the chain can look a fact up, read a document, interview
# anyone or check a name. That is fine for advice, framework and how-to
# nonfiction, where the value is a method rather than a claim about the world.
# It is not fine for reportage -- a book telling the reader what is happening
# inside a real, named institution -- because every specific in it is invented.
#
# This is not theoretical. "Code of the Past" reached OLYMPUS as AI-written
# reportage about the National Archives of India and a named government
# digitisation mission, complete with a fabricated surprise audit, hacking
# attempts and a funding freeze. It was refused. The cheapest place to stop the
# next one is here, before a 65,000-word draft exists.
_REPORTAGE_ENTITY = re.compile(
    r"\b(ministr(y|ies)|department|government|parliament|archives?|bureau|"
    r"agenc(y|ies)|commission|authority|corporation|council|federation|"
    r"institute|university|administration|programme|program|mission|"
    r"initiative|scheme|task force)\b",
    re.IGNORECASE,
)
_REPORTAGE_FRAMING = re.compile(
    r"\b(inside|investigation|investigative|expos[eé]|untold|true story|"
    r"real story|what really happened|behind the scenes|leaked|whistleblower|"
    r"scandal|the rise (and fall )?of|how .{0,40} is "
    r"(saving|rebuilding|transforming|fixing|rescuing))\b",
    re.IGNORECASE,
)


def _sourcing_gate(brief: str, kdp_mode: str) -> tuple[bool, str]:
    """Would writing this book honestly need facts the pipeline cannot get?

    Returns (blocked, reason). Fiction is never blocked -- invented specifics
    are the point there. Nonfiction goes to a focused model audit, with the
    keyword heuristic as the fallback when no provider answers, so a provider
    outage cannot quietly switch the guard off.
    """
    if kdp_mode == "fiction":
        return False, ""

    candidate = "\n".join(part for part in (
        _marker(brief, "ANGLE"), _marker(brief, "BRIEF") or brief[:2000],
    ) if part)

    # Only reportage-shaped nonfiction needs this audit. Sending every advice
    # book to a probabilistic classifier produced false HIGH verdicts for
    # ordinary subjects such as algorithms and underwriting platforms. The
    # deterministic pair deliberately requires both an institutional subject
    # and investigative/current-affairs framing.
    entity = _REPORTAGE_ENTITY.search(candidate)
    framing = _REPORTAGE_FRAMING.search(candidate)
    if not (entity and framing):
        return False, ""

    verdict, _note = _research_synthesis(
        "You are a sourcing auditor for a book pipeline that CANNOT research: it "
        "has no way to look a fact up, read a document, interview anyone, or "
        "check a name. Judge exactly one thing about the candidate below.\n\n"
        "Answer HIGH if writing this book honestly would require specific factual "
        "claims about real named organisations, government programmes, current "
        "events, or living (or recently living) people — claims a reader could "
        "check and find invented.\n"
        "Answer LOW if the book delivers a method, framework, skill or invented "
        "story, and its value does not rest on such claims. Ordinary advice "
        "nonfiction is LOW even when it mentions real professions, places or "
        "well-known ideas.\n\n"
        "Reply with exactly two lines:\n"
        "SOURCING_RISK: HIGH | LOW\n"
        "WHY: <one line>\n\n"
        f"Candidate:\n{candidate}",
        max_tokens=200,
    )
    level = _marker(verdict, "SOURCING_RISK").upper() if verdict else ""
    if level.startswith("HIGH"):
        why = _marker(verdict, "WHY") or "requires factual claims the pipeline cannot verify"
        return True, f"sourcing auditor: {why}"
    if level.startswith("LOW"):
        return False, ""

    # No usable verdict. Judge the shape of the text rather than waving the
    # candidate through: a named institution plus reportage framing is the
    # exact combination that produced the refused title.
    return True, (
        "sourcing auditor unavailable and the candidate reads as reportage "
        f"about a real institution (matched '{entity.group(0)}' with "
        f"'{framing.group(0).strip()}')"
    )


_KDP_TOPIC_FAMILIES = {
    "automation": re.compile(r"\b(ai|automation|automated|algorithm|machine[ -]?learning)\b", re.I),
    "access_paywall": re.compile(r"\b(paywall|subscription|inaccessible|access|afford|locked|exclusive)\w*\b", re.I),
    "career_displacement": re.compile(r"\b(job|career|profession|worker|workplace|task|role|obsolesc|displac|redundan)\w*\b", re.I),
    "retirement": re.compile(r"\b(retire|pension|epfo|nps|senior citizen)\w*\b", re.I),
    "tax": re.compile(r"\b(tax|income tax|deduction|shelter|compliance)\w*\b", re.I),
    "health_sleep": re.compile(r"\b(sleep|glymphatic|neurolog|circadian|night shift)\w*\b", re.I),
    "relationship": re.compile(r"\b(relationship|intimacy|partner|marriage|dating)\w*\b", re.I),
}


def _kdp_topic_history() -> list[dict[str, str]]:
    """Return durable topic records even when Obsidian memory is unavailable."""
    root = Path.home() / "Documents" / "LAO" / "kdp-book-factory" / "output"
    history: list[dict[str, str]] = []
    for path in sorted(root.glob("*/topic_log.txt"), reverse=True):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        if text:
            history.append({"topic": text, "source": str(path)})
    for title in memory.prior_titles("5", "Book Publishing (KDP)", limit=50):
        history.append({"topic": title, "source": "ONE Vault / Floor 05"})
    return history


def _topic_terms(text: str) -> set[str]:
    stop = {
        "about", "after", "again", "against", "being", "book", "build", "from",
        "have", "into", "more", "their", "them", "these", "this", "through",
        "what", "when", "where", "which", "while", "with", "without", "your",
    }
    return {
        token for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 4 and token not in stop
    }


def _find_kdp_topic_duplicate(candidate: str,
                              history: list[dict[str, str]] | None = None) -> dict[str, Any] | None:
    """Fail closed on the same title, language, or three-part subject concept.

    ``history`` is the floor's prior topics. Pass a snapshot taken BEFORE this
    run wrote anything: HERMES records its commissioning note in the vault, and
    the vault is one of the sources this reads, so a check made afterwards
    compares the candidate against itself. On 2026-09-24 that is exactly what
    happened -- lexical_similarity 1.0 against a "previous" title that was the
    candidate, written minutes earlier by the same run.
    """
    candidate = candidate.strip()
    if not candidate:
        return {"reason": "empty candidate topic", "candidate": candidate}
    candidate_terms = _topic_terms(candidate)
    candidate_families = {
        name for name, pattern in _KDP_TOPIC_FAMILIES.items() if pattern.search(candidate)
    }
    for record in (_kdp_topic_history() if history is None else history):
        previous = record["topic"]
        previous_terms = _topic_terms(previous)
        union = candidate_terms | previous_terms
        lexical = len(candidate_terms & previous_terms) / len(union) if union else 0.0
        previous_families = {
            name for name, pattern in _KDP_TOPIC_FAMILIES.items() if pattern.search(previous)
        }
        shared_families = sorted(candidate_families & previous_families)
        # Three shared subject dimensions catches paraphrases such as
        # "tasks automated by unaffordable tools" vs "invisible automation &
        # paywall tech" even when the proposed title itself is different.
        if lexical >= 0.34 or len(shared_families) >= 3:
            return {
                "reason": "topic overlaps prior KDP commission",
                "candidate": candidate,
                "previous": previous,
                "source": record["source"],
                "lexical_similarity": round(lexical, 3),
                "shared_concepts": shared_families,
            }
    return None


KDP_PAYMENTS_SYNC_MARKER = "kdp payments sync"
# Must match the rows already on the books; it is part of the upsert key.
KDP_STORE = "amazon-kdp"


def _revenue_service(module_name: str) -> Any | None:
    """Import one of the company's shared revenue modules by path.

    floors_bridge.load() cannot reach these: it resolves
    <floor>/lib/<module>.py, and the revenue service lives at
    _services/revenue/<module>.py with no lib package. Asking it anyway
    returned None and the sync reported "the revenue service is unavailable"
    while silently banking nothing - found 2026-09-24 when a listings refresh
    said it had synced zero titles and had no error to show for it.

    The directory goes on sys.path because these modules import each other by
    bare name (kdp_payments does `import money`).
    """
    directory = floors_bridge.floors_root() / "_services" / "revenue"
    target = directory / f"{module_name}.py"
    if not target.is_file():
        return None
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    try:
        import importlib

        return importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 - a missing service must not stop the job
        print(f"[one-agents] revenue service {module_name} unavailable: {exc}", flush=True)
        return None


def _publishing_lib(module_name: str) -> Any | None:
    """One of Floor 5's own modules, or None if it cannot be loaded.

    None rather than an exception: these enrich the nightly sync, and a
    missing one must not stop the money half from being banked.
    """
    return floors_bridge.load("floor_05_publishing", module_name)


def _kdp_listings_sync() -> dict[str, Any]:
    """Refresh what the board counts as purchasable from the real shelf.

    The listings table said 10 while the shelf carried three titles it had
    never heard of, including the one published that morning - listings were
    written once and never reconciled. Upsert only: KDP paginates, so a title
    this read does not see has not necessarily gone, and marking it dead on
    that basis would be worse than a stale count.
    """
    from openjarvis.tools import kdp_reports_reader as reports

    money = _revenue_service("money")
    if money is None:
        return {"synced": 0, "reason": "the revenue service is unavailable"}
    try:
        shelf = reports.read_bookshelf(headless=True)
    except Exception as exc:  # noqa: BLE001 - the money half already succeeded
        return {"synced": 0, "error": f"{type(exc).__name__}: {exc}"[:200]}

    # Exclusivity is read on the same pass because it is read from the same
    # page, and because it is what decides whether a title can earn anywhere
    # but Kindle. On 2026-09-26 eight of ten said "KDP Select: eBook enrolled".
    eligibility = _publishing_lib("distribution_eligibility")

    synced = []
    for title in shelf:
        if not title.get("asin") or not title.get("title"):
            continue
        free_on = ""
        if eligibility is not None:
            free_on = eligibility.verdict(title).get("wide_eligible_on") or ""
        money.record_listing(
            # The store label is half the upsert key. Writing "Amazon KDP"
            # where the table already said "amazon-kdp" did not update ten
            # listings, it created ten more.
            "5", KDP_STORE, title["asin"], title["title"],
            status=title.get("status") or "live",
            url=f"https://www.amazon.com/dp/{title['asin']}",
            price=title.get("price_usd"), currency="USD",
            exclusive=title.get("kdp_select"),
            exclusive_until=free_on,
            published_on=title.get("submitted_on") or "",
        )
        synced.append(title["asin"])

    position = (eligibility.assess(shelf) if eligibility is not None
                else {"summary": "the eligibility engine is unavailable"})
    return {"synced": len(synced), "asins": synced,
            "distribution": {k: position.get(k) for k in
                             ("summary", "wide_eligible_count", "exclusive_count",
                              "unknown_count", "next_title_free_on")},
            "owner_actions": position.get("owner_actions", [])[:12]}


def _kdp_payments_sync(job: dict[str, Any]) -> dict[str, Any]:
    """Read KDP's payments report and put the settled money on the books.

    METRON's work, not the head's. Floor 5 already seats a measurement and
    attribution worker, and reading what a storefront actually paid is exactly
    that job; HERMES commissions titles and reports upward. It ran under
    HERMES for one night because the marker was hung on the head's handler as
    the quickest place to attach a trigger, and the building showed it: the
    floor head sitting at his desk announcing Amazon's payment totals.

    Runs nightly because the only thing that changes between runs is the
    calendar: KDP marks a payment "Paid" the day it is scheduled, so the same
    rows sit there for days before the money exists. Settlement is decided by
    the payment date, which is why the 29th needs no special case - the run
    that morning simply finds two more rows on the settled side.

    Idempotent on KDP's own payment numbers, so every other night is a no-op.

    The two halves are independent on purpose
    -----------------------------------------
    The money and the shelf live on different Amazon hosts, and only one of
    them keeps asking to be signed in again. Measured on 2026-09-29, same
    browser and same profile within one minute: kdp.amazon.com/bookshelf
    loaded signed in, and kdpreports.amazon.com/payments bounced to the
    sign-in form. Reading the payments report first and letting it raise took
    the shelf refresh down with it, so a night that could still have updated
    the catalogue and its exclusivity updated nothing at all.
    """
    from openjarvis.tools import kdp_reports_reader as reports

    # Paired with head_briefs_worker in _hermes_hands_payments_to_metron.
    # Confirming receipt first is what makes the two of them stand together
    # in the building instead of the head leaving before the worker reacts.
    stages.worker_confirms_receipt("metron", "Got it - opening the payments report")
    stages.set_stage("metron", stages.EXECUTING, "Reading KDP's payments report")
    try:
        payments_service = _revenue_service("kdp_payments")
        try:
            split = reports.read_payments(headless=True)
        except Exception as exc:  # noqa: BLE001 - the shelf half may still work
            return _payments_unreadable(job, exc)

        if payments_service is None:
            return {"agent": "METRON", "mode": "revenue_sync", "recorded": False,
                    "reason": "the revenue service is unavailable; nothing was banked",
                    **{k: split[k] for k in ("as_of", "settled_total", "scheduled_total", "currency")}}

        recorded = payments_service.record_settled(split)
        recorded["listings"] = _kdp_listings_sync()
        _publishing_event(
            job, agent="METRON", event_type="kdp_payments_synced", stage="revenue",
            summary=(f"{recorded['currency']} {recorded['imported_total']} newly banked; "
                     f"{recorded['currency']} {recorded['pending_total']} still promised"),
            details={"imported": recorded["imported"], "pending": recorded["pending"],
                     "as_of": recorded["as_of"]},
        )
        return {"agent": "METRON", "mode": "revenue_sync", "recorded": True, **recorded,
                "content": (f"Banked {recorded['currency']} {recorded['imported_total']} from KDP; "
                            f"{recorded['currency']} {recorded['pending_total']} is promised but "
                            f"not yet paid.")}
    finally:
        # Clears on a failed read too. A worker left mid-stage keeps its
        # speech bubble up for days, which is how the stale SCRIBE bubble
        # happened; a nightly job must never be able to leave one behind.
        stages.clear_stage("metron")


def _payments_unreadable(job: dict[str, Any], error: Exception) -> dict[str, Any]:
    """Report a payments read that failed, and do the half that still works.

    The shelf refresh is the probe as well as the work. If it succeeds, the
    profile is signed in and only kdpreports.amazon.com is asking again, which
    is a materially different thing to tell the owner than "the KDP profile
    needs its one-time login" - that sentence sent them to re-authenticate a
    profile that was never logged out, and it hid that the shelf could have
    been refreshed all along.
    """
    listings = _kdp_listings_sync()
    profile_alive = bool(listings.get("synced"))
    reason = (
        "Amazon refused the payments report while the same profile read the "
        "shelf fine in the same minute, so nothing is logged out. That host "
        "only mints a session for a real browser window - check this read is "
        "running headed and parked off-screen rather than headless, which is "
        "what caused every previous occurrence. ONE never types a password; "
        "if a window genuinely cannot be opened, run kdp-login.ps1."
        if profile_alive else
        "The KDP profile could not read the payments report or the shelf, so "
        "the session itself has lapsed. Run kdp-login.ps1 and sign in there."
    )
    _publishing_event(
        job, agent="METRON", event_type="kdp_payments_unreadable", stage="revenue",
        summary=("The payments report needs a fresh sign-in; the shelf was refreshed"
                 if profile_alive else "KDP could not be read at all"),
        details={"listings": listings, "error": f"{type(error).__name__}: {error}"[:300]},
        status="waiting" if profile_alive else "failed",
    )
    return {"agent": "METRON", "mode": "revenue_sync", "recorded": False,
            "profile_signed_in": profile_alive, "reason": reason,
            "listings": listings,
            "error": f"{type(error).__name__}: {error}"[:300],
            "content": reason}


def _hermes_hands_payments_to_metron(job: dict[str, Any]) -> dict[str, Any]:
    """Walk the nightly payments brief over to the worker whose job it is.

    The trigger enters through the head because the scheduler refuses any
    other target - dispatch() rejects a worker or anything with a
    reports_to, so pointing the nightly trigger straight at METRON failed
    with "Scheduled trigger refused non-head target: metron" and banked
    nothing. That rule is right: a scheduled routine arrives at the floor's
    head, who briefs a worker. The head is the door, not the desk.

    So HERMES keeps the trigger and hands the work over properly, through
    the floor's one handoff choreography, the same way he briefs SCRIBE.
    """
    return stages.head_briefs_worker(
        "hermes", "metron",
        carrying_detail="Taking the KDP payments brief to METRON",
        briefing_detail="Read tonight's payments report and bank what has arrived",
        receiving_detail="Taking the payments brief",
        awaiting_detail="Waiting on METRON's payment reconciliation",
        enqueue=lambda: enqueue_job("metron", str(job.get("task") or ""),
                                    mode="execute", tier="fast"),
    ) | {"agent": "HERMES", "mode": "delegated",
         "content": "Handed tonight's KDP payments read to METRON."}


def _run_hermes(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 5 head - commissions a title, then hands it to SCRIBE.

    The floor works the way a real desk would: HERMES researches what to
    commission, walks the brief over to the worker, and waits. SCRIBE drives
    LAO's KDP factory to completion and walks the finished book back. HERMES
    then reports upward. Each of those is a real step with a real artifact —
    the stages exist so the building can show the handoff, not to invent it.

    ``mode='report'`` is the third leg of that chain, enqueued by SCRIBE once
    the book exists; it is not something a person dispatches by hand.
    """
    task = str(job.get("task") or "")
    mode = str(job.get("mode") or "plan").strip().lower()

    try:
        portfolio_payload = json.loads(task)
    except (json.JSONDecodeError, TypeError):
        portfolio_payload = {}
    if portfolio_payload.get("workflow") == "publishing_portfolio" and portfolio_payload.get("phase") == "commission":
        return _hermes_commission(job, portfolio_payload)

    if mode == "report":
        return _hermes_report(job)

    # The money clock, not the book clock, and checked before anything else:
    # reading the payments report is METRON's work, and the nightly trigger
    # dispatches straight there. This branch only catches a payments job that
    # still reaches the head - an old trigger, or a hand dispatch - and walks
    # it to the right desk.
    #
    # It has to come before the research event and the stage below. While it
    # sat after them, a sync left HERMES showing "researching" and put the
    # banking summary in the head's own speech bubble, which is what the
    # building was reporting on 2026-09-24: the head appeared to be reading
    # Amazon's payments table instead of commissioning a title.
    if KDP_PAYMENTS_SYNC_MARKER in str(job.get("task") or "").lower():
        return _hermes_hands_payments_to_metron(job)

    mission_id = str(portfolio_payload.get("mission_id") or job["id"])
    _publishing_event(job, agent="HERMES", event_type="research_started",
                      stage="24h_demand_radar", summary="Fresh market-signal research started")

    # The detail is what the building shows in the speech bubble beside HERMES'
    # face, so it carries the Chairman's actual words — not a generic label.
    stages.set_stage("hermes", stages.RESEARCHING,
                     task.strip()[:180] or "Choosing the next KDP title")

    # Read its own history first. Without this the floor happily re-commissions
    # a title it already published — the vault is what makes it memory.
    already = memory.prior_titles("5", "Book Publishing (KDP)")
    # Frozen here, before this run writes its own brief and vault note, so the
    # uniqueness gate can never reject a candidate for matching itself.
    topic_history = _kdp_topic_history()
    avoid = (
        "\n\nAlready commissioned by this floor — do not repeat or closely "
        "overlap these:\n" + "\n".join(f"- {t}" for t in already[:15])
        if already else ""
    )

    # Capture an immutable, machine-readable 24-hour discovery snapshot before
    # asking a model to interpret it. This prevents "web research" from being
    # only a persuasive paragraph with no reproducible input.
    radar_snapshot: dict[str, Any] = {"items": [], "errors": [{"error": "radar unavailable"}]}
    radar = None
    try:
        # Global-first by explicit instruction 2026-09-13 ("apne search ko
        # global rakhna as hume maximum profit bahar se hi ho payega") --
        # KDP's real volume is the US/UK market, not India; the first entry
        # picks the Google News edition discussion_persistence() etc. search.
        requested_region = str(portfolio_payload.get("region") or "").upper()
        markets = [requested_region] if requested_region in {"IN", "US", "GB", "CA", "AU"} else ["US", "GB", "CA", "AU", "IN"]
        reusable = _sanjeevani_research()
        if reusable is not None:
            engine = floors_bridge.load("floor_05_publishing", "book_demand_engine")
            radar = floors_bridge.load("floor_05_publishing", "publishing_demand_radar")
            if engine is None:
                raise RuntimeError("Floor 05 book-demand engine is unavailable")
            supply_collector = radar.book_supply if radar is not None else None
            # A trigger-fired job's task carries a "[ONE trigger: ...]"
            # schedule label the Chairman needs to see (kept in `task` for
            # the stage detail above), but engine.collect() uses this same
            # string as a literal search query. Stripped here so a query
            # never gets built from "ONE trigger KDP Book Factory Weekly
            # Monday IST" -- confirmed live 2026-09-13 via query_plan() that
            # the unstripped prefix dominates the extracted query terms and
            # returns nothing a real headline would ever match.
            research_query = re.sub(r"^\[ONE trigger: [^\]]+\]\s*", "", task).strip() or task
            # The old generic category sweep repeatedly crowned wellness and
            # personal-finance topics. Keep the collectors and scoring intact,
            # but seed them with the catalogue's actual commercial territory.
            # This is a research query, not a manuscript instruction.
            if re.search(r"next governed KDP|book factory|authority-catalogue", research_query, re.I):
                research_query = (
                    "Windows PowerShell networking enterprise automation "
                    "agentic AI operations governance practical guide"
                )
            def _survivable(call: Any, empty: dict[str, Any]) -> Any:
                # All five evidence calls for one topic sit in a single try block
                # inside the floor's collect(), so one slow site deletes the whole
                # candidate. Confirmed live 2026-09-19: openlibrary.org timed out
                # at 12s on all six topics, every candidate vanished, the catalog
                # evidence went empty, and the freshness gate blocked the book -
                # while Google and Apple had already answered the same question.
                # Missing evidence is handed over as missing instead; the floor's
                # own scorer still refuses to call a candidate eligible when its
                # competition is genuinely unknown, so the gate is untouched.
                def guarded(*args: Any, **kwargs: Any) -> dict[str, Any]:
                    try:
                        return call(*args, **kwargs)
                    except Exception as exc:  # noqa: BLE001
                        return {**empty, "source_type": "unavailable",
                                "unavailable_reason": f"{type(exc).__name__}: {exc}"[:200]}
                return guarded

            radar_snapshot = engine.collect(
                research_query, reusable, markets=markets,
                supply_collector=_survivable(supply_collector,
                                             {"raw_signal": {"total_items": None}, "role": "competition"}),
                open_supply_collector=_survivable(engine.open_library_supply,
                                                 {"total_items": None, "role": "competition"}),
                intent_collector=_survivable(engine.google_book_intent,
                                             {"book_intent_suggestions": [], "suggestions": [],
                                              "role": "reader_intent"}),
                persistence_collector=_survivable(engine.discussion_persistence,
                                                  {"result_count": 0, "items": [],
                                                   "role": "discussion_persistence"}),
            )
            radar_text = json.dumps(radar_snapshot, ensure_ascii=False, separators=(",", ":"))
        else:
            radar = floors_bridge.load("floor_05_publishing", "publishing_demand_radar")
        if reusable is None and radar is not None:
            radar_snapshot = radar.collect(markets)
            radar_text = radar.compact(radar_snapshot)
        elif reusable is None and radar is None:
            radar_text = "{}"
    except Exception as exc:
        radar_text = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
    radar_dir = _home() / "agent_outputs" / "research"
    radar_dir.mkdir(parents=True, exist_ok=True)
    radar_path = radar_dir / f"{mission_id}-trending-now.json"
    radar_path.write_text(json.dumps(radar_snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    freshness_counts = radar_snapshot.get("freshness_counts") or {}
    _publishing_event(
        job, agent="HERMES", event_type="freshness_gate_completed",
        stage="24_48h_date_gate",
        summary=(
            f"Freshness gate: {len(radar_snapshot.get('items') or [])} eligible; "
            f"{len(radar_snapshot.get('excluded_items') or [])} excluded"
        ),
        details={"buckets": freshness_counts, "snapshot": str(radar_path),
                 "candidate_count": len(radar_snapshot.get("candidates") or []),
                 "winner": (radar_snapshot.get("winner") or {}).get("topic"),
                 "winner_score": (radar_snapshot.get("winner") or {}).get("score")},
    )
    if not _job_is_active(str(job["id"])):
        stages.clear_stage("hermes")
        return {
            "agent": "HERMES", "mode": "cancelled", "handed_to": None,
            "content": "Research finished after queue ownership expired; result discarded.",
            "radar_snapshot": str(radar_path),
        }

    # Freshness is a commissioning gate, not an informational event. Models
    # may interpret evidence only after deterministic acquisition meets this
    # quorum; prose and catalog homepages can never substitute for dated demand.
    evidence_gate = _fresh_research_quorum(radar_snapshot)
    if not evidence_gate["passed"]:
        stages.clear_stage("hermes")
        output_dir = _home() / "agent_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        rejected_path = output_dir / f"{job['id']}-rejected-freshness.md"
        rejected_path.write_text(
            "# HERMES — Blocked at Freshness Evidence Gate\n\n"
            f"Eligible dated signals: {evidence_gate['eligible_items']} "
            f"(minimum {evidence_gate['minimum_items']})\n\n"
            f"Independent source types: {evidence_gate['eligible_sources']} "
            f"(minimum {evidence_gate['minimum_sources']})\n\n"
            f"Fresh demand-discovery signals: {evidence_gate['demand_items']} (minimum 1)\n\n"
            f"Current catalog comparisons: {evidence_gate['catalog_items']} (minimum 1)\n\n"
            f"Source health: {json.dumps(radar_snapshot.get('source_health') or {}, ensure_ascii=False)}\n\n"
            "No demand score or publishing commission was produced.\n",
            encoding="utf-8",
        )
        blocked_reason = (
            f"fresh evidence quorum not met: {evidence_gate['eligible_items']}/"
            f"{evidence_gate['minimum_items']} items, {evidence_gate['eligible_sources']}/"
            f"{evidence_gate['minimum_sources']} independent source types, "
            f"{evidence_gate['demand_items']} demand signals, "
            f"{evidence_gate['catalog_items']} catalog comparisons"
        )
        if evidence_gate.get("floor_owned"):
            blocked_reason = (
                f"Floor 05 found {evidence_gate['candidate_count']} candidate(s), "
                "but none passed the deterministic 80/100 book-demand gate"
            )
        _publishing_event(
            job, agent="HERMES", event_type="research_blocked",
            stage="24_48h_date_gate",
            summary="Freshness evidence quorum failed; no book was commissioned",
            details={"reason": blocked_reason, "snapshot": str(radar_path),
                     "source_health": radar_snapshot.get("source_health") or {}},
            status="blocked",
        )
        return {"agent": "HERMES", "mode": "blocked", "_blocked": True,
                "content": "Current market evidence is insufficient; HERMES did not commission a book.",
                "blocked_reason": blocked_reason, "radar_snapshot": str(radar_path),
                "output": str(rejected_path)}

    # Add a credential-free book-supply/competition signal for the strongest
    # discovered queries. These are public catalog results, not sales claims.
    supply: list[dict[str, Any]] = []
    if radar_snapshot.get("catalog_evidence"):
        supply = list(radar_snapshot.get("catalog_evidence") or [])
    elif radar is not None:
        for item in (radar_snapshot.get("items") or [])[:8]:
            query = str(item.get("query") or "").strip()
            if not query:
                continue
            try:
                supply.append(radar.book_supply(query, timeout=10, limit=10))
            except Exception as exc:
                supply.append({"query": query, "error": f"{type(exc).__name__}: {exc}"[:300]})
    # The whole snapshot used to go into the prompt verbatim -- 261,503 chars on
    # 2026-09-23 -- and the same evidence went in AGAIN as the untrusted-evidence
    # bundle. Together ~80,000 tokens into a 16,384-token window, so Ollama
    # dropped ~80% of it from the front: every day's fresh signals were cut and
    # only the fixed instruction tail survived. That is why HERMES returned a
    # byte-identical ANGLE on 20, 21, 22 and 23 September even though the
    # deterministic winner changed (money -> business -> anxiety and depression).
    # Send a compact view instead: same facts the model is allowed to cite
    # (evidence_id, title, source_url, age, bucket), without the per-candidate
    # evidence bundles that made up 180,395 of those chars.
    research_evidence = json.dumps(
        {"trending_now": _compact_radar(radar_snapshot, include_items=False),
         "book_supply": "supplied separately as UNTRUSTED EVIDENCE"},
        ensure_ascii=False, separators=(",", ":"),
    )
    # The engine scores topics without knowing what this floor has already
    # published, so it happily re-crowned a subject the uniqueness gate would
    # reject 300 lines later -- the whole run spent to be thrown away. Drop
    # colliding topics here, while there is still a shortlist to fall back on.
    shortlist = [row for row in (radar_snapshot.get("candidates") or [])
                 if isinstance(row, dict) and row.get("build_eligible")]
    fresh_shortlist = [row for row in shortlist
                       if not _find_kdp_topic_duplicate(str(row.get("topic") or ""), topic_history)]
    winner = radar_snapshot.get("winner") or {}
    if winner and _find_kdp_topic_duplicate(str(winner.get("topic") or ""), topic_history) and fresh_shortlist:
        superseded = str(winner.get("topic") or "")
        winner = fresh_shortlist[0]
        radar_snapshot["winner"] = winner
        _publishing_event(
            job, agent="HERMES", event_type="winner_repointed",
            stage="topic_uniqueness_gate",
            summary=(f"Deterministic winner {superseded!r} was already commissioned; "
                     f"promoted {winner.get('topic')!r} from the shortlist"),
            details={"superseded": superseded, "promoted": winner.get("topic"),
                     "shortlist": [row.get("topic") for row in fresh_shortlist]},
        )
    # Everything below the winner, newest-first, for the retry after synthesis.
    remaining_shortlist = [row for row in fresh_shortlist
                           if row.get("topic") != winner.get("topic")]
    _publishing_event(
        job, agent="HERMES", event_type="book_demand_shortlist_completed",
        stage="reader_intent_competition_score",
        summary=(f"Selected {winner.get('topic')} at {winner.get('score')}/100"
                 if winner else "No candidate passed the book-demand gate"),
        details={"candidates": [{"topic": row.get("topic"), "score": row.get("score"),
                                  "eligible": row.get("build_eligible"),
                                  "blockers": row.get("blockers", [])}
                                 for row in radar_snapshot.get("candidates") or []],
                 "winner": winner.get("topic"), "winner_score": winner.get("score")},
    )

    def _synthesis_prompt(active_winner: dict[str, Any], rejected: str = "") -> str:
        return (
        "You are HERMES, head of Book Publishing at a digital holding company, "
        "commissioning the next Amazon KDP title.\n\n"
        f"Request: {task}\n\n"
        "Commission a nonfiction utility book inside Vineet Pandey's demonstrated "
        "authority lane: Windows, PowerShell, networking, enterprise automation, "
        "agentic AI operations, AI governance, or an adjacent implementation "
        "playbook. Reject generic wellness, retirement, romance, horror, lifestyle, "
        "and trend-chasing concepts even if the raw trend is strong. Ground the "
        "decision in purchase intent, a reachable buyer, and a defensible gap. "
        "Do not invent internal teams, tools, boards or "
        "databases — the only production system is an automated drafting pipeline.\n\n"
        "That pipeline cannot research. It cannot look a fact up, read a document, "
        "interview anyone or verify a name, so do not commission a book whose honest "
        "execution needs specific factual claims about real named organisations, "
        "government programmes, current events, or living people — every specific in "
        "it would be invented and the book would be unpublishable. Nonfiction is "
        "welcome when it delivers a method, framework or skill the reader applies to "
        "their own life.\n\n"
        # The contradiction that cost four runs. This line survived the
        # 2026-10-14 prompt-gate fix one screen below it, and it wins: asked
        # for "exact source_url values" that were stripped before it ever saw
        # the evidence, the model supplied URL-shaped tokens instead - on the
        # 16:05 run, eight base64 Google News redirect fragments, none of
        # which appear anywhere in its context. It was obeying the prompt.
        "Use ONLY the captured evidence below, and cite it by the evidence_id "
        "each radar item carries. The evidence deliberately carries no URLs: "
        "there is no link to quote, and a URL-shaped citation is an invented one. "
        "The Floor 05 engine has already selected the winner deterministically. Use only "
        "that winner; do not replace it, alter its scores, or invent a different candidate. "
        "Do not claim you searched sources that are absent. A viral headline is not book demand: "
        "corroborate 24-hour acceleration with persistence and book-supply evidence. "
        "Treat only 0-24h and 24-48h discovery buckets as demand evidence; never score or cite "
        "signals in >48h or unknown buckets. Catalog supply is a separate current-index signal.\n\n"
        f"Floor-owned operating method:\n{_publishing_skill_text()}\n\n"
        f"Machine-captured official/public evidence (discovery and catalog supply; neither proves sales):\n{research_evidence}\n\n"
        f"Deterministic winner: "
        f"{json.dumps(_without_urls(active_winner), ensure_ascii=False)}\n\n"
        # The evidence is news, so the model kept building the book on top of it:
        # on 2026-09-19 it commissioned a title whose whole "why now" was Meta and
        # Accenture reorganising their management layers, and the sourcing gate
        # refused it a step later, as it should - we cannot check what either
        # company did. The evidence proves a subject is being discussed. It is
        # not the subject, and the names in it are not ours to repeat.
        "The captured evidence tells you WHAT subject readers are circling right "
        "now. It is not the book. Do not carry its names into the commission: the "
        "ANGLE and the BRIEF must not name a single real company, institution, "
        "government body, product or living person, and 'why now' must rest on "
        "what the reader is dealing with in their own life or work - not on what "
        "some organisation announced. A brief that leans on a named organisation "
        "is refused at the next gate and the whole run is wasted.\n\n"
        "Use the earning catalogue control as the packaging benchmark: an exact "
        "utility phrase, a concrete outcome, high contrast, and a proof cue readable "
        "at 120x192 pixels. Do not imitate its artwork. Reject dark cinematic "
        "photography with a long abstract title and tiny subtitle. Prefer a literal "
        "title under 60 characters and a $2.99-$4.99 launch-price hypothesis. "
        "Define the lead magnet and distribution before manuscript production.\n\n"
        "Reply in exactly this shape:\n"
        "MODE: nonfiction\n"
        "REGION: <primary market, e.g. global or india>\n"
        "ANGLE: <one line — the specific hook this book leads with, naming no real "
        "organisation or person>\n"
        "TITLE: <literal benefit-led working title, preferably <=60 characters>\n"
        "BUYER: <one specific role and problem>\n"
        "PURCHASE_QUERY: <exact problem-led query a buyer would type>\n"
        "SERIES: <Windows Power User Field Guides | Enterprise Automation Playbooks | Agentic AI Operations>\n"
        "LAUNCH_PRICE_USD: <2.99-4.99 unless evidence justifies another price>\n"
        "THUMBNAIL_PROMISE: <3-6 dominant words plus one concrete proof/benefit badge>\n"
        "LEAD_MAGNET: <one useful checklist, command sheet, template, or workbook>\n"
        "LINKEDIN_ANGLES: <three teaching-post angles>\n"
        "A_PLUS_PLAN: <three visual modules>\n"
        "DEMAND_SCORE: <0-100>\nBUYER_INTENT_SCORE: <0-100>\n"
        "DIFFERENTIATION_SCORE: <0-100>\n"
        "PACKAGING_SCORE: <0-100>\nTHUMBNAIL_CLARITY_SCORE: <0-100>\n"
        "SERIES_FIT_SCORE: <0-100>\nLAUNCH_READINESS_SCORE: <0-100>\n"
        # Asked for exactly what the gate accepts. This line used to read
        # "URLs or named current sources", which was impossible and useless in
        # turn: source_url is stripped before the model ever sees the evidence
        # (it was half the token bundle), and a named source cannot be checked
        # against anything. The model obeyed the line it was given - on
        # 2026-10-13 it wrote "Recent reports on rising industrial maintenance
        # costs" - and the gate correctly refused it. The instruction to cite
        # evidence_ids existed only in the media floor's prompt, never here.
        # No specimen id here on purpose. The first version of this line carried
        # "e.g. [a1b2c3d4e5f60718293a]" and on 2026-10-14 the model copied that
        # placeholder straight into its answer, then invented a second one with
        # letters that are not even hex. A concrete example in a prompt is an
        # answer the model is allowed to give.
        "EVIDENCE: <one line per claim, each ending with the evidence_id of the "
        "radar item it comes from, in square brackets. Copy the id exactly as it "
        "appears in the radar above - never compose, shorten or invent one. A "
        "claim you cannot tie to a radar item does not belong here>\n"
        "BRIEF:\n"
        "<8-14 lines: target reader, why now, competing titles, what makes this "
        "one different, and the honest commercial risk>"
        + avoid
        + (("\n\nThe angle you proposed a moment ago was rejected as a repeat "
            "of a book this floor already commissioned:\n" + rejected + "\n"
            "Commission the winner named above instead, and lead with a different "
            "reader problem.") if rejected else "")
        )

    def _synthesise(active_winner: dict[str, Any], rejected: str = "") -> tuple[str, str]:
        return _research_synthesis(
            _synthesis_prompt(active_winner, rejected),
            # Same items, same trimmed shape as the prompt's own copy: the full
            # rows were being sent here as well, so the day's evidence arrived
            # twice and neither copy survived the context window.
            max_tokens=2200, evidence={"eligible": _compact_radar(radar_snapshot)["items"],
                                       "catalog_evidence": supply,
                                       "counts": radar_snapshot.get("freshness_counts", {}),
                                       "policy": radar_snapshot.get("freshness_policy", "")},
        )

    brief, note = _synthesise(winner)

    if not brief:
        # Research evidence is a hard requirement. A local planning template
        # is not a substitute and must never be presented as completed market
        # research simply because the cloud provider is unavailable.
        stages.clear_stage("hermes")
        safe_note = str(note or "research provider unavailable")[:1200]
        blocked = {
            "agent": "HERMES",
            "mode": "blocked",
            "content": (
                "Live market research did not run. HERMES stopped before "
                "commissioning because no evidence-capable provider was available."
            ),
            "blocked_reason": safe_note,
            "radar_snapshot": str(radar_path),
            "_blocked": True,
        }
        _publishing_event(
            job, agent="HERMES", event_type="research_blocked",
            stage="provider_gate",
            summary="Live market research blocked; no book was commissioned",
            details={"reason": safe_note, "radar_snapshot": str(radar_path)},
            status="blocked",
        )
        return blocked

    required_markers = (
        "TITLE", "BUYER", "PURCHASE_QUERY", "SERIES", "LAUNCH_PRICE_USD",
        "THUMBNAIL_PROMISE", "LEAD_MAGNET", "LINKEDIN_ANGLES", "A_PLUS_PLAN",
        "DEMAND_SCORE", "BUYER_INTENT_SCORE",
        "DIFFERENTIATION_SCORE", "PACKAGING_SCORE", "THUMBNAIL_CLARITY_SCORE",
        "SERIES_FIT_SCORE", "LAUNCH_READINESS_SCORE", "EVIDENCE",
    )
    if any(not _marker(brief, marker) for marker in required_markers):
        audit_text, audit_note = _research_synthesis(
            "Act as an evidence auditor, not a commissioning writer. Audit the candidate below "
            "against the captured reader-demand and book-competition evidence below. "
            # Same correction as the commissioning contract above: this asked
            # for source_url, which the evidence it is handed does not carry.
            "Cite only the evidence_id values supplied below; do not invent "
            "citations or name sources that are not in them. "
            "Return ONLY these markers. Scores must be 0-100 or UNKNOWN; "
            "EVIDENCE must quote evidence_ids in square brackets:\n"
            "TITLE:\nBUYER:\nPURCHASE_QUERY:\nSERIES:\nLAUNCH_PRICE_USD:\n"
            "THUMBNAIL_PROMISE:\nLEAD_MAGNET:\nLINKEDIN_ANGLES:\nA_PLUS_PLAN:\n"
            "DEMAND_SCORE:\nBUYER_INTENT_SCORE:\n"
            "DIFFERENTIATION_SCORE:\nPACKAGING_SCORE:\nTHUMBNAIL_CLARITY_SCORE:\n"
            "SERIES_FIT_SCORE:\nLAUNCH_READINESS_SCORE:\nEVIDENCE:\n\n"
            f"Candidate:\n{brief}\n\nCaptured evidence:\n{research_evidence}",
            max_tokens=1200, evidence={"eligible": radar_snapshot.get("items", []),
                                       "catalog_evidence": supply,
                                       "counts": radar_snapshot.get("freshness_counts", {}),
                                       "policy": radar_snapshot.get("freshness_policy", "")},
        )
        if audit_text:
            brief = f"{brief}\n\nEVIDENCE AUDIT:\n{audit_text}"
        elif audit_note:
            note = f"{note}; evidence audit unavailable: {audit_note}".strip("; ")

    # A provider returning fluent prose is not the same thing as completing
    # the research contract.  Fail closed unless the post-audit brief has the
    # full scorecard and provenance a reader could follow.  This prevents the
    # monitor from labelling a generic trend summary as completed research.
    #
    # Provenance is a resolvable evidence id OR a literal URL. This system
    # strips source_url before the model ever sees it - the URLs were half the
    # token bundle, see _RADAR_ITEM_FIELDS - so demanding "https://" in the
    # brief asked the model for something its own context forbids. Run
    # hermes-a75ab9b40ca8 was rejected on 2026-10-10 for "direct evidence
    # URLs: 0" having cited its sources correctly, by id, exactly as the
    # system prompt instructs. An id counts only when it resolves against this
    # run's own snapshot, so an invented one still fails the gate.
    score_markers = {marker for marker in required_markers if marker.endswith("_SCORE")}
    missing_markers = [
        marker for marker in required_markers
        if (not _marker(brief, marker) if marker in score_markers
            else not re.search(rf"^[ \t]*\**{re.escape(marker)}\**[ \t]*:",
                               brief, re.MULTILINE | re.IGNORECASE))
    ]
    evidence_value = _evidence_block(brief)
    direct_urls = re.findall(r"https?://[^\s,)]+", evidence_value)
    cited_ids = _evidence_urls(radar_snapshot, evidence_value or brief)
    if missing_markers or not (direct_urls or cited_ids):
        stages.clear_stage("hermes")
        output_dir = _home() / "agent_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        rejected_path = output_dir / f"{job['id']}-rejected-research.md"
        rejected_path.write_text(
            "# HERMES — Rejected Research Output\n\n"
            f"Missing score fields: {', '.join(missing_markers) or 'none'}\n\n"
            f"Provenance: {len(direct_urls)} direct URL(s), "
            f"{len(cited_ids)} resolvable evidence id(s)\n\n{brief}\n",
            encoding="utf-8",
        )
        blocked = {
            "agent": "HERMES", "mode": "blocked", "_blocked": True,
            "content": "Research output failed the idea-scorecard quality gate.",
            "blocked_reason": (
                f"missing score fields: {', '.join(missing_markers) or 'none'}; "
                f"provenance: {len(direct_urls)} url(s), {len(cited_ids)} evidence id(s)"
                + (f"; {_unknown_cited_ids(radar_snapshot, evidence_value)} cited id(s) "
                   "match no radar item"
                   if _unknown_cited_ids(radar_snapshot, evidence_value) else "")
                + (f"; {_unresolved_citations(radar_snapshot, evidence_value)} cited source(s) "
                   "are not in this run's evidence"
                   if _unresolved_citations(radar_snapshot, evidence_value) else "")
            ),
            "radar_snapshot": str(radar_path), "output": str(rejected_path),
        }
        _publishing_event(
            job, agent="HERMES", event_type="research_blocked",
            stage="output_quality_gate",
            summary="Rejected: provider did not return a scored, evidence-linked idea brief",
            details={"missing_markers": missing_markers,
                     "direct_evidence_urls": len(direct_urls),
                     "result": str(rejected_path)},
            status="blocked",
        )
        return blocked

    kdp_mode = _marker(brief, "MODE", "nonfiction").lower()
    if kdp_mode != "nonfiction":
        kdp_mode = "nonfiction"
    region = _marker(brief, "REGION", "global").lower()
    angle = _marker(brief, "ANGLE")

    # A repeat used to end the day 300 lines below this point, with the brief
    # file and the vault note already written for a candidate that was always
    # going to be thrown away -- four days in a row, 20-23 September. The engine
    # scored six candidates and only ever the first was tried. Ask again with
    # the next one, here, while nothing has been written yet.
    for attempt, next_winner in enumerate(remaining_shortlist[:2], start=1):
        collision = _find_kdp_topic_duplicate(angle, topic_history) if angle else None
        if not collision:
            break
        _publishing_event(
            job, agent="HERMES", event_type="duplicate_retry",
            stage="topic_uniqueness_gate",
            summary=(f"Angle repeated a prior commission; retrying with "
                     f"{next_winner.get('topic')!r} (attempt {attempt})"),
            details={"rejected_angle": angle, "collision": collision,
                     "next_topic": next_winner.get("topic")},
        )
        retry_brief, retry_note = _synthesise(next_winner, angle)
        if not retry_brief:
            break
        brief, note = retry_brief, retry_note
        winner = next_winner
        radar_snapshot["winner"] = next_winner
        kdp_mode = _marker(brief, "MODE", "nonfiction").lower()
        if kdp_mode != "nonfiction":
            kdp_mode = "nonfiction"
        region = _marker(brief, "REGION", "global").lower()
        angle = _marker(brief, "ANGLE")

    # The book's own identity, and nothing else. This used to append the whole
    # `brief` as well, which made the lane gate decorative: on 2026-10-23 "The
    # Business Plan Workbook: Build Your Roadmap in 30 Days" passed it on a
    # single match - the series label the model had just written itself. Its
    # title, buyer ("aspiring entrepreneur") and purchase query ("business plan
    # book pdf") are nowhere near the lane, and on these four fields it fails.
    authority = publishing_strategy.authority_fit(
        "\n".join((_marker(brief, "TITLE"), angle, _marker(brief, "BUYER"),
                   _marker(brief, "PURCHASE_QUERY")))
    )
    selected_series = _marker(brief, "SERIES")
    allowed_series = {
        "Windows Power User Field Guides", "Enterprise Automation Playbooks",
        "Agentic AI Operations",
    }
    if not authority["passed"] or selected_series not in allowed_series:
        stages.clear_stage("hermes")
        reason = ("candidate is outside Vineet Pandey's demonstrated authority lane"
                  if not authority["passed"] else
                  "candidate did not select exactly one approved catalogue series")
        _publishing_event(
            job, agent="HERMES", event_type="research_blocked",
            stage="authority_fit_gate", summary=f"Rejected: {reason}",
            details={"reason": reason, "authority_matches": authority["matches"],
                     "series": selected_series}, status="rejected",
        )
        return {
            "agent": "HERMES", "mode": "blocked", "_blocked": True,
            "content": "Candidate rejected before BIBLOS at the authority-catalogue gate.",
            "blocked_reason": reason, "angle": angle,
            "radar_snapshot": str(radar_path),
        }

    unsourceable, sourcing_reason = _sourcing_gate(brief, kdp_mode)
    if unsourceable:
        stages.clear_stage("hermes")
        output_dir = _home() / "agent_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        rejected_path = output_dir / f"{job['id']}-rejected-sourcing.md"
        rejected_path.write_text(
            "# HERMES — Rejected at the Sourcing Gate\n\n"
            f"Reason: {sourcing_reason}\n\n"
            "This candidate would need facts the drafting pipeline cannot obtain, "
            "so nothing was commissioned.\n\n"
            f"{brief}\n",
            encoding="utf-8",
        )
        blocked = {
            "agent": "HERMES", "mode": "blocked", "_blocked": True,
            "content": (
                "Candidate refused at the sourcing gate: it would need facts about the "
                "real world that this pipeline cannot research, so the book could only "
                "be written by inventing them."
            ),
            "blocked_reason": sourcing_reason,
            "angle": angle, "kdp_mode": kdp_mode,
            "radar_snapshot": str(radar_path), "output": str(rejected_path),
        }
        _publishing_event(
            job, agent="HERMES", event_type="research_blocked",
            stage="sourcing_gate",
            summary="Refused: candidate requires unverifiable real-world claims",
            details={"reason": sourcing_reason, "angle": angle,
                     "result": str(rejected_path)},
            status="blocked",
        )
        return blocked

    output_dir = _home() / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job['id']}.md"
    output_path.write_text(
        f"# HERMES — KDP Commissioning Brief\n\n"
        f"Request: {task}\n\nResearch engine: "
        f"{radar_snapshot.get('library') or 'floor-local-fallback'} "
        f"v{radar_snapshot.get('library_version') or 'unknown'}; synthesis: "
        f"{os.environ.get('ONE_LOCAL_RESEARCH_MODEL', 'qwen3.5:9b')}\n\n"
        f"{brief}\n"
        # The model cites evidence ids, not links: the URLs never go into
        # the prompt because they were half its weight. Resolve the ones it
        # actually cited, so the brief a human reads still carries sources.
        + _cited_sources_block(radar_snapshot, brief),
        encoding="utf-8",
    )

    remembered = memory.remember(
        agent="HERMES", floor_id="5", floor_name="Book Publishing (KDP)",
        kind="Commissioning Brief", body=brief, task=task,
        tags=["kdp", "publishing", kdp_mode],
    )

    result: dict[str, Any] = {
        "agent": "HERMES",
        "mode": mode,
        "research_engine": "free-local (Sanjeevani/Ollama)",
        "kdp_mode": kdp_mode,
        "region": region,
        "angle": angle,
        "content": brief,
        "output": str(output_path),
        "vault_note": remembered.get("path"),
        "prior_titles_considered": len(already),
        "mission_id": mission_id,
        "radar_snapshot": str(radar_path),
        "radar_signal_count": len(radar_snapshot.get("items") or []),
    }

    _publishing_event(job, agent="HERMES", event_type="research_completed",
                      stage="24h_demand_radar", summary=angle or "Research brief completed",
                      details={"region": region, "mode": kdp_mode, "evidence": _marker(brief, "EVIDENCE")})

    # Commissioning the book is the DEFAULT. Telling a floor head to do its job
    # shouldn't require remembering which verb the router happens to map to
    # "execute" — any dispatch that reaches HERMES runs the whole pipeline.
    # Research-only is the explicit exception, asked for in plain words.
    lowered_task = task.lower()
    research_only = bool(re.search(
        r"\b(research|analysis|planning|plan)\s+only\b|"
        r"\b(do not|don't|dont|without)\s+(commission|build|produce|write)\b|"
        r"\bno\s+(commission|production|book build)\b",
        lowered_task,
    ))
    if research_only:
        stages.clear_stage("hermes")
        result["handed_to"] = None
        result["note"] = (
            "Research only — nothing handed to SCRIBE, because the request asked "
            "to plan/draft/research. Say it without those words (e.g. 'HERMES, "
            "get the next book done') to commission it for real."
        )
        _publishing_event(
            job, agent="HERMES", event_type="research_only_completed",
            stage="24_48h_date_gate",
            summary="Governed research completed; no book was commissioned",
            details={"radar_snapshot": str(radar_path), "result": str(output_path)},
            status="completed",
        )
        return result

    def score(name: str) -> float | None:
        raw = _marker(brief, name)
        try:
            return max(0.0, min(100.0, float(raw)))
        except (TypeError, ValueError):
            return None

    # The discovery engine ranks topics; it does not know the author's
    # authority, final title, thumbnail, series or launch plan. Those commercial
    # dimensions must come from the finished commissioning brief rather than
    # inheriting optimistic topic proxies from the trend engine.
    dimensions = {
        "demand": score("DEMAND_SCORE"),
        "buyer_intent": score("BUYER_INTENT_SCORE"),
        "authority_fit": authority["score"],
        "differentiation": score("DIFFERENTIATION_SCORE"),
        "packaging": score("PACKAGING_SCORE"),
        "thumbnail_clarity": score("THUMBNAIL_CLARITY_SCORE"),
        "series_fit": score("SERIES_FIT_SCORE"),
        "launch_readiness": score("LAUNCH_READINESS_SCORE"),
    }
    evidence: list[dict[str, Any]] = []
    if winner.get("evidence"):
        evidence.extend(dict(row) for row in winner["evidence"].values() if isinstance(row, dict))
    # BIBLOS asks for three kinds of evidence by name: demand_discovery,
    # demand_corroboration and competition. The winner's own bundle carries
    # reader intent, persistence and competition, and the discovery signals
    # that produced the candidate in the first place only reached BIBLOS when
    # there was no winner at all - so a real winner could never be audited and
    # every candidate came back UNKNOWN. They are added properly now.
    #
    # Sanjeevani and Floor 5 also name the same things differently: a search
    # index calls a signal news_context or social_discussion, the portfolio
    # calls it demand_discovery. Translated here, at the boundary between the
    # two vocabularies, and only the label changes - no item is added,
    # reweighted or invented, and anything unrecognised keeps its own name so
    # BIBLOS can still refuse it.
    discovery_roles = {"news_context": "demand_discovery",
                       "social_discussion": "demand_discovery",
                       "technical_community": "demand_discovery",
                       "web_discovery": "demand_discovery",
                       "demand_discovery": "demand_discovery",
                       "news_corroboration": "demand_corroboration",
                       "discussion_persistence": "demand_corroboration"}
    seen_roles = {str(row.get("role") or "") for row in evidence}
    for row in (radar_snapshot.get("items") or []):
        if not isinstance(row, dict):
            continue
        mapped = discovery_roles.get(str(row.get("role") or ""))
        if not mapped or mapped in seen_roles:
            continue
        item = dict(row)
        item["role"] = mapped
        item["role_as_captured"] = row.get("role")
        evidence.append(item)
        seen_roles.add(mapped)
    cited = _marker(brief, "EVIDENCE")
    if cited:
        evidence.append({"source": cited, "role": "demand_corroboration",
                         "captured_at": _now(), "research_engine": result["research_engine"],
                         "limitations": "Local synthesis over captured public evidence; BIBLOS must retain source URLs."})
    try:
        radar = floors_bridge.load("floor_05_publishing", "publishing_demand_radar")
        if radar is not None and angle:
            evidence.append(radar.book_supply(angle))
    except Exception as exc:
        evidence.append({"role": "competition_unavailable", "captured_at": _now(),
                         "error": f"{type(exc).__name__}: {exc}"[:500]})

    # Uniqueness is a deterministic gate, not another instruction for the
    # model to follow. Stop here before BIBLOS spends a slot on a known topic;
    # the same check runs again in _hermes_commission to close the race where
    # another title is completed while this audit is in flight.
    duplicate = _find_kdp_topic_duplicate(angle, topic_history)
    if duplicate:
        stages.clear_stage("hermes")
        _publishing_event(
            job, agent="HERMES", event_type="duplicate_rejected",
            stage="topic_uniqueness_gate",
            summary="Candidate duplicates KDP topic history; BIBLOS not started",
            details=duplicate, status="rejected",
        )
        result.update({"handed_to": None, "duplicate": duplicate})
        result["content"] = "Duplicate KDP topic rejected before commercial audit."
        return result

    # New titles never go straight from an attractive brief into production.
    # BIBLOS is the commercial gate; only an evidence-complete 80+ candidate
    # comes back to HERMES for commissioning.
    if not _job_is_active(str(job["id"])):
        stages.clear_stage("hermes")
        result["handed_to"] = None
        result["note"] = "Queue ownership expired before BIBLOS handoff; no downstream job was created."
        return result

    worker = stages.head_briefs_worker(
        "hermes", "biblos",
        carrying_detail=f"Taking the researched candidate to BIBLOS: {angle[:60]}",
        briefing_detail=f"BIBLOS, validate demand before we commission: {angle[:90]}",
        awaiting_detail="Waiting on BIBLOS commercial validation",
        enqueue=lambda: enqueue_job(
            "biblos", json.dumps({"workflow": "publishing_portfolio",
                "phase": "audit", "title_id": job["id"],
                "brief_path": str(output_path), "kdp_mode": kdp_mode,
                "region": region, "angle": angle, "origin_job": job["id"],
                "mission_id": mission_id, "objective": task,
                "select_active": False,
                "wide_requested": kdp_mode == "nonfiction",
                "dimensions": dimensions, "evidence": evidence}),
            mode="execute",
            tier="fast",
        ),
    )
    result["handed_to"] = {"agent": "BIBLOS", "job_id": worker["id"]}
    result["note"] = (
        "Candidate handed to BIBLOS. Production starts only if purchase-intent "
        "evidence is complete, every commercial hard floor passes, and the "
        "weighted score is at least 85."
    )
    return result


def _hermes_commission(job: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Commission a BIBLOS-approved title; this is the only path to SCRIBE."""
    angle = str(payload.get("angle") or "")
    # This runs in a later job, by which time the research phase has written its
    # own commissioning note to the vault -- and the vault is one of the sources
    # the history reads. An exact self-match here is that note, not a repeat:
    # the research phase already cleared this exact string against a snapshot
    # taken before it wrote anything. Anything short of an exact match, and any
    # record from the book-factory output logs, still blocks as before.
    history = [record for record in _kdp_topic_history()
               if not (record.get("source") == "ONE Vault / Floor 05"
                       and str(record.get("topic") or "").strip() == angle.strip())]
    duplicate = _find_kdp_topic_duplicate(angle, history)
    if duplicate:
        stages.clear_stage("hermes")
        _publishing_event(
            job, agent="HERMES", event_type="duplicate_rejected",
            stage="topic_uniqueness_gate",
            summary="Previously commissioned KDP topic rejected before SCRIBE",
            details=duplicate, status="rejected",
        )
        return {
            "agent": "HERMES", "mode": "commission", "blocked": True,
            "duplicate": duplicate, "handed_to": None,
            "content": "Candidate duplicates an existing KDP topic; SCRIBE was not started.",
        }
    if not _job_is_active(str(job["id"])):
        stages.clear_stage("hermes")
        return {
            "agent": "HERMES", "mode": "cancelled", "handed_to": None,
            "content": "Queue ownership expired before SCRIBE handoff; no book was commissioned.",
        }
    worker = stages.head_briefs_worker(
        "hermes", "scribe",
        carrying_detail=f"Taking the validated brief to SCRIBE: {angle[:60]}",
        briefing_detail=f"SCRIBE, build this 85+ authority-lane candidate: {angle[:100]}",
        awaiting_detail="Waiting on SCRIBE to produce the enriched manuscript",
        enqueue=lambda: enqueue_job(
            "scribe", json.dumps(payload), mode="execute", tier="heavy"),
    )
    _publishing_event(job, agent="HERMES", event_type="commissioned",
                      stage="production_slot", summary="BIBLOS-approved title commissioned to SCRIBE",
                      details={"score": (payload.get("audit") or {}).get("score"), "scribe_job_id": worker["id"]})
    return {"agent": "HERMES", "mode": "commission", "commercial_audit": payload.get("audit"),
            "handed_to": {"agent": "SCRIBE", "job_id": worker["id"]},
            "content": "BIBLOS threshold passed; enriched book commissioned."}


def _hermes_report(job: dict[str, Any]) -> dict[str, Any]:
    """Third leg: SCRIBE has delivered, HERMES reports the result upward."""
    stages.set_stage("hermes", stages.REPORTING, "Reporting the finished book")
    try:
        payload = json.loads(str(job.get("task") or "{}"))
    except json.JSONDecodeError:
        payload = {}

    run_dir = payload.get("run_dir") or "(not reported by LAO)"
    title = payload.get("title") or "(title in the run folder)"
    message = (
        f"Sir, the book is finished. SCRIBE has handed it over.\n\n"
        f"Title: {title}\n"
        f"Location: {run_dir}\n\n"
        "It is ready for upload to Amazon KDP. That upload is a manual step — "
        "I have not touched it."
    )

    output_dir = _home() / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job['id']}.md"
    output_path.write_text(f"# HERMES — Delivery Report\n\n{message}\n", encoding="utf-8")

    remembered = memory.remember(
        agent="HERMES", floor_id="5", floor_name="Book Publishing (KDP)",
        kind="Delivery Report",
        body=f"{message}\n\nANGLE: {title}\n",
        tags=["kdp", "publishing", "delivered", "awaiting-upload"],
    )

    time.sleep(2.0)
    stages.clear_stage("hermes")
    return {
        "agent": "HERMES",
        "mode": "report",
        "content": message,
        "run_dir": run_dir,
        "title": title,
        "output": str(output_path),
        "vault_note": remembered.get("path"),
        "requires_human": "Amazon KDP upload",
    }


def _publishing_growth_logic() -> Any:
    logic = floors_bridge.load("floor_05_publishing", "portfolio_growth_runtime")
    if logic is None:
        raise RuntimeError("Floor 05 portfolio-growth logic is unavailable or unsafe to load")
    return logic


def _json_task(job: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(str(job.get("task") or "{}"))
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _run_biblos(job: dict[str, Any]) -> dict[str, Any]:
    payload = _json_task(job)
    stages.worker_confirms_receipt("biblos", "Auditing current demand evidence")
    stages.set_stage("biblos", stages.EXECUTING, "Scoring demand, conversion and expansion potential")
    audit = publishing_strategy.commercial_audit(
        str(payload.get("title_id") or job["id"]),
        payload.get("dimensions") or {}, payload.get("evidence") or [],
    )
    missing_labels = list(audit.get("missing") or []) + list(audit.get("missing_evidence") or [])
    audit_summary = (
        f"Commercial score {audit['score']}/100"
        if audit.get("score") is not None
        else "Rejected: missing " + ", ".join(missing_labels)
    )
    _publishing_event(job, agent="BIBLOS", event_type="commercial_score",
                      stage="commercial_gate", summary=audit_summary,
                      details={"score": audit["score"], "dimensions": audit.get("dimensions"),
                               "eligible": audit["build_eligible"], "missing": audit.get("missing"),
                               "missing_evidence": audit.get("missing_evidence"),
                               "floor_failures": audit.get("floor_failures")},
                      status="running" if audit["build_eligible"] else "rejected")
    if not audit["build_eligible"]:
        stages.clear_stage("biblos"); stages.clear_stage("hermes")
        return {"agent": "BIBLOS", "audit": audit, "handed_to": None,
                "content": "Candidate rejected before production; score must be 85+ with purchase-intent evidence and every commercial hard floor passed."}
    commission = dict(payload)
    commission.update({"phase": "commission", "audit": audit})
    worker = stages.head_briefs_worker(
        "biblos", "hermes",
        carrying_detail=f"Taking {audit['score']}/100 validation back to HERMES",
        briefing_detail="HERMES, this candidate cleared the commercial threshold",
        awaiting_detail="Validation delivered",
        enqueue=lambda: enqueue_job("hermes", json.dumps(commission), mode="execute", tier="heavy"),
    )
    stages.clear_stage("biblos")
    return {"agent": "BIBLOS", "audit": audit,
            "handed_to": {"agent": "HERMES", "job_id": worker["id"]},
            "content": f"Commercial score {audit['score']}/100; eligible for one of the weekly production slots."}


def _run_mercury(job: dict[str, Any]) -> dict[str, Any]:
    payload = _json_task(job); logic = _publishing_growth_logic()
    stages.worker_confirms_receipt("mercury", "Checking rights, exclusivity and store route")
    route = logic.distribution_route(str(payload.get("title") or job["id"]),
                                     str(payload.get("kdp_mode") or "nonfiction"),
                                     payload.get("select_active"),
                                     bool(payload.get("wide_requested")))
    _publishing_event(job, agent="MERCURY", event_type="distribution_route",
                      stage="rights_and_distribution", summary=f"Route: {route['route']}",
                      details=route, status="blocked" if route["route"] == "HOLD" else "running")
    if route["route"] == "HOLD":
        stages.clear_stage("mercury")
        scribe_id = str(payload.get("scribe_job_id") or "")
        if scribe_id:
            with _connect() as db:
                db.execute("UPDATE jobs SET status='blocked', result=?, updated_at=? WHERE id=?",
                           (json.dumps({**payload, "distribution": route}), _now(), scribe_id))
        return {"agent": "MERCURY", "distribution": route, "content": route["reason"]}
    economics = dict(payload); economics.update({"workflow": "publishing_portfolio",
                                                  "phase": "economics", "distribution": route})
    stages.set_stage("mercury", stages.CARRYING_TO_HEAD,
                     f"Taking {route['route']} economics request to ALFA", worker="alfa")
    alfa_job = enqueue_job("alfa", json.dumps(economics), mode="execute", tier="fast")
    stages.clear_stage("mercury")
    return {"agent": "MERCURY", "distribution": route,
            "handed_to": {"agent": "ALFA", "job_id": alfa_job["id"]},
            "content": "Rights-safe route proposed; no store was changed."}


def _queue_print_formats(job: dict[str, Any], packet: Any, run_dir: str,
                         scribe_job_id: str, ebook_asin: str) -> dict[str, Any]:
    """Build the print interior and queue whichever formats the length allows.

    The factory emits A4, which is not a KDP trim, so the eBook manuscript can
    never be a print interior; kdp_print_interior rewrites it to 6 x 9 with the
    gutter that page count requires. Hardcover starts at 75 pages, so a short
    book is simply a paperback - reported, not raised, because refusing the
    whole run over a length KDP itself allows for paperback helps nobody.
    """
    from openjarvis.tools import kdp_print_packet as print_packet
    from openjarvis.tools.kdp_paperback import preflight_paperback
    from openjarvis.tools.kdp_print_interior import eligible_formats

    # Both halves of this used to be estimates, and both were wrong. Format
    # eligibility came from a word count, and the cover came from whatever the
    # factory had already put in visual_assets - a wrap measuring 12.747 in
    # around a 46-page book, a spine cut for roughly 220 pages. Building the
    # packet renders the interior, counts the pages it actually has, and cuts
    # the cover to that, which is the only order a physical book allows.
    try:
        packet_files = print_packet.build(run_dir)
    except Exception as exc:  # noqa: BLE001 - the eBook is already live
        return {"queued": [], "error": f"{type(exc).__name__}: {exc}"[:200]}

    # Checked rather than trusted, against the same preflight a person would
    # run. A rejected upload costs one of the format's two weekly slots.
    check = preflight_paperback(run_dir)
    if not check.ready:
        return {"queued": [], "skipped": "the print packet does not pass preflight",
                "errors": check.errors, **packet_files.to_dict()}

    allowed = eligible_formats(packet_files.page_count)
    queued: list[dict[str, Any]] = []
    for fmt in ("paperback", "hardcover"):
        if not allowed.get(fmt):
            continue
        child = enqueue_job("imprimatur", json.dumps({
            "phase": "print", "format": fmt, "run_dir": run_dir,
            "scribe_job_id": scribe_job_id, "ebook_asin": ebook_asin,
            "interior_path": packet_files.interior_pdf,
            "cover_path": packet_files.cover_pdf,
        }), mode="execute", tier="fast")
        queued.append({"format": fmt, "job_id": child["id"]})

    _publishing_event(job, agent="IMPRIMATUR", event_type="print_formats_queued",
                      stage="format_expansion",
                      summary=(f"{len(queued)} print format(s) queued from a "
                               f"{packet_files.page_count}-page interior"),
                      details={"queued": queued, "eligibility": allowed.get("reasons", {}),
                               "interior": packet_files.interior_pdf,
                               "cover": packet_files.cover_pdf,
                               "spine_in": round(packet_files.spine_in, 4)})
    return {"queued": queued, "preflight": "passed", **allowed,
            **packet_files.to_dict()}


def _record_edition_isbn(title: str, fmt: str, draft: dict[str, Any]) -> dict[str, Any]:
    """Put this edition's ISBN on the company register.

    Reported rather than raised: the draft exists on Amazon either way, and
    losing a prepared print edition because a register was unavailable would
    be the wrong trade. What must not happen is the ISBN going unrecorded in
    silence, so the outcome travels back in the job result.
    """
    isbn = str(draft.get("isbn") or "")
    if not isbn:
        return {"recorded": False, "reason": "KDP did not show an ISBN for this edition"}

    register = _revenue_service("isbns")
    if register is None:
        return {"recorded": False, "isbn": isbn,
                "reason": "the ISBN register is unavailable"}
    source = str(draft.get("isbn_source") or register.KDP_FREE)
    try:
        row = register.assign(
            isbn, title=title, fmt=fmt, source=source,
            imprint="Independently published" if source == register.KDP_FREE else "")
    except Exception as exc:  # noqa: BLE001
        return {"recorded": False, "isbn": isbn,
                "reason": f"{type(exc).__name__}: {exc}"[:160]}
    return {"recorded": True, "isbn": row["isbn"], "source": row["source"],
            "portable": row["source"] != register.KDP_FREE}


CONTENT_OVERRIDE_ACTION = "kdp_content_override"


def _content_safety_gate(job: dict[str, Any], run_dir: str, packet: Any) -> dict[str, Any] | None:
    """Read the book against the house policy before Amazon ever sees it.

    None when it may proceed. A refusal when it may not.

    Floor 5 publishes unattended since 2026-09-24, and until this ran there
    was no point at which anything read a finished manuscript for the risk
    the owner named first - that a reader is provoked rather than entertained
    and the brand is boycotted over a sentence nobody reviewed. The scanner
    existed and nothing called it.

    Placed at the top of IMPRIMATUR rather than inside one phase, so the eBook
    draft, the submission and the print editions are all covered by the same
    read. A book that cannot be sold as a Kindle edition cannot be sold as a
    paperback either.

    A block is not the end of the road. The rules are deliberately narrow but
    they have been wrong before - on the live catalogue, "lust" once matched
    inside "cluster" - so the owner can override one, per manuscript, through
    OLYMPUS. The override is keyed to the manuscript's checksum: editing the
    book invalidates it and the gate runs again on what was actually changed.
    """
    from openjarvis.tools import kdp_content_safety as safety
    from openjarvis.tools.approval_store import ApprovalStore, STATUS_APPROVED

    try:
        manuscript = Path(run_dir, "book.md").read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        # Not a silent pass. A manuscript nobody can read is a manuscript
        # nobody has checked, and that is the state this gate exists to end.
        return {"agent": "IMPRIMATUR", "phase": "content_refused",
                "reason": f"the manuscript could not be read for review: {exc}",
                "content": "Publishing stopped: the manuscript could not be read for review."}

    report = safety.scan(manuscript, marketing=str(getattr(packet, "description", "") or ""))
    allowed, note = safety.may_publish(report)
    checksum = str((getattr(packet, "checksums", {}) or {}).get("manuscript", ""))

    if allowed:
        if report.verdict == safety.REVIEW:
            _publishing_event(
                job, agent="IMPRIMATUR", event_type="content_findings_raised",
                stage="content_policy", summary=note,
                details={"findings": safety.passages_for_review(report)},
                status="completed")
        return None

    store = ApprovalStore()
    # Keyed to the manuscript's checksum, so an override covers the book the
    # Chairman actually read and expires the moment a word of it changes.
    permission_key = f"{CONTENT_OVERRIDE_ACTION}:{checksum}"
    for prior in store.list_approved():
        if (prior.action_type == CONTENT_OVERRIDE_ACTION
                and prior.permission_key == permission_key):
            _publishing_event(
                job, agent="IMPRIMATUR", event_type="content_block_overridden",
                stage="content_policy",
                summary=f"The Chairman overrode: {report.summary()}",
                details={"approval_id": prior.id, "report": report.to_dict()},
                status="completed")
            return None

    action = store.queue_action(
        action_type=CONTENT_OVERRIDE_ACTION,
        description=f"House content policy blocked: {packet.title} - {report.summary()}",
        payload={"agent_id": "imprimatur", "run_dir": run_dir, "title": packet.title,
                 "report": report.to_dict()},
        permission_key=permission_key, tier="high", ttl_hours=168,
    )
    stages.set_stage("imprimatur", stages.AWAITING_UPLOAD,
                     f"Content policy blocked: {packet.title}")
    _publishing_event(
        job, agent="IMPRIMATUR", event_type="content_policy_blocked",
        stage="content_policy", summary=note,
        details={"approval_id": action.id, "report": report.to_dict()},
        status="blocked")
    return {"agent": "IMPRIMATUR", "phase": "content_refused",
            "approval_id": action.id, "report": report.to_dict(),
            "reason": note,
            "content": (f"{note} Nothing was uploaded. The passages are on the "
                        "approval if this is a false positive.")}


def _run_imprimatur(job: dict[str, Any]) -> dict[str, Any]:
    """Prepare, submit, and monitor one KDP listing as resumable phases."""
    from openjarvis.tools.approval_store import ApprovalStore, STATUS_APPROVED
    from openjarvis.tools.kdp_browser_publisher import (
        TitleCreationLimitReached, poll_asin, prepare_draft, prepare_print_draft,
        submit_approved, validate_packet, write_state,
    )

    payload = _json_task(job)
    mode = str(payload.get("phase") or "prepare").strip().lower()
    run_dir = str(payload.get("run_dir") or "")
    scribe_job_id = str(payload.get("scribe_job_id") or "")
    if not run_dir or not scribe_job_id:
        raise RuntimeError("IMPRIMATUR requires run_dir and scribe_job_id")
    packet = validate_packet(run_dir)

    # Before any phase, because every phase ends at a storefront. The ASIN
    # poll is exempt: it reads back a listing that is already live, and
    # refusing it would only stop the company from learning the ASIN of a
    # book it has already published.
    if mode != "poll":
        refused = _content_safety_gate(job, run_dir, packet)
        if refused is not None:
            return refused

    if mode == "prepare":
        stages.worker_confirms_receipt("imprimatur", f"Preparing KDP draft for {packet.title}")
        stages.set_stage("imprimatur", stages.EXECUTING, "Uploading manuscript and cover to a KDP draft")
        try:
            draft = prepare_draft(packet, headless=False)
        except TitleCreationLimitReached as limit:
            # Amazon grants two new titles per format per week. The book is
            # finished and unchanged; the only thing missing is a slot, so this
            # waits for the next reset instead of failing a run that did
            # everything right. Sunday 00:00 UTC, plus a few minutes so the
            # retry never lands on the boundary itself.
            now = datetime.now(timezone.utc)
            days_ahead = (6 - now.weekday()) % 7 or 7
            reset = (now + timedelta(days=days_ahead)).replace(
                hour=0, minute=5, second=0, microsecond=0)
            stages.set_stage("imprimatur", stages.AWAITING_UPLOAD,
                             f"Waiting for Amazon's next title slot: {packet.title}")
            _publishing_event(job, agent="IMPRIMATUR", event_type="title_slot_exhausted",
                              stage="amazon_weekly_limit",
                              summary="Amazon's weekly new-title limit is spent; the book keeps its place",
                              details={"reset_at": reset.isoformat(), "title": packet.title},
                              status="waiting")
            return {"agent": "IMPRIMATUR", "phase": "waiting_for_slot",
                    "retry_after": reset.isoformat(), "reason": str(limit),
                    "content": ("Amazon's weekly new-title limit is spent. The finished book "
                                f"is queued and will be published after {reset:%d %b %H:%M} UTC.")}
        action = ApprovalStore().queue_action(
            action_type="kdp_publish",
            description=f"Publish Kindle eBook: {packet.title}",
            payload={
                "agent_id": "imprimatur", "phase": "submit", "run_dir": run_dir,
                "scribe_job_id": scribe_job_id, "title": packet.title,
                "checksums": packet.checksums,
                "price_usd": packet.price_usd,
                "ai_disclosure": {
                    "text": packet.ai_generated_text,
                    "images": packet.ai_generated_images,
                },
            },
            permission_key=f"kdp_publish:{packet.checksums['manuscript']}",
            tier="high", ttl_hours=72,
        )
        # Standing owner policy (reconfirmed 2026-10-10): KDP production is
        # autonomous through submission and ASIN reconciliation. Olympus is
        # retained as an auditable action record, not a manual upload queue.
        # Operations can fail closed instantly without a deployment by setting
        # ONE_KDP_AUTO_PUBLISH=0.
        auto_publish = os.environ.get("ONE_KDP_AUTO_PUBLISH", "1").strip().lower() \
            not in {"0", "false", "no", "off"}
        if auto_publish:
            ApprovalStore().update_status(action.id, STATUS_APPROVED)
            submit_job = enqueue_job("imprimatur", json.dumps({
                "phase": "submit", "run_dir": run_dir,
                "scribe_job_id": scribe_job_id, "title": packet.title,
                "approval_id": action.id,
            }), mode="execute", tier="fast",
                dedupe_key=f"kdp-submit:{packet.checksums['manuscript']}")
            stages.set_stage("imprimatur", stages.EXECUTING,
                             f"KDP draft ready; autonomous submission queued: {packet.title}")
            _publishing_event(
                job, agent="IMPRIMATUR", event_type="kdp_auto_submit_queued",
                stage="submission", summary="KDP draft prepared; standing policy queued submission",
                details={"approval_id": action.id, "draft": draft,
                         "submit_job_id": submit_job["id"]}, status="completed")
            return {
                "agent": "IMPRIMATUR", "phase": "auto_submit_queued",
                "approval_id": action.id, "draft": draft,
                "handed_to": {"agent": "IMPRIMATUR", "job_id": submit_job["id"]},
                "content": "KDP draft is complete; autonomous submission is queued.",
            }
        stages.set_stage("imprimatur", stages.AWAITING_UPLOAD,
                         f"Draft ready; waiting for Olympus approval: {packet.title}")
        _publishing_event(job, agent="IMPRIMATUR", event_type="kdp_draft_ready",
                          stage="approval_gate", summary="KDP draft prepared; final submission gated",
                          details={"approval_id": action.id, "draft": draft}, status="awaiting_approval")
        return {"agent": "IMPRIMATUR", "phase": "approval", "approval_id": action.id,
                "draft": draft, "content": "KDP draft is complete and queued for per-title approval."}

    if mode == "print":
        fmt = str(payload.get("format") or "paperback")
        stages.set_stage("imprimatur", stages.EXECUTING,
                         f"Setting up the {fmt} of {packet.title}")
        try:
            ready = prepare_print_draft(
                # "ebook_id" is read too: a job queued before 2026-10-14
                # carries the same ASIN under the older key.
                packet, fmt, str(payload.get("ebook_asin")
                                 or payload.get("ebook_id") or ""),
                interior_path=str(payload.get("interior_path") or ""),
                cover_path=str(payload.get("cover_path") or ""),
                headless=False)
        except TitleCreationLimitReached as limit:
            # Each format has its own weekly allowance, so a spent paperback
            # quota says nothing about hardcover and nothing about the eBook
            # that is already on sale. Wait rather than fail.
            stages.set_stage("imprimatur", stages.AWAITING_UPLOAD,
                             f"Waiting for Amazon's next {fmt} slot: {packet.title}")
            _publishing_event(job, agent="IMPRIMATUR", event_type="title_slot_exhausted",
                              stage="amazon_weekly_limit",
                              summary=f"Amazon's weekly {fmt} limit is spent; the book keeps its place",
                              details={"format": fmt, "title": packet.title}, status="waiting")
            return {"agent": "IMPRIMATUR", "phase": "waiting_for_slot", "format": fmt,
                    "reason": str(limit),
                    "content": f"The {fmt} is prepared and waiting for Amazon's next slot."}
        # An ISBN is permanent and exists nowhere else the company can look it
        # up: Amazon's free one is issued during this upload and never shown
        # again outside the title. An edition whose ISBN nobody wrote down is
        # an edition nobody can cite, so it goes on the register here, with
        # which kind it is - a KDP ISBN means this edition can never be sold
        # off Amazon, and that is the figure the distribution board reads.
        recorded = _record_edition_isbn(packet.title, fmt, ready)

        stages.set_stage("imprimatur", stages.AWAITING_UPLOAD,
                         f"{fmt.title()} draft ready for review: {packet.title}")
        # Not "awaiting_approval". Print publishing has been autonomous since
        # 2026-09-24 and there is no approval gate on this path, so nothing is
        # waiting on the Chairman - but the board said three of these were,
        # and he reasonably asked what he was meant to decide. A status is a
        # claim about who the work is sitting with, and this one was false.
        pending = ready.get("ai_detail_pending") or []
        _publishing_event(job, agent="IMPRIMATUR", event_type="print_draft_ready",
                          stage="print_format",
                          summary=(f"{fmt.title()} draft prepared; "
                                   f"AI disclosure still needs {', '.join(pending)}"
                                   if pending else f"{fmt.title()} draft prepared"),
                          details={"format": fmt, "draft": ready.get("draft_url"),
                                   "isbn": recorded, "ai_detail_pending": pending},
                          status="blocked" if pending else "completed")
        return {"agent": "IMPRIMATUR", "phase": "print_ready", "format": fmt,
                "draft": ready, "isbn": recorded,
                "content": f"{fmt.title()} draft is set up with the print interior and wrap cover."}

    approval_id = str(payload.get("approval_id") or "")
    action = ApprovalStore().get_action(approval_id) if approval_id else None
    if mode == "submit":
        if action is None or action.status != STATUS_APPROVED:
            raise PermissionError("KDP submission requires an approved, unexpired per-title A3 action")
        if action.payload.get("checksums") != packet.checksums:
            raise PermissionError("Approved KDP files no longer match the submission packet")
        stages.set_stage("imprimatur", stages.EXECUTING, f"Submitting approved title: {packet.title}")
        submitted = submit_approved(packet, approval_id, headless=False)
        stages.scribe_waits_for_kdp(run_dir, packet.title, scribe_job_id)
        poll_job = enqueue_job("imprimatur", json.dumps({
            "phase": "poll", "run_dir": run_dir, "scribe_job_id": scribe_job_id,
            "approval_id": approval_id,
        }), mode="execute", tier="fast")
        return {"agent": "IMPRIMATUR", "phase": "submitted", "submission": submitted,
                "handed_to": {"agent": "IMPRIMATUR", "job_id": poll_job["id"]},
                "content": "Approved KDP title submitted; ASIN monitoring started."}

    if mode == "poll":
        stages.set_stage("imprimatur", stages.EXECUTING, f"Checking KDP status for {packet.title}")
        status = poll_asin(packet, headless=True)
        asin = str(status.get("asin") or "")
        if asin:
            evidence = {
                "asin": asin,
                "title": packet.title,
                "status": status.get("kdp_status"),
                "source": "KDP Bookshelf",
                "marketplace": "US",
                "listing_url": f"https://www.amazon.com/dp/{asin}",
                "confirmed_by": "IMPRIMATUR",
            }
            confirmed = confirm_scribe_upload(
                scribe_job_id, evidence,
                rationale=f"IMPRIMATUR verified ASIN {asin} in the authenticated KDP Bookshelf.",
            )
            stages.clear_stage("imprimatur")
            # SCRIBE has been sitting on awaiting_upload since it handed the
            # book over. The ASIN is the proof that the wait is over, so the
            # agent that ends the wait is the one that clears the bubble -
            # otherwise the building keeps telling the Chairman a book is
            # waiting to be uploaded while it is already on sale.
            stages.clear_stage("scribe")
            # The eBook is on sale; the same book can now earn as print too.
            # Queued rather than done inline: each print format is its own
            # browser run and its own weekly quota, and a failure in one must
            # not undo the eBook that already succeeded.
            print_plan = _queue_print_formats(job, packet, run_dir, scribe_job_id, asin)
            return {"agent": "IMPRIMATUR", "phase": "complete", "asin": asin,
                    "print_formats": print_plan,
                    "kdp_status": status.get("kdp_status"), "handoff": confirmed,
                    "content": f"ASIN {asin} verified; publishing lifecycle released."}
        # Do not occupy the single ONE worker while Amazon reviews the title.
        # A daemon timer re-enqueues the lightweight check; the on-disk publish
        # state remains the recovery source if ONE is restarted between checks.
        import threading

        try:
            delay = max(300.0, float(os.environ.get("ONE_KDP_ASIN_POLL_SECONDS", "1800")))
        except ValueError:
            delay = 1800.0
        next_payload = {
            "phase": "poll", "run_dir": run_dir, "scribe_job_id": scribe_job_id,
            "approval_id": approval_id, "poll_attempt": int(payload.get("poll_attempt") or 0) + 1,
        }
        # Persist the continuation inputs before scheduling the in-process
        # timer. Worker startup can reconstruct this poll after a reboot or
        # power loss instead of leaving the title parked forever.
        write_state(
            packet,
            "AWAITING_ASIN",
            kdp_status=status.get("kdp_status", "unknown"),
            scribe_job_id=scribe_job_id,
            approval_id=approval_id,
            poll_attempt=next_payload["poll_attempt"],
            next_check_seconds=delay,
        )
        timer = threading.Timer(
            delay,
            lambda: enqueue_job("imprimatur", json.dumps(next_payload), mode="execute", tier="fast"),
        )
        timer.daemon = True
        timer.start()
        stages.set_stage("imprimatur", stages.AWAITING_WORKER,
                         f"Amazon is still processing {packet.title}; ASIN not assigned yet")
        stages.scribe_waits_for_kdp(run_dir, packet.title, scribe_job_id)
        return {"agent": "IMPRIMATUR", "phase": "awaiting_asin", "status": status,
                "next_check_seconds": delay,
                "content": "Amazon is still processing the title. ASIN monitoring remains active."}

    raise ValueError(f"Unknown IMPRIMATUR phase: {mode}")


def _run_leda(job: dict[str, Any]) -> dict[str, Any]:
    payload = _json_task(job); logic = _publishing_growth_logic()
    title = str(payload.get("title") or "(untitled)")
    stages.worker_confirms_receipt("leda", f"Preparing owned-audience plan for {title}")
    plan = logic.audience_plan(title)
    _publishing_event(job, agent="LEDA", event_type="audience_plan",
                      stage="owned_audience", summary="Consent-safe audience draft prepared",
                      details={"status": plan.get("status"), "segments": plan.get("segments")})
    growth = dict(payload); growth.update({"workflow": "publishing_portfolio",
                                          "phase": "organic_distribution", "audience": plan})
    ares_job = enqueue_job("ares", json.dumps(growth), mode="execute", tier="fast")
    stages.clear_stage("leda")
    return {"agent": "LEDA", "audience": plan,
            "handed_to": {"agent": "ARES", "job_id": ares_job["id"]},
            "content": "Reader-magnet and consent-safe segments drafted; nothing sent."}


def _run_metron(job: dict[str, Any]) -> dict[str, Any]:
    # Measurement has two halves and this is the money one: what the store
    # actually paid, read from KDP's own report. Checked first because the
    # baseline below expects a book payload and would otherwise open a
    # seven-day loop on "(untitled)".
    if KDP_PAYMENTS_SYNC_MARKER in str(job.get("task") or "").lower():
        return _kdp_payments_sync(job)

    payload = _json_task(job); logic = _publishing_growth_logic()
    stages.worker_confirms_receipt("metron", "Establishing the seven-day performance baseline")
    report = logic.measurement_baseline(str(payload.get("title") or "(untitled)"),
                                        payload.get("metrics"))
    _publishing_event(job, agent="METRON", event_type="measurement_baseline",
                      stage="measurement", summary="Seven-day measurement loop opened",
                      details=report, status="completed")
    stages.clear_stage("metron")
    return {"agent": "METRON", "measurement": report,
            "content": "Measurement loop opened; missing storefront data remains unknown, never zero."}


def _run_peitho(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 5's second worker -- starts once SCRIBE delivers a finished book.

    Hands off directly from SCRIBE, not through HERMES (explicit call,
    2026-08-26: "wo book ab dega le jake PEITHO ko instead of HERMES") --
    KDP upload has no official API and stays a manual human step (see the
    KDP submission packet SCRIBE prepares in _generate_kdp_packet), so
    HERMES's "ready for upload" report has nothing new to add to this leg;
    SCRIBE walks the book straight to PEITHO instead.

    Phase 1 of the lead-gen pipeline (2026-08-27 plan): writes 4 reel hook
    scripts from the book's own outline via _generate_peitho_reel_scripts.
    Phase 2 (actual video generation + Instagram auto-post) and Phase 3
    (YouTube Shorts upload) are separate, larger builds -- see the plan doc
    for why, and PEITHO's memory note below for what's still missing.
    """
    try:
        payload = json.loads(str(job.get("task") or "{}"))
    except json.JSONDecodeError:
        payload = {}
    title = str(payload.get("title") or "(untitled)")
    run_dir = str(payload.get("run_dir") or "")
    kdp_packet_path = str(payload.get("kdp_packet_path") or "")

    stages.worker_confirms_receipt("peitho", f"Got it -- starting on marketing for “{title}”")
    stages.set_stage("peitho", stages.EXECUTING, f"Writing reel hook scripts for “{title}”")

    reel_scripts = _generate_peitho_reel_scripts(run_dir, title) if run_dir else {"generated": False, "note": "no run_dir", "angles": []}
    lifecycle_plan = payload.get("post_upload_lifecycle") or {}
    lifecycle = _publishing_lifecycle_module()
    launch_workspace = (
        lifecycle.materialize_launch_workspace(
            run_dir, str((payload.get("upload_evidence") or {}).get("asin") or job["id"]),
            title, lifecycle_plan, reel_scripts)
        if lifecycle is not None and run_dir else
        {"root": "", "files": {}, "external_actions_executed": 0}
    )

    generated_count = sum(1 for a in reel_scripts.get("angles", []) if a.get("generated"))
    hooks_summary = "\n".join(
        f"  {a['angle']}. {a.get('hook', '(failed)')[:100]}" for a in reel_scripts.get("angles", [])
    )
    remembered = memory.remember(
        agent="PEITHO", floor_id="5", floor_name="Book Publishing (KDP)",
        kind="Marketing Intake",
        body=(
            f"Received the finished book from SCRIBE.\n\n"
            f"Title: {title}\nRun folder: {run_dir}\n"
            f"KDP submission packet: {kdp_packet_path or '(not generated)'}\n\n"
            f"Wrote {generated_count}/4 reel hook scripts to "
            f"{reel_scripts.get('dir') or '(not generated)'}:\n{hooks_summary}\n\n"
            f"Governed post-upload workspace: {launch_workspace.get('root') or '(not generated)'}\n"
            "Creative, audience, distribution and measurement artifacts are "
            "drafted there. External posting, sending and spend remain disabled."
        ),
        task=f"book delivered: {title}",
        tags=["kdp", "publishing", "marketing", "reel-scripts"],
    )

    leda_job = enqueue_job(
        "leda", json.dumps({**payload, "workflow": "publishing_portfolio",
                            "phase": "owned_audience", "reel_scripts": reel_scripts,
                            "launch_workspace": launch_workspace}),
        mode="execute", tier="fast",
    )
    _publishing_event(job, agent="PEITHO", event_type="creative_bundle",
                      stage="launch_assets", summary=f"Generated {generated_count}/4 reel hook scripts",
                      details={"generated": generated_count, "artifact_dir": reel_scripts.get("dir"),
                               "leda_job_id": leda_job["id"]})
    stages.clear_stage("peitho")

    return {
        "agent": "PEITHO",
        "mode": job.get("mode"),
        "title": title,
        "run_dir": run_dir,
        "kdp_packet_path": kdp_packet_path,
        "reel_scripts": reel_scripts,
        "launch_workspace": launch_workspace,
        "content": f"Wrote {generated_count}/4 reel hook scripts for “{title}”.",
        "vault_note": remembered.get("path"),
        "handed_to": {"agent": "LEDA", "job_id": leda_job["id"]},
        "note": "Review workspace prepared. External generation/posting needs configured adapters and explicit approval.",
    }


_PEITHO_ANGLE_ENTRY_POINTS = [
    "Enter through the story's opening inciting incident -- ground it in the "
    "first 1-3 beats of the outline below, the moment that kicks everything off.",
    "Enter through a mid-story revelation or twist -- pull from the middle "
    "beats of the outline, a moment where something the reader thought was "
    "true turns out not to be.",
    "Enter through a specific supporting character's discovery or point of "
    "view -- find a beat where someone OTHER than the protagonist learns "
    "something that changes the stakes.",
    "Enter through how far this goes -- pull from the outline's final beats "
    "(without spelling out the actual ending) to frame 'here's what she's up "
    "against by the end', as a tension-raiser, not a spoiler.",
]


# Same folder every existing chatgptLogin-using LAO process (KDP Book
# Factory, ImagineIndia Reel, Daily LinkedIn Authority Post) already runs
# under -- confirmed live via GET /processes 2026-08-29. get_credential
# resolves assetName against whatever folder_id the job carries, so this
# has to match or "chatgptLogin" won't be found.
_PEITHO_LAO_FOLDER_ID = "446427d7-5722-4d59-a487-8de321325cbc"


def _peitho_angle_prompt(title: str, genre: str, tropes: str, premise: str, outline_text: str, entry_point: str) -> str:
    return (
        f"You are a viral short-form video scriptwriter -- the kind who "
        f"writes for creators with millions of followers, not a "
        f"copywriter. Write a hook script to sell the finished book "
        f"\"{title}\", genre {genre}, tropes {tropes}.\n\n"
        f"Premise: {premise}\n\nFull chapter outline:\n{outline_text}\n\n"
        f"For THIS script: {entry_point}\n\n"
        "STYLE -- this is the part that actually matters. Every reel that "
        "works sounds like someone talking fast and urgent, not a book "
        "blurb read aloud:\n"
        "- Short fragments. Not flowing sentences with commas stacked up. "
        "Each beat is its own punch, one breath long.\n"
        "- Second person or direct address where it lands harder: \"She "
        "trusted him with everything.\" beats \"Nora Kessler had spent "
        "three years confessing her deepest secrets to Dr. Voss.\"\n"
        "- Open with a stopping-power line, not a scene-setter. Compare: "
        "'He wasn't treating her. He was writing about her.' vs 'Dr. Voss "
        "was her confidant for years.' The first one stops a thumb "
        "mid-scroll. The second one is a synopsis.\n"
        "- Cut fast between beats. No connective tissue like 'and then' "
        "or 'as a result' -- just the next punch.\n"
        "- Read every line out loud in your head before writing the next "
        "one: if it sounds like it belongs on the back of the book "
        "instead of spoken over a jump-cut, rewrite it.\n\n"
        "Ground every beat in specific named characters/events from the "
        "outline above -- never generic teaser language. The whole point "
        "is a viewer feels they NEED to know what happens next and only "
        "the book tells them. Never reveal how the story actually ends.\n\n"
        "Reply in exactly this shape:\n"
        "HOOK:\n<one line, the first 1-2 seconds on screen -- a "
        "stopping-power line per the style notes above, not a "
        "scene-setter>\n"
        "BEATS:\n<4-6 short fragment lines, one beat per line, no "
        "connective tissue, building tension in order>\n"
        "CLIFFHANGER:\n<one line, the cut -- ends mid-tension, not "
        "resolved>\n"
        "CAPTION:\n<1-2 sentence social caption, same punchy register as "
        "the hook, not a blurb>\n"
        "HASHTAGS:\n<7 hashtags, one per line, no # repeated across "
        "generic filler like #book #reading -- specific to this story's "
        "genre/tropes>\n"
        "CTA:\n<one line telling the viewer how to find the book>"
    )


def _run_peitho_lao_draft(angle_prompts: list[str], *, expected_markers: list[str] | None = None,
                          timeout_ms: int = 120000) -> tuple[dict[str, str], str]:
    """Run all 4 angle prompts through LAO's own, already-logged-in ChatGPT
    session -- reuses the exact `chatgptLogin` credential and production-
    hardened `ask_chatgpt` action ImagineIndia and KDP Book Factory already
    depend on daily, via LAO Studio's studio/run-draft endpoint (a raw step
    list dispatched as a one-off job, no package/workflow.yaml authoring
    needed). Returns ({angle_1: text, ...}, failure_note); failure_note is
    "" on success.

    Added 2026-08-29, replacing an earlier draft of this feature that stood
    up a SECOND, separate ChatGPT browser profile inside ONE itself -- the
    Chairman's own correction ("jo humara LAO wala hai usi ko use karo"):
    LAO's robot already keeps a persistent, logged-in Chrome session for
    exactly this, so there was nothing to duplicate.
    """
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool

    steps: list[dict[str, Any]] = [
        {"action": "open_browser"},
        {"action": "get_credential", "args": {"assetName": "chatgptLogin", "as": "credential"}},
        {"action": "chatgpt_login_with_credential", "args": {"credential": "{{credential}}"}},
    ]
    for i, prompt in enumerate(angle_prompts, start=1):
        if i > 1:
            # A fresh chat per angle -- otherwise angle 2-4 would be written
            # with angle 1's beats still in the same conversation's context.
            steps.append({"action": "navigate", "args": {"url": "https://chatgpt.com/"}})
        ask_args: dict[str, Any] = {"prompt": prompt, "timeout_ms": timeout_ms, "as": f"angle_{i}"}
        if expected_markers:
            # Without markers ask_chatgpt returns the first assistant text it
            # sees, which for a long reply is the reply mid-stream.
            ask_args["expected_markers"] = list(expected_markers)
        steps.append({"action": "ask_chatgpt", "args": ask_args})

    tool = LaoOrchestratorTool()
    started = tool.execute(
        action="run_draft", steps=steps,
        draft_name="peitho-reel-hooks", folder_id=_PEITHO_LAO_FOLDER_ID,
    )
    if not started.success:
        return {}, f"LAO draft dispatch failed: {started.content}"
    try:
        start_payload = json.loads(started.content)
    except json.JSONDecodeError:
        return {}, f"LAO draft dispatch returned unparseable response: {started.content[:300]}"
    job_id = ((start_payload.get("job") or {}).get("id")) or ""
    if not job_id:
        return {}, f"LAO draft dispatch returned no job id: {started.content[:300]}"

    poll_seconds = 15.0
    max_wait_seconds = 900.0  # login + 4 chat turns; generous but not open-ended
    deadline = time.time() + max_wait_seconds
    terminal = {"Successful", "Failed", "Stopped", "Cancelled", "Faulted", "Retried"}
    status = "Pending"
    while time.time() < deadline:
        time.sleep(poll_seconds)
        probe = tool.execute(action="status", job_id=job_id, process_name="")
        if not probe.success:
            continue
        try:
            probe_payload = json.loads(probe.content)
        except json.JSONDecodeError:
            continue
        job = probe_payload.get("job") or {}
        status = str(job.get("status") or status)
        if status in terminal:
            if status != "Successful":
                return {}, f"LAO draft job {job_id} ended as {status}"
            return dict(job.get("output_result") or {}), ""
    return {}, f"LAO draft job {job_id} did not finish within {max_wait_seconds:.0f}s (last status: {status})"


def _generate_peitho_reel_scripts(run_dir: str, title: str) -> dict[str, Any]:
    """Four short-form video hook scripts, cut from the finished book's own
    outline -- one ChatGPT call per angle, not one call for all four.

    Confirmed live 2026-08-27 on the KDP packet's own hybrid pipeline: a
    single response asked to fill ~20 marked sections at once starts
    literally echoing the placeholder syntax back instead of generating
    real content for most of them. Four small, focused calls (one angle
    each) don't hit that failure mode, and each angle gets its own
    structural entry point (see _PEITHO_ANGLE_ENTRY_POINTS) so the four
    don't all retread the same beat.

    Reads outline.json (chapter-by-chapter beats -- already written by
    SCRIBE's book-writing stage) rather than the full ~13-14k word
    manuscript: the beats are exactly what a hook script needs, and keep
    every prompt small. No video/image generation or posting happens here
    -- see PEITHO's plan doc for why that's Phase 2, a separate build.

    Generation itself runs through LAO's own ChatGPT session (see
    _run_peitho_lao_draft) -- the Chairman compared Claude, the OpenAI API,
    and ChatGPT-the-product for this exact job and asked specifically for
    the product, reached through LAO's existing credential rather than a
    new login of our own. No direct-API fallback: PEITHO holds no
    OPENAI_API_KEY/ANTHROPIC_API_KEY of its own (the vault rule enforced in
    one-company/floors/_registry/validate.py), so if the LAO job fails this
    stage fails loud with the real reason instead of quietly reaching past
    that boundary.
    """
    outline_path = Path(run_dir) / "outline.json"
    try:
        outline_data = json.loads(outline_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"generated": False, "note": f"Could not read outline.json: {exc}", "angles": []}

    genre = outline_data.get("genre", "")
    tropes = outline_data.get("tropes", "")
    premise = outline_data.get("premise", "")
    outline_text = outline_data.get("outline", "")

    scripts_dir = Path(run_dir) / "reel_scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    angle_prompts = [
        _peitho_angle_prompt(title, genre, tropes, premise, outline_text, entry_point)
        for entry_point in _PEITHO_ANGLE_ENTRY_POINTS
    ]

    lao_results, lao_note = _run_peitho_lao_draft(angle_prompts)

    # No direct-API fallback here on purpose: the vault rule this codebase
    # enforces elsewhere (one-company/floors/_registry/validate.py -- "no
    # agent declares SECRET data access, the credential vault is read by no
    # agent") means PEITHO itself must never hold an OPENAI_API_KEY/
    # ANTHROPIC_API_KEY read of its own, direct-env-read fallback included.
    # LAO's own get_credential/resolve_asset step is the one sanctioned
    # bridge pattern (same shape as SCRIBE's LAO token) -- if that job
    # fails, this stage fails loud with the real reason instead of quietly
    # reaching for a secret PEITHO was never granted.
    angles: list[dict[str, Any]] = []
    for i, prompt in enumerate(angle_prompts, start=1):
        content = str(lao_results.get(f"angle_{i}") or "").strip()
        note = lao_note
        if not content:
            angles.append({"angle": i, "generated": False, "note": note, "path": ""})
            continue

        def extract(tag: str) -> str:
            m = re.search(rf"{tag}:\s*\n?(.*?)(?=\n[A-Z]+:|\Z)", content, re.S)
            return m.group(1).strip() if m else ""

        angle_path = scripts_dir / f"angle-{i}.md"
        angle_path.write_text(
            f"# Reel Hook — Angle {i} — {title}\n\n"
            f"**Hook:** {extract('HOOK')}\n\n"
            f"**Beats:**\n{extract('BEATS')}\n\n"
            f"**Cliffhanger:** {extract('CLIFFHANGER')}\n\n"
            f"**Caption:** {extract('CAPTION')}\n\n"
            f"**Hashtags:**\n{extract('HASHTAGS')}\n\n"
            f"**CTA:** {extract('CTA')}\n",
            encoding="utf-8",
        )
        angles.append({"angle": i, "generated": True, "path": str(angle_path), "hook": extract("HOOK")})

    return {"generated": any(a.get("generated") for a in angles), "angles": angles, "dir": str(scripts_dir)}


_ANGLE_CONSTRAINT = re.compile(
    r"\s*(?:,|--|—)?\s*(?:while |whilst )?"
    r"(?:without (?:naming|mentioning|referencing)|naming no|mentioning no)\b[^.]*",
    re.IGNORECASE,
)
# Phrases that only ever come from our own brief. If one reaches a shop page a
# reader is being shown the instructions we wrote for the model.
_INTERNAL_COPY_MARKERS = (
    "kdp", "amazon", "without naming", "naming no", "generic advice",
    "this brief", "the brief", "the prompt", "the angle", "target reader",
    "commercial risk", "back-cover", "royalty", "browse-category",
)


def _reader_facing(text: str) -> str:
    """An angle written for the floor, rewritten as something a reader may see.

    HERMES is told the angle must name no real organisation, and the model
    obligingly writes that instruction into the angle itself -- "...into a
    competitive moat without naming specific nations or governments". Carried
    verbatim into a shop description (2026-09-24, live) it reads as a note to
    ourselves. Cut the clause; keep the hook.
    """
    cleaned = _ANGLE_CONSTRAINT.sub("", str(text or "")).strip().rstrip(",;-— ")
    return (cleaned + ".") if cleaned and not cleaned.endswith(".") else cleaned


def _strip_internal_copy(description: str) -> tuple[str, list[str]]:
    """Drop sentences that talk about our own process instead of the book.

    Returns the cleaned text and what was removed, so a caller can say plainly
    that it intervened rather than quietly shipping different words.
    """
    kept: list[str] = []
    dropped: list[str] = []
    for block in str(description or "").split("\n"):
        if not block.strip():
            kept.append(block)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", block)
        good = [s for s in sentences
                if not any(m in s.lower() for m in _INTERNAL_COPY_MARKERS)]
        dropped.extend(s.strip() for s in sentences if s not in good and s.strip())
        if good:
            kept.append(" ".join(good).strip())
    return ("\n").join(kept).strip(), dropped


def _generate_kdp_packet(title: str, kdp_mode: str, region: str, angle: str, run_dir: str) -> dict[str, Any]:
    """Everything a human needs to paste into KDP's own wizard by hand.

    Amazon has no API for KDP uploads/metadata (confirmed 2026-08-26 --
    only Ads/Attribution APIs exist, and SP-API explicitly excludes KDP
    data). The only way to fully automate the real submit is a headless
    browser riding a live authenticated session to dodge Amazon's bot
    detection -- a call the Chairman made explicitly not to build, even
    with account-loss risk accepted, because it is standing automation of
    a real form-submission/account action and a detection-evasion pattern,
    neither of which per-instance authorization unlocks. So this is as far
    as automation goes: SCRIBE prepares every field a human would otherwise
    have to write from scratch, and a human still does the clicking.
    """
    # Metadata drafting is synthesis over an already-finished, local book. It
    # does not justify a paid provider call; use the same local-first policy as
    # HERMES research and fail closed if no approved local model is available.
    packet, note = _research_synthesis(
        "You are SCRIBE, producing the exact fields a human will paste into "
        "Amazon KDP's Kindle eBook setup wizard for a finished manuscript. "
        "There is no KDP API -- this packet is what gets typed in by hand.\n\n"
        f"Title: {title}\nMode: {kdp_mode}\nRegion: {region}\n"
        # The angle carries the floor own constraint clause; a reader must
        # never see it, so the model is not shown it either.
        f"What the book promises the reader: {_reader_facing(angle)}\n\n"
        "Every field here is read by a shopper deciding whether to buy. Write "
        "only about the book and what the reader gets. Never mention this "
        "brief, the instructions, the platform, the listing process, pricing "
        "mechanics, or any constraint we work under. Reply in exactly this "
        "shape:\n"
        "SUBTITLE: <or NONE>\n"
        "DESCRIPTION:\n<150-300 word back-cover description in KDP's rich-"
        "text style -- short paragraphs, one bolded hook line, plain text, "
        "no markdown asterisks>\n"
        "CATEGORIES:\n<3 real Amazon Kindle Store browse-category paths this "
        "book fits, most-specific first, one per line>\n"
        "KEYWORDS:\n<7 search-term phrases, one per line, each under 50 "
        "characters, no repetition of words already in the title>\n"
        "PRICE_USD: <a single list price, matching the current 70%-royalty "
        "band $2.99-$12.99 on Amazon.com, calibrated to what comparable "
        "titles in this genre/region actually sell at>\n"
        "ROYALTY_PLAN: 70 | 35\n",
        evidence={"eligible": [], "catalog_evidence": [], "counts": {},
                  "policy": "Do not invent live sales or competitor-price claims."},
    )
    if not packet:
        return {"generated": False, "note": note, "path": ""}

    # Last line of defence. The wording above tells the model to keep our
    # process out of the copy; this makes sure of it, because the description
    # is pasted onto a public shop page and nobody reads it again first.
    removed: list[str] = []
    match = re.search(r"(?ms)^DESCRIPTION:\s*\n(.*?)(?=^[A-Z_]+:)", packet)
    if match:
        cleaned, removed = _strip_internal_copy(match.group(1))
        if removed:
            packet = (packet[:match.start(1)] + cleaned
                      + ("\n" * 2) + packet[match.end(1):])

    # Written straight into the book's own run_dir (next to book.md,
    # cover.jpg, KDP_Book_Professional.docx, ...), not ONE's own
    # agent_outputs -- confirmed live 2026-08-27: the Chairman does the
    # actual upload by hand from that folder, and a packet saved anywhere
    # else is a packet he can't find when he goes looking for it.
    packet_path = Path(run_dir) / "kdp_submission_packet.md"
    packet_path.write_text(
        f"# KDP Submission Packet — {title}\n\n"
        "Paste these fields into kdp.amazon.com's Kindle eBook wizard by "
        "hand -- there is no KDP API and the actual submit stays a manual "
        "step.\n\n"
        f"{packet}\n",
        encoding="utf-8",
    )
    return {"generated": True, "content": packet, "path": str(packet_path),
            "internal_copy_removed": removed}


def _docx_embeds(docx_path: Path, image_path: Path) -> bool:
    """Is this exact image actually inside the .docx?

    A cover refresh that reports success while the deliverable still carries
    the previous cover is the failure worth catching here, and file timestamps
    do not catch it -- the DOCX is rewritten on every run whether or not the
    new art made it in. Comparing bytes is the only answer that means anything.
    """
    import hashlib
    import zipfile

    try:
        wanted = hashlib.md5(image_path.read_bytes()).hexdigest()
        with zipfile.ZipFile(docx_path) as bundle:
            return any(
                hashlib.md5(bundle.read(name)).hexdigest() == wanted
                for name in bundle.namelist() if name.startswith("word/media/")
            )
    except Exception:  # noqa: BLE001 - unreadable means "cannot confirm", not "yes"
        return False


def _cover_jpeg_from_art(visual: Path) -> str:
    """Make the uploadable cover.jpg out of the art the model produced.

    This used to be the overlay step's job, and the overlay paints our own
    title and author over the art unless it decides the art already has
    typography. It decides that by counting sharp luminance swings, which is a
    fine proxy for text on a photograph and the wrong one here: on the first
    house-style cover it correctly left the title alone and then painted the
    full 86-character factory title across the benefit list, and stamped
    VINEET PANDEY over the author bar the model had already set, because that
    bar is dark yellow on dark navy and barely swings at all. The result read
    twice and passed the reading test, since the title really was on it.

    A cover we asked to be finished does not want anything painted on it, so
    nothing is.
    """
    from PIL import Image

    art = visual / "cover_raw.png"
    if not art.is_file():
        art = visual / "cover.png"
    if not art.is_file():
        raise FileNotFoundError(f"No cover art to convert in {visual}")
    out = visual / "cover.jpg"
    with Image.open(art) as img:
        img = img.convert("RGB")
        # KDP's own recommendation, and what every cover in this catalogue is.
        if img.size != (1600, 2560):
            img = img.resize((1600, 2560), Image.LANCZOS)
        img.save(out, "JPEG", quality=92, optimize=True, progressive=False)
    return str(out)


def _cover_verdict(check: dict[str, Any]) -> str:
    """One line about whether the cover says what the book is called."""
    if not check:
        return "not checked"
    if check.get("ok") is None:
        return f"could not be checked ({check.get('error', 'unknown')})"
    share = check.get("title_coverage")
    readable = f"{float(share):.0%} of the title readable" if share is not None else "unknown"
    return ("reads correctly, " if check.get("ok") else "FAILED, ") + readable


def _cover_packaging(run_dir: Path, brief: dict[str, Any]) -> dict[str, Any]:
    """What the commission decided about how this book should be packaged.

    HERMES picks a title, a thumbnail promise, a lead magnet and a series, and
    none of it reached the cover: the brief handed to the factory carried only
    the angle, so the factory invented its own title and drew a scene from
    chapter one. Read back from the commission brief where there is one, and
    from the book's own metadata otherwise.
    """
    out: dict[str, Any] = {"title": "", "subtitle": "", "author": "Vineet Pandey",
                           "thumbnail_promise": "", "lead_magnet": "", "series": "",
                           "keywords": []}
    meta = run_dir / "kdp_metadata.json"
    if meta.is_file():
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
            out["title"] = str(m.get("title") or "")
            out["subtitle"] = str(m.get("subtitle") or "")
            out["author"] = str(m.get("author") or out["author"])
            out["keywords"] = [str(k) for k in (m.get("keywords") or [])][:8]
        except (OSError, json.JSONDecodeError):
            pass
    path = str(brief.get("brief_path") or "")
    if not path and brief.get("origin_job"):
        path = str(_home() / "agent_outputs" / f"{brief['origin_job']}.md")
    if path and Path(path).is_file():
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            text = ""
        for key, field in (("TITLE", "commissioned_title"),
                           ("THUMBNAIL_PROMISE", "thumbnail_promise"),
                           ("LEAD_MAGNET", "lead_magnet"),
                           ("SERIES", "series")):
            found = re.search(rf"^{key}:\s*(.+)$", text, re.MULTILINE)
            if found:
                out[field] = found.group(1).strip()
    # The commissioned title is the short one the packaging was scored on; the
    # factory's is the long one it wrote for itself.
    short = str(out.pop("commissioned_title", "") or "")
    if short and len(short) < len(out["title"] or short):
        out["cover_title"] = short
    out.setdefault("cover_title", out["title"])
    return out


def _scribe_cover_refresh(job: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    """Regenerate an existing book's cover with the current pipeline.

    Runs an explicit, minimal step list against ONE named run_dir. It cannot
    write a book: no step in it authors anything.

    The first version of this tried to be clever and reuse the whole KDP
    process, by clearing a gate file so LAO's resume would pick the book up.
    That failed badly on 2026-08-30. _find_resumable_kdp_run skips any run
    carrying lao_result.json -- i.e. any run that FINISHED -- so a completed
    book can never be resumed no matter what is deleted from it. Resume found
    nothing, and the process did the only other thing it knows how to do:
    started a brand new book on a fresh topic. It was nine chapters deep before
    it was stopped. A refresh whose failure mode is "writes an entire different
    book" is not a refresh, so the process is not used at all here.

    The old prompt and art files are renamed, never deleted, so a worse
    regeneration can be compared against what shipped.
    """
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool

    run_dir = Path(str(brief.get("run_dir") or "").strip())
    if not run_dir.exists():
        stages.clear_stage("scribe")
        raise RuntimeError(f"cover_refresh needs an existing run_dir; got {run_dir!r}")

    title = str(brief.get("title") or "")
    if not title:
        meta = run_dir / "kdp_metadata.json"
        if meta.exists():
            try:
                title = str(json.loads(meta.read_text(encoding="utf-8")).get("title") or "")
            except Exception:  # noqa: BLE001
                title = ""
    label = title or run_dir.name

    stages.worker_confirms_receipt("scribe", f"Redoing the cover for “{label[:80]}”")
    stages.set_stage("scribe", stages.EXECUTING, f"Clearing the old cover prompts for “{label[:70]}”")

    visual = run_dir / "visual_assets"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    moved: list[str] = []
    # cover_raw.png goes too: the compositor reads it in preference to
    # cover.png, so leaving the old raw art in place would quietly compose the
    # new type over the OLD picture and look like the refresh had run.
    for name in ("banner_prompt.txt", "banner_prompt.md", "cover_prompt.txt",
                 "cover_prompt.md", "cover_raw.png"):
        src = visual / name
        if src.exists():
            src.rename(visual / f"{name}.{stamp}.bak")
            moved.append(name)

    subtitle = ""
    meta_file = run_dir / "kdp_metadata.json"
    author = "Vineet Pandey"
    if meta_file.exists():
        try:
            m = json.loads(meta_file.read_text(encoding="utf-8"))
            subtitle = str(m.get("subtitle") or "")
            author = str(m.get("author") or author)
        except Exception:  # noqa: BLE001
            pass

    # The cover brief is written here, not by the factory. Its own
    # refresh_kdp_cover_prompts writes a scene - a character in silhouette
    # somewhere atmospheric - and the workflow then forbids the image model
    # any lettering at all, so every cover came back a dark photograph with a
    # long title painted over it. This asks for the finished cover the
    # catalogue's sellers actually have, built from what the commission
    # already decided and threw away.
    from openjarvis.tools import kdp_cover_brief, kdp_cover_qc

    packaging = _cover_packaging(run_dir, brief)
    cover_title = packaging.get("cover_title") or title or label
    (visual / "cover_prompt.txt").write_text(
        kdp_cover_brief.cover_prompt(
            title=cover_title, subtitle=packaging["subtitle"],
            author=packaging["author"],
            thumbnail_promise=packaging["thumbnail_promise"],
            lead_magnet=packaging["lead_magnet"], series=packaging["series"],
            keywords=packaging["keywords"]),
        encoding="utf-8")

    cover_png = str(visual / "cover.png")
    steps = [
        {"action": "open_browser"},
        {"action": "get_credential", "args": {"assetName": "chatgptLogin", "as": "chatgpt_credential"}},
        {"action": "chatgpt_login_with_credential", "args": {"credential": "{{chatgpt_credential}}"}},
        {"action": "read_local_file",
         "args": {"path": str(visual / "cover_prompt.txt"), "as": "cover_prompt_text"}},
        {"action": "generate_and_download_chatgpt_image",
         "args": {"prompt": "Generate an image using this exact prompt. Do not ask "
                            "follow-up questions. Prompt: {{cover_prompt_text}}",
                  "filename": cover_png, "always_nudge_fresh_image": True,
                  # Off deliberately: that flag bans lettering, and the whole
                  # point now is that the model sets the type. Portrait and
                  # the 1600x2560 proportion are stated in the brief itself,
                  # which is where the rest of the design lives too.
                  "cover_constraints": False}},

        # The book file embeds the cover, so regenerating the image alone
        # leaves the DOCX still carrying the old one. The production workflow
        # runs this immediately after the overlay step for exactly that
        # reason; the first version of this draft stopped one step short and
        # produced a new cover that existed nowhere in the actual deliverable.
    ]

    tool = LaoOrchestratorTool()
    stages.set_stage("scribe", stages.EXECUTING, f"LAO is regenerating the cover for “{label[:70]}”")

    started = tool.execute(action="run_draft", steps=steps, draft_name="scribe-cover-refresh",
                           folder_id=_PEITHO_LAO_FOLDER_ID)
    if not started.success:
        stages.clear_stage("scribe")
        raise RuntimeError(f"LAO refused the cover refresh: {started.content}")
    try:
        lao_job_id = ((json.loads(started.content).get("job") or {}).get("id")) or ""
    except json.JSONDecodeError:
        lao_job_id = ""
    if lao_job_id:
        job_recovery.attach(_connect, job["id"], lao_job_id)
    process_name = ""

    poll_seconds = float(os.environ.get("ONE_LAO_POLL_SECONDS", "30"))
    deadline = time.time() + float(os.environ.get("ONE_COVER_REFRESH_MAX_WAIT", "3600"))
    terminal = {"Successful", "Failed", "Stopped", "Cancelled", "Faulted"}
    status = "Pending"
    while time.time() < deadline:
        time.sleep(poll_seconds)
        job_recovery.heartbeat(_connect, job["id"])
        probe = tool.execute(action="status", process_name=process_name,
                             scope="production", job_id=lao_job_id)
        if not probe.success:
            continue
        try:
            status = str((json.loads(probe.content).get("job") or {}).get("status") or status)
        except json.JSONDecodeError:
            continue
        stages.set_stage("scribe", stages.EXECUTING,
                         f"Cover for “{label[:60]}” · LAO {status}", lao_job=lao_job_id)
        if status in terminal:
            break

    produced = {
        name: (visual / name).exists()
        for name in ("cover_prompt.txt", "cover_raw.png", "cover.jpg", "cover_wrap_print.pdf")
    }
    # The model sets the type now, so the spelling is its to get wrong, and
    # nothing downstream would notice: the file uploads either way. Read the
    # cover back with the OCR Windows already has and say what it says.
    cover_check: dict[str, Any] = {}
    cover_file = Path(_cover_jpeg_from_art(visual))
    try:
        cover_check = kdp_cover_qc.check_cover(
            cover_file, title=cover_title, author=packaging["author"],
            # The long title the factory wrote for itself. If its words turn
            # up on the cover as well, something painted over the art.
            forbid=[t for t in (packaging.get("title"), title)
                    if t and t != cover_title]).to_dict()
    except Exception as exc:  # noqa: BLE001 - a failed reader is not a failed cover
        cover_check = {"ok": None, "error": f"{type(exc).__name__}: {exc}"[:200]}
    if status != "Successful":
        stages.clear_stage("scribe")
        raise RuntimeError(f"LAO cover refresh ended as {status} (job {lao_job_id[:8]})")
    # A cover whose own title cannot be read off it is not a finished cover,
    # whatever LAO says about the job. The previous prompt and art are beside
    # it with a timestamp, so this refuses to call the refresh done rather
    # than losing anything - and it refuses BEFORE the book is rebuilt around
    # it, which is the whole reason the render is a second run.
    if cover_check.get("ok") is False:
        stages.clear_stage("scribe")
        raise RuntimeError(
            "The new cover did not pass its own reading test: "
            + "; ".join(cover_check.get("notes") or ["unreadable"])
            + f" Windows read: {str(cover_check.get('ocr_text') or '')[:200]!r}")

    # The book file embeds the cover, so the DOCX has to be rebuilt after it -
    # and only after it passes. This used to be the last step of the same run,
    # which meant the book was re-rendered around whatever came back.
    stages.set_stage("scribe", stages.EXECUTING,
                     f"Rebuilding the book around the new cover: “{label[:60]}”")
    render = tool.execute(action="run_draft",
                          steps=[{"action": "render_kdp_docx",
                                  "args": {"run_dir": str(run_dir), "as": "final_docx"}}],
                          draft_name="scribe-cover-rerender",
                          folder_id=_PEITHO_LAO_FOLDER_ID)
    render_status = "not started"
    if render.success:
        try:
            render_job = ((json.loads(render.content).get("job") or {}).get("id")) or ""
        except json.JSONDecodeError:
            render_job = ""
        render_deadline = time.time() + 1800
        render_status = "Pending"
        while render_job and time.time() < render_deadline:
            time.sleep(poll_seconds)
            job_recovery.heartbeat(_connect, job["id"])
            probe = tool.execute(action="status", process_name="",
                                 scope="production", job_id=render_job)
            if not probe.success:
                continue
            try:
                render_status = str((json.loads(probe.content).get("job") or {}).get("status")
                                    or render_status)
            except json.JSONDecodeError:
                continue
            if render_status in terminal:
                break
    else:
        render_status = f"refused: {render.content[:120]}"

    # Checked by content, not by existence: the DOCX is always there, and the
    # question that matters is whether it carries the cover we just made.
    produced["docx_has_new_cover"] = _docx_embeds(run_dir / "KDP_Book_Professional.docx",
                                                  visual / "cover.jpg")
    stages.clear_stage("scribe")

    memory.remember(
        agent="SCRIBE", floor_id="5", floor_name="Book Publishing (KDP)",
        kind="Cover Refresh",
        body=(f"Regenerated the cover for “{label}”.\n\n"
              f"- LAO job: `{lao_job_id}` — {status}\n"
              f"- Run folder: `{run_dir}`\n"
              f"- Prompts rotated out: {', '.join(moved) or 'none'}\n"
              f"- Produced: {', '.join(k for k, v in produced.items() if v) or 'nothing'}\n"
              f"- Cover text: {_cover_verdict(cover_check)}\n\n"
              "Front cover and paperback wrap are rebuilt; re-uploading them to "
              "KDP is still a manual step."),
        task=f"cover refresh / {label}",
        tags=["kdp", "publishing", "cover"],
    )

    return {
        "agent": "SCRIBE",
        "mode": "cover_refresh",
        "lao_job": lao_job_id,
        "lao_status": status,
        "run_dir": str(run_dir),
        "title": label,
        "rotated_out": moved,
        "produced": produced,
        "cover_title": cover_title,
        "cover_check": cover_check,
        "rerender_status": render_status,
        "requires_human": "Re-upload the new cover to KDP; the listing is still in review.",
    }


def _lao_failure_reason(lao_job_id: str, last_poll: dict[str, Any] | None = None) -> str:
    """Why LAO stopped, in LAO's own words.

    Asked of LAO directly because the poll response carries a status and not
    a cause. Without this the floor reports "Failed" and the actual sentence -
    on 2026-10-06, a Claude Code executable pinned to a version Windows had
    already updated away - is only reachable by logging into LAO by hand.

    Never raises. A reason that cannot be fetched must not turn a failed book
    into a crashed agent on top of it.
    """
    reason = str(((last_poll or {}).get("job") or {}).get("error_message") or "").strip()
    if reason:
        return reason[:400]
    if not lao_job_id:
        return "LAO gave no reason and no job id to ask about"
    try:
        from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool

        result = LaoOrchestratorTool().execute(action="status", job_id=lao_job_id)
        payload = getattr(result, "data", None) or getattr(result, "content", None) or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        job = (payload or {}).get("job") or payload or {}
        reason = str(job.get("error_message") or "").strip()
    except Exception as exc:  # noqa: BLE001 - diagnosing a failure, not adding one
        return f"LAO gave no reason and could not be asked ({type(exc).__name__})"
    return reason[:400] if reason else "LAO recorded no reason for the failure"


def _run_scribe(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 5 worker - runs LAO's KDP factory and waits for the book.

    This is the only agent that blocks on an external multi-hour job, so it
    polls LAO rather than fire-and-forgetting: the floor's whole point is that
    the worker is genuinely busy for as long as the book takes.
    """
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool
    from openjarvis.one_agents import lao_healer

    try:
        brief = json.loads(str(job.get("task") or "{}"))
    except json.JSONDecodeError:
        brief = {}
    kdp_mode = brief.get("kdp_mode") or "auto"
    region = brief.get("region") or "global"
    angle = str(brief.get("angle") or "").strip()
    existing_run_dir = str(brief.get("existing_run_dir") or "").strip()

    # Re-run only the cover for a book that already exists, rather than writing
    # a new one. Added 2026-08-30: the cover pipeline gained a real composition
    # layer, a paperback full-wrap, and new art-composition instructions, and a
    # book already sitting in Amazon's review queue needed those applied to it.
    # That is SCRIBE's job -- it owns this floor's production work -- not
    # something to run by hand from a chat session.
    if str(job.get("mode") or "").strip().lower() == "cover_refresh" or brief.get("cover_refresh"):
        return _scribe_cover_refresh(job, brief)

    stages.worker_confirms_receipt(
        "scribe",
        f"Got it — {angle[:110]}" if angle else "Taking the brief from HERMES",
    )

    tool = LaoOrchestratorTool()
    process_name = os.environ.get("LAO_KDP_PROCESS", KDP_PROCESS_NAME)

    # dryRun stays True: it still produces the full manuscript + images, and
    # KDP upload is a manual human gate that must never be automated.
    # LAO's workflow.yaml unconditionally runs its own trend research as its
    # first step and always overwrites the trend_snapshot the book-writing
    # step reads -- passing trend_snapshot directly in input_args never
    # reached it, since that variable isn't wired to any input at all. LAO's
    # v0.9.4 KDP package added a real topicOverride input specifically for
    # this: when set, the research step returns it as the trend_snapshot
    # instead of scanning RSS, so HERMES's actual researched angle is what
    # the book gets written about instead of being silently discarded.
    input_args: dict[str, Any] = {"mode": kdp_mode, "region": region, "dryRun": True}
    if angle:
        # The lane travels with the angle. LAO's package exposes no input for
        # it, and what it is handed is all it knows: on 2026-10-23 it took a
        # business-plan angle and wrote a startup-finance book around two
        # invented people, because nothing it received said otherwise. This is
        # the weaker half of the fix -- the delivered-lane gate below does not
        # depend on LAO reading it.
        input_args["topicOverride"] = (
            f"{angle}\n\n"
            "Hard constraints: this is a nonfiction utility book in the "
            "Windows / PowerShell / networking / enterprise automation / "
            "agentic AI operations / AI governance lane. Teach a method the "
            "reader applies to their own work. Do not invent named people, "
            "companies or case studies, and do not write a narrative."
        )

    # Declared before the nested attempt function and mutated via `nonlocal`
    # (not returned) so a heal-and-retry cycle can still see the latest
    # known job id / status payload even when an attempt raises instead of
    # returning normally -- e.g. a file-lock heal needs the run_dir from
    # the attempt that just failed, which only exists in that payload.
    last: dict[str, Any] = {}
    lao_job_id = ""

    def _attempt_lao_run(resume_id: str = "") -> tuple[str, dict[str, Any], str]:
        """One full start+poll+terminal-status attempt. Raises RuntimeError
        on any failure. Deliberately does NOT clear stages itself -- a
        healed retry should keep SCRIBE visibly at work instead of
        flickering back to idle between attempts.

        With resume_id set, the start is skipped entirely and this polls a LAO
        job that is already running -- the recovery path after a restart. The
        poll loop below is identical either way, which is the point: recovery
        reuses the ordinary path rather than a parallel one."""
        nonlocal last, lao_job_id
        if existing_run_dir:
            run_path = Path(existing_run_dir)
            if not run_path.exists() or not (run_path / "KDP_Book_Professional.docx").exists():
                raise RuntimeError(f"Existing KDP run is not complete: {existing_run_dir}")
            title = ""
            meta_path = run_path / "kdp_metadata.json"
            if meta_path.exists():
                try:
                    title = str(json.loads(meta_path.read_text(encoding="utf-8")).get("title") or "")
                except Exception:  # noqa: BLE001
                    title = ""
            lao_job_id = str(brief.get("existing_lao_job_id") or "reconciled-existing-run")
            last = {"job": {"status": "Successful", "output_result": {
                "book_draft": {"run_dir": str(run_path), "title": title, "resumed": True}
            }}}
            stages.set_stage("scribe", stages.EXECUTING,
                             f"Reconciling completed KDP artifact: {title or run_path.name}",
                             lao_job=lao_job_id)
            return "Successful", last, lao_job_id
        if resume_id:
            lao_job_id = resume_id
            stages.set_stage(
                "scribe", stages.EXECUTING,
                f"Picking the book back up — LAO job {resume_id[:8]} after a restart",
                lao_job=resume_id)
        else:
            stages.set_stage("scribe", stages.EXECUTING,
                             f"Starting the book: {angle[:110]}" if angle
                             else "Starting LAO KDP Book Factory")
            started = tool.execute(
                action="start", mode="dry_run", process_name=process_name,
                scope="production",
                input_args=input_args,
            )
            if not started.success:
                raise RuntimeError(f"LAO refused the KDP run: {started.content}")
            try:
                start_payload = json.loads(started.content)
            except json.JSONDecodeError:
                start_payload = {"raw": started.content}
            lao_job_id = ((start_payload.get("job") or {}).get("id")) or ""
            # Recorded before the first poll, not after it: the gap between
            # starting the job and writing down its id is exactly the window
            # where a restart loses the reference and the book is orphaned.
            job_recovery.attach(_connect, job["id"], lao_job_id)

        # --- wait for the book ---------------------------------------------
        poll_seconds = float(os.environ.get("ONE_LAO_POLL_SECONDS", "30"))
        max_wait = float(os.environ.get("ONE_LAO_MAX_WAIT_SECONDS", "10800"))  # 3h
        deadline = time.time() + max_wait
        terminal = {"Successful", "Failed", "Stopped", "Cancelled", "Faulted"}
        status = "Pending"
        consecutive_probe_failures = 0
        # See the matching comment in _run_muse -- without this check, a failed
        # status probe silently kept the last-known status forever instead of
        # ever surfacing that polling itself had stopped succeeding.
        max_consecutive_probe_failures = 5

        while time.time() < deadline:
            time.sleep(poll_seconds)
            # Says "this worker is still alive" to the restart sweep. Without
            # it a long healthy poll looks exactly like an orphan.
            job_recovery.heartbeat(_connect, job["id"])
            probe = tool.execute(action="status", process_name=process_name,
                                 scope="production", job_id=lao_job_id)
            if not probe.success:
                consecutive_probe_failures += 1
                stages.set_stage(
                    "scribe", stages.EXECUTING,
                    f"Lost contact with LAO, retrying ({consecutive_probe_failures}/{max_consecutive_probe_failures})…",
                    lao_job=lao_job_id, lao_process=process_name)
                if consecutive_probe_failures >= max_consecutive_probe_failures:
                    raise RuntimeError(
                        f"Lost contact with LAO after {consecutive_probe_failures} consecutive "
                        f"failed status polls (last: {probe.content[:200]}) -- cannot confirm "
                        "whether the underlying LAO job is still running."
                    )
                continue
            consecutive_probe_failures = 0
            try:
                last = json.loads(probe.content)
            except json.JSONDecodeError:
                last = {"raw": probe.content}
            status = str((last.get("job") or {}).get("status") or status)
            # Keep the bubble beside SCRIBE honest about the long wait: what it is
            # writing, and where LAO actually is.
            elapsed = int((time.time() - (deadline - max_wait)) // 60)
            stages.set_stage(
                "scribe", stages.EXECUTING,
                (f"Writing “{angle[:70]}” · LAO {status} · {elapsed}m" if angle
                 else f"LAO job {status} · {elapsed}m"),
                lao_job=lao_job_id, lao_process=process_name)
            if status in terminal:
                break
        else:
            raise RuntimeError(
                f"LAO KDP job did not finish within {max_wait/3600:.1f}h (last status: {status})"
            )

        if status != "Successful":
            # Carry LAO's own reason, not just its verdict. On 2026-10-06 this
            # raised "LAO KDP job ended as Failed" and nothing else, while the
            # sentence that mattered - a Claude Code path pinned to a version
            # that had since been updated away - sat inside LAO. The Chairman
            # had to go and find it himself, which is the floor's job.
            raise RuntimeError(
                f"LAO KDP job ended as {status}: {_lao_failure_reason(lao_job_id, last)}")

        return status, last, lao_job_id

    # Up to 3 attempts total: the infrastructure failures lao_healer.heal()
    # recognizes (stuck-busy robot, stale-code rejection, orphaned file
    # lock) are transient and self-resolve once fixed, so a fresh attempt
    # right after healing usually just works -- see lao_healer.py for why
    # this exists instead of failing straight to a human every time.
    max_attempts = 3
    status = ""
    final_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            # Only the first attempt resumes. If that fails and the healer
            # runs, the retry starts a genuinely fresh LAO job rather than
            # re-attaching to one that just went wrong.
            status, last, lao_job_id = _attempt_lao_run(
                job_recovery.resume_target(job) if attempt == 1 else ""
            )
            final_error = None
            break
        except RuntimeError as exc:
            final_error = exc
            if attempt >= max_attempts:
                break
            heal_run_dir = str(
                ((last.get("job") or {}).get("output_result") or {})
                .get("book_draft", {})
                .get("run_dir") or ""
            )
            healing = lao_healer.heal(str(exc), heal_run_dir)
            stages.set_stage(
                "scribe", stages.EXECUTING,
                f"Hit a snag ({str(exc)[:60]}) — {healing['diagnosis'][:90]}",
            )
            if not healing["healed"]:
                break
            time.sleep(5)

    if final_error is not None:
        stages.clear_stage("scribe")
        stages.clear_stage("hermes")
        raise final_error

    # Prefer the run_dir/title LAO's own status response already carries --
    # it is authoritative (LAO's robot-worker knows exactly what it wrote)
    # and, critically, this process's Path.home() is a SANDBOXED
    # runtime_home (set by start-one.ps1), not the real Windows profile LAO
    # actually writes under, so re-discovering the folder locally via
    # _latest_kdp_output() was silently looking in the wrong place. That
    # function is now only a last-resort fallback for the rare case LAO's
    # response is missing this data.
    book_draft = ((last.get("job") or {}).get("output_result") or {}).get("book_draft") or {}
    run_dir = str(book_draft.get("run_dir") or "")
    title = str(book_draft.get("title") or "")
    if not run_dir or not title:
        try:
            run_dir, title = _latest_kdp_output()
        except RuntimeError:
            # LAO said "Successful" but the output can't actually be
            # confirmed -- do not walk a phantom book across the floor.
            # HERMES, not PEITHO, is who's still blocked here -- the
            # SCRIBE->PEITHO leg only exists after a successful handoff,
            # which this failure never reaches.
            stages.clear_stage("scribe")
            stages.clear_stage("hermes")
            raise

    # The lane is checked again here, on the book that exists rather than on
    # the brief that asked for it. LAO receives no lane constraint at all, so
    # a commission that passed every gate upstream can still come back as a
    # different book about something else -- and until this, it did, with the
    # submission packet written for it and the Chairman asked to upload it.
    delivered = _delivered_book_lane(run_dir, title)
    if not delivered["passed"]:
        stages.clear_stage("scribe")
        stages.clear_stage("hermes")
        _publishing_event(
            job, agent="SCRIBE", event_type="research_blocked",
            stage="delivered_lane_gate",
            summary=(f"Rejected: the delivered book "
                     f"{delivered['delivered_title']!r} is outside the catalogue lane"),
            details=delivered, status="rejected",
        )
        return {
            "agent": "SCRIBE", "mode": "blocked", "_blocked": True,
            "content": ("The manuscript is preserved, but the book that was "
                        "written is not in the catalogue lane and will not be "
                        "packaged for upload."),
            "blocked_reason": (f"delivered book {delivered['delivered_title']!r} is "
                               f"outside Vineet Pandey's authority lane"),
            "run_dir": run_dir, "title": title, "delivered_lane": delivered,
        }

    # KDP has no upload/metadata API (confirmed 2026-08-26) and the real
    # submit stays a manual human step -- see _generate_kdp_packet's
    # docstring for why. This is SCRIBE's actual deliverable for that step:
    # every field a human needs, pre-written, ready to paste.
    kdp_packet = _generate_kdp_packet(title, kdp_mode, region, angle, run_dir)
    if not kdp_packet.get("generated") or not kdp_packet.get("path"):
        # A finished manuscript is not upload-ready without its submission
        # packet. Do not expose the OLYMPUS upload action or continue to
        # distribution/economics with an incomplete SCRIBE delivery.
        stages.clear_stage("scribe")
        stages.clear_stage("hermes")
        return {
            "agent": "SCRIBE", "mode": "blocked", "_blocked": True,
            "content": "The manuscript is preserved, but the KDP submission packet is missing.",
            "blocked_reason": str(kdp_packet.get("note") or "KDP packet generation failed"),
            "run_dir": run_dir, "title": title, "kdp_packet": kdp_packet,
        }

    memory.remember(
        agent="SCRIBE", floor_id="5", floor_name="Book Publishing (KDP)",
        kind="Production Run",
        body=(f"Ran LAO's KDP Book Factory to completion.\n\n"
              f"- LAO job: `{lao_job_id}` — {status}\n"
              f"- Output folder: `{run_dir}`\n"
              f"- Title: {title}\n"
              f"- KDP packet: {kdp_packet.get('path') or '(not generated: ' + str(kdp_packet.get('note')) + ')'}\n\n"
              "Waiting on the Chairman to upload it to KDP by hand -- PEITHO's "
              "post-publish work has nothing real to start on until then."),
        task=f"{kdp_mode} / {region}",
        tags=["kdp", "publishing", "production", "awaiting-upload"],
    )

    # --- growth review before the upload gate ------------------------------
    # Explicit call, 2026-08-26: "SCRIBE ke pas se message tab tak na hate
    # jab tak ye book upload na ho jaye" -- PEITHO's job is post-publish
    # marketing, so starting it before the book is actually live on Amazon
    # would have nothing real to work from. SCRIBE's stage stays set (not
    # cleared) and its job stays open (not finished) until the Chairman
    # confirms the upload via confirm_scribe_upload -- that is what actually
    # celebrates with PEITHO, enqueues its job, and closes this one out. This
    # deliberately does NOT block this thread waiting for that confirmation:
    # the outer job watchdog (_job_watchdog_seconds) would eventually kill a
    # thread that blocks for however long a human upload takes and mark it
    # failed, which is exactly the "looks done, actually still running"
    # confusion this whole mechanism exists to avoid. Returning here lets
    # run_worker mark the row 'awaiting_upload' via the _await_human_upload
    # flag below and free the worker thread immediately.
    stages.set_stage("scribe", stages.AWAITING_WORKER,
                     f"“{title}” is ready — waiting on MERCURY and ALFA review")
    mercury_job = enqueue_job(
        "mercury", json.dumps({
            "workflow": "publishing_portfolio", "phase": "distribution_review",
            "scribe_job_id": job["id"], "run_dir": run_dir, "title": title,
            "lao_job": lao_job_id, "kdp_mode": kdp_mode, "region": region,
            "kdp_packet": kdp_packet,
            "mission_id": brief.get("mission_id") or brief.get("origin_job"),
            "origin_job": brief.get("origin_job"), "objective": brief.get("objective"),
            "select_active": brief.get("select_active"),
            "wide_requested": bool(brief.get("wide_requested", kdp_mode == "nonfiction")),
        }), mode="execute", tier="fast")
    # HERMES's own job (_run_hermes) set itself to AWAITING_WORKER when it
    # briefed SCRIBE and has been blocked ever since -- that wait was only
    # ever for the manuscript, which is done now. Nothing else clears it:
    # this SCRIBE->PEITHO leg bypasses HERMES entirely (see confirm_
    # scribe_upload's docstring for why), so without this line HERMES was
    # left showing "Waiting on SCRIBE" in the building forever, confirmed
    # live 2026-08-28 on a book that had already been uploaded and handed
    # to PEITHO.
    stages.clear_stage("hermes")

    return {
        "agent": "SCRIBE",
        "mode": job.get("mode"),
        "lao_job": lao_job_id,
        "lao_status": status,
        "run_dir": run_dir,
        "title": title,
        "kdp_mode": kdp_mode,
        "region": region,
        "mission_id": brief.get("mission_id") or brief.get("origin_job"),
        "origin_job": brief.get("origin_job"), "objective": brief.get("objective"),
        "kdp_packet": kdp_packet,
        "growth_review": {"agent": "MERCURY", "job_id": mercury_job["id"]},
        "requires_human": "After MERCURY/ALFA clear the title: Amazon KDP upload",
        "_await_growth_review": True,
    }


def _latest_kdp_output() -> tuple[str, str]:
    """Newest KDP run folder on disk, and a best-effort title from it.

    Reads what LAO actually produced rather than trusting the job payload —
    the run folder is the artifact, and its name is the timestamped truth.
    Raises if that can't be confirmed. It used to swallow this and return a
    placeholder string like "(output folder unreadable)" as if it were a
    real title -- which then got walked across the floor and celebrated as
    a shipped book. A caller that reports success must never do so without
    having actually verified the output.
    """
    from pathlib import Path as _Path

    base = _Path(os.environ.get(
        "LAO_KDP_OUTPUT_DIR",
        str(_Path.home() / "Documents" / "LAO" / "kdp-book-factory" / "output"),
    ))
    try:
        runs = sorted(
            (p for p in base.iterdir() if p.is_dir() and p.name.endswith("claude-code-kdp-book")),
            key=lambda p: p.stat().st_mtime,
        )
    except OSError as exc:
        raise RuntimeError(f"Could not read KDP output folder {base}: {exc}") from exc
    if not runs:
        raise RuntimeError(f"LAO reported a successful run but no output folder exists under {base}")

    run = runs[-1]
    title = run.name
    meta = run / "kdp_metadata.json"
    if meta.exists():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            title = str(data.get("title") or data.get("Title") or title)
        except (json.JSONDecodeError, OSError):
            pass
    return str(run), title


def _sonia_seo_package(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a governed YouTube package from YATRA's verified master, for any destination."""
    from openjarvis.one_agents import youtube_seo

    asset_folder = str(payload.get("asset_folder") or "").strip()
    root = _YATRA_ASSET_ROOT / asset_folder
    plan_path = root / "production-plan.json"
    master = Path(str((payload.get("cut") or {}).get("master") or root / "edit" / "master.mp4"))
    if not plan_path.is_file() or not master.is_file():
        raise RuntimeError("ARES needs YATRA's production plan and verified master")
    record = (json.loads(plan_path.read_text(encoding="utf-8")) or [{}])[0]
    package = youtube_seo.build_package(
        record, master=master, plan_path=plan_path,
        portrait_library=_YATRA_ASSET_ROOT / "_channel-assets" / "sonia-portraits")
    out = root / "seo" / "youtube-seo-package.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    package["path"] = str(out)
    return package


def _radar_fetch(url: str) -> bytes:
    """The trend radar's only door to the network: Sanjeevani's TLS-verified,
    SSRF-guarded fetcher (it refuses private and loopback addresses)."""
    reusable = _sanjeevani_research()
    if reusable is None:
        raise RuntimeError("Sanjeevani research library is unavailable")
    return reusable._get(reusable._safe_public_url(url), timeout=15, limit=2_000_000, attempts=1)


def _ares_dispatch_linkedin(job: dict[str, Any], li: Any) -> dict[str, Any]:
    """Floor 3 head: build today's LinkedIn Authority brief, then brief HERALD.

    The decisions (pillar, brief wording, standing-authority test) live in
    floors/floor_03_growth/lib/linkedin_authority.py; this is only the plumbing.
    ARES researches and decides; HERALD executes the brief and never chooses its
    own topic or its own authority to publish.
    """
    task = str(job.get("task") or "")
    mode = str(job.get("mode") or "plan").strip().lower()
    channel = li.channel()
    display = channel.get("display_name", "LinkedIn Authority")

    # stages.set_stage() keeps one record per agent_id, so a second concurrent
    # ARES flow (the Sonia SEO leg also uses this head) would overwrite the
    # first's worker_job pointer. Decline visibly rather than silently skip.
    current = (stages.get_stages() or {}).get("ares")
    if current and current.get("stage") not in {"idle", None}:
        detail = str(current.get("detail") or "").strip()
        reason = (f"ARES is already mid-flow ({current.get('stage')}"
                  + (f" - {detail}" if detail else "") + f"); {display} was not started.")
        return {"agent": "ARES", "mode": "blocked", "_blocked": True, "content": reason,
                "blocked_reason": reason, "handed_to": None}

    stages.set_stage("ares", stages.RESEARCHING, task.strip()[:180] or f"Choosing the next {display} post")

    prior = list(memory.prior_titles("3", channel["vault_floor_name"]))
    legacy = channel.get("legacy_vault") or {}
    if legacy:  # the channel's history before it moved to Floor 3
        prior += [t for t in memory.prior_titles(str(legacy["floor_id"]), legacy["floor_name"]) if t not in prior]

    weekday = datetime.now(ZoneInfo("Asia/Kolkata")).weekday()
    pillar, pillar_query = li.pillar_for(weekday)
    angle, evidence_path, evidence_count, ground_error = "", "", 0, ""

    # LinkedIn v2 (2026-10-14): the radar picks a live tech trend by code. Any
    # failure here keeps the v1 brief below, so the slot is never lost to v2.
    v2_plan = None
    try:
        v2_plan = linkedin_growth.plan(weekday=weekday, fetch=_radar_fetch, prior_titles=prior, home=_home(),
                                       job_id=str(job["id"]))
    except Exception as exc:  # noqa: BLE001
        print(f"[one-agents] LinkedIn v2 plan failed, using the v1 brief: {type(exc).__name__}: {exc}", flush=True)
    if v2_plan:
        pillar = v2_plan["lane_label"]
        angle = str(v2_plan["story"]["title"])
        evidence_path = v2_plan["radar_path"]
        evidence_count = len(v2_plan["story"].get("evidence", []))
    else:
        reusable = _sanjeevani_research()
        if reusable is None:
            ground_error = "Sanjeevani research library unavailable"
        else:
            try:
                snapshot = reusable.collect(pillar_query, markets=["IN", "US", "GB"])
                eligible = list(snapshot.get("eligible") or [])
                evidence_count = len(eligible)
                if not eligible:
                    ground_error = "zero eligible current evidence"
                else:
                    brief, note = _research_synthesis(li.brief_prompt(pillar, prior), evidence=snapshot)
                    if brief:
                        angle = brief
                    else:
                        ground_error = note or "local synthesis returned no brief"
            except Exception as exc:
                ground_error = f"{type(exc).__name__}: {exc}"

    if v2_plan:
        pass  # the radar story and its audit file are already set above
    elif angle:
        output_dir = _home() / "agent_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        evidence_file = output_dir / f"{job['id']}-linkedin-brief.md"
        evidence_file.write_text(li.brief_document(task, pillar, angle), encoding="utf-8")
        evidence_path = str(evidence_file)
        memory.remember(agent="ARES", floor_id="3", floor_name=channel["vault_floor_name"],
                        kind="LinkedIn Authority Brief", body=angle, task=task,
                        tags=["linkedin", "authority", "sanjeevani", pillar.lower()])
    elif li.requires_grounding(weekday):
        # Saturday alone must stop rather than let ChatGPT invent a "trending"
        # story the Content Bible says has to be real.
        stages.clear_stage("ares")
        return {"agent": "ARES", "mode": "blocked", "_blocked": True,
                "content": f"LinkedIn Authority stopped: {ground_error}.",
                "blocked_reason": ground_error, "handed_to": None}
    else:
        # Every other day lets ChatGPT pick a topic inside the day's pillar; a
        # research miss enriches nothing today but must not stop that day.
        angle = li.fallback_angle(task, pillar)

    authorized = li.routine_publish_allowed(task)
    if authorized:
        authorized = _job_fired_by_trigger(str(channel.get("routine_trigger_id") or ""), str(job.get("id") or ""))
        if not authorized:
            print(f"[one-agents] {job.get('id')} names the {display} schedule but has no fire receipt; "
                  "HERALD is briefed without publish authority", flush=True)

    worker = stages.head_briefs_worker(
        "ares", "herald",
        carrying_detail=f"Taking the {display} brief to HERALD",
        briefing_detail=f"HERALD, today's {display} post ({pillar}): {task.strip()[:90]}",
        awaiting_detail=f"Waiting on HERALD to publish the {display} post",
        enqueue=lambda: enqueue_job(
            "herald",
            json.dumps(li.worker_payload(
                angle=angle, pillar=pillar, prior_titles=prior, origin_job=str(job["id"]),
                evidence_path=evidence_path, evidence_count=evidence_count,
                publish_authorized=authorized, v2=v2_plan)),
            mode="execute", tier="fast"),
    )
    return {
        "agent": "ARES", "mode": mode, "brand": li.SLUG, "pillar": pillar, "v2": bool(v2_plan),
        "content": f"Briefed HERALD on today's {display} post ({pillar}).",
        "prior_posts_considered": len(prior), "sanjeevani_evidence_count": evidence_count,
        "evidence_path": evidence_path, "publish_authorized": authorized,
        "handed_to": {"agent": "HERALD", "job_id": worker["id"]},
        "note": "HERALD will execute the head-approved brief and hand its receipt back to ARES.",
    }


def _ares_report_linkedin(job: dict[str, Any], payload: dict[str, Any], li: Any) -> dict[str, Any]:
    """Third leg: HERALD's verified receipt comes back to its head and is filed."""
    channel = li.channel()
    stages.set_stage("ares", stages.REPORTING, "Reporting the finished LinkedIn Authority post")
    message = li.receipt_summary(payload)
    if payload.get("v2_digest"):
        message += "\n\n" + str(payload["v2_digest"])
    title = payload.get("title") or "(details in the receipt)"
    output_dir = _home() / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job['id']}.md"
    output_path.write_text(f"# ARES - Delivery Report (LinkedIn Authority)\n\n{message}\n", encoding="utf-8")
    remembered = memory.remember(
        agent="ARES", floor_id="3", floor_name=channel["vault_floor_name"], kind="Delivery Report",
        body=f"{message}\n\nANGLE: {title}\n",
        tags=[li.SLUG, "growth", "linkedin post", "delivered"])
    time.sleep(2.0)
    stages.clear_stage("ares")
    return {"agent": "ARES", "mode": "report", "brand": li.SLUG, "content": message, "title": title,
            "format": payload.get("format") or "LinkedIn post", "published": bool(payload.get("published")),
            "output": str(output_path), "vault_note": remembered.get("path")}


def _run_lyra(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 12 YouTube packaging specialist.

    LYRA owns the Sonia SEO/thumbnail package that previously made ARES a
    cross-floor bottleneck. The payload and artifact paths stay compatible so
    an in-flight production can resume across the migration.
    """
    payload = _json_task(job)
    if payload.get("brand") == "planexium":
        from openjarvis.one_agents.planexium import repackage_job
        result = repackage_job(payload)
        report = enqueue_job("helios", json.dumps({"brand": "planexium", "stage": "production_complete", **result}),
                             mode="report", dedupe_key=f"planexium:{payload['mission_id']}:packaging-report")
        return {**result, "agent": "LYRA", "handed_to": {"agent": "HELIOS", "job_id": report["id"]}}
    if payload.get("brand") != "sonia_travel_vlogs" or payload.get("stage") != "seo":
        return {"agent": "LYRA", "mode": "blocked", "_blocked": True,
                "content": "LYRA accepts only HELIOS-approved YouTube packaging jobs.",
                "blocked_reason": "unsupported LYRA payload", "handed_to": None}
    stages.worker_confirms_receipt("lyra", "Received YATRA's verified master from HELIOS")
    try:
        stages.set_stage("lyra", stages.EXECUTING,
                         "Building search, chapters, packaging and private-upload manifest")
        package = _sonia_seo_package(payload)
        stages.set_stage("lyra", stages.EXECUTING,
                         "Generating and scoring three thumbnail variants in ChatGPT")
        try:
            from openjarvis.one_agents import ares_thumbnail
            from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool
            package["thumbnail_receipt"] = ares_thumbnail.make_thumbnail_experiment(
                Path(package["path"]), tool=LaoOrchestratorTool(),
                artifact_roots=_YATRA_ROBOT_ARTIFACTS, max_wait_seconds=780)
        except Exception as exc:  # noqa: BLE001 - gate records the missing thumbnail
            package["thumbnail_receipt"] = {
                "ok": False, "stage": "error",
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            }
        try:
            from openjarvis.one_agents import youtube_publish
            package["upload_gate"] = youtube_publish.prepare_gate(Path(package["path"]))
        except Exception as exc:  # noqa: BLE001 - SEO package remains inspectable
            package["upload_gate"] = {
                "status": "unavailable",
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            }
        stages.set_stage("lyra", stages.CARRYING_TO_HEAD,
                         "Taking the SEO and private-upload package back to HELIOS")
        _require_active_job(job, "hand the SEO package to HELIOS")
        report = enqueue_job(
            "helios",
            json.dumps({**payload, "stage": "seo_complete",
                        "format": "youtube_seo_package", "worker": "lyra",
                        "seo": package, "published": False,
                        "output": package["path"]}),
            mode="report", tier="fast",
            dedupe_key=f"travel:{payload.get('lao_job')}:seo-report",
        )
        return {"agent": "LYRA", "stage": "seo", "seo": package,
                "published": False,
                "handed_to": {"agent": "HELIOS", "job_id": report["id"]}}
    finally:
        stages.clear_stage("lyra")


def _run_chandan(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 12 production worker, restricted to its commissioned brand."""
    if _json_task(job).get("brand") != "origin_to_ovation":
        raise ValueError("CHANDAN only accepts explicit origin_to_ovation missions")
    from openjarvis.one_agents.origin_to_ovation import run_stage
    from openjarvis.one_agents.chandan_control import ProviderTerminalError, terminal_result
    try:
        return run_stage(job, enqueue=enqueue_job)
    except ProviderTerminalError as error:
        return terminal_result(error)


def _run_ares(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 3 - organic publishing distribution or the existing local plan."""
    payload = _json_task(job)
    if payload.get("brand") == "planexium":
        from openjarvis.one_agents.planexium_seo import run_job
        return run_job(job)
    if payload.get("brand") == "origin_to_ovation":
        from openjarvis.one_agents.origin_to_ovation import run_stage
        return run_stage(job, enqueue=enqueue_job)
    if (payload.get("brand") == "sonia_travel_vlogs"
            and payload.get("stage") == "thumbnail_editorial_approval"):
        from openjarvis.one_agents.ares_thumbnail import promote_editorial_approval

        root = Path(str(payload.get("asset_root") or ""))
        source = Path(str(payload.get("thumbnail") or ""))
        if not root.is_dir() or not source.is_file():
            raise RuntimeError("ARES received an incomplete editorial-thumbnail approval")
        stages.worker_confirms_receipt("ares", "Received the user's approved Sonia thumbnail")
        try:
            stages.set_stage("ares", stages.EXECUTING,
                             "Normalising and hash-binding the approved thumbnail for ECHO")
            receipt = promote_editorial_approval(
                root, source, approved_by=str(payload.get("approved_by") or "user"),
                note=str(payload.get("note") or ""),
            )
            stages.set_stage("ares", stages.CARRYING_TO_HEAD,
                             "Approved thumbnail is bound to the normal ECHO upload path")
            return {"agent": "ARES", "stage": "thumbnail_editorial_approval",
                    "status": "approved", "thumbnail": receipt["path"],
                    "thumbnail_sha256": receipt["sha256"], "published": False}
        finally:
            stages.clear_stage("ares")
    # LinkedIn Authority: the one channel Floor 3 owns (Chairman, 2026-10-13).
    _task_text = str(job.get("task") or "")
    _li = floors_bridge.load("floor_03_growth", "linkedin_authority")
    if _li is not None and _li.is_linkedin_task(_task_text, payload):
        if str(job.get("mode") or "").strip().lower() == "report" and payload.get("worker") == "herald":
            return _ares_report_linkedin(job, payload, _li)
        return _ares_dispatch_linkedin(job, _li)
    if _li is None and "[linkedin-authority]" in _task_text.lower():
        reason = "LinkedIn Authority stopped: Floor 3's linkedin_authority module could not be loaded."
        return {"agent": "ARES", "mode": "blocked", "_blocked": True, "content": reason,
                "blocked_reason": reason, "handed_to": None}
    if payload.get("brand") == "sonia_travel_vlogs" and payload.get("stage") == "vista_thumbnail_seo":
        # VISTA deliberately stops before the expensive ChatGPT thumbnail/SEO leg. ARES owns that leg and resumes
        # from VISTA's durable handoff; it must never call the full production entry point because doing so could
        # buy footage or synthesize Sonia's narration again.
        slot = str(payload.get("slot") or "")
        origin = str(payload.get("origin_job") or "")
        trigger_id = str(payload.get("trigger_id") or "")
        handoff = payload.get("handoff")
        if slot not in {"0900", "1300", "1800"} or not origin:
            raise RuntimeError("ARES received an incomplete VISTA thumbnail/SEO handoff")
        expected_trigger = f"daily-vista-short-{slot}"
        if trigger_id != expected_trigger or not _job_fired_by_trigger(expected_trigger, origin):
            raise RuntimeError("ARES VISTA handoff has no authentic scheduler fire receipt")
        if not isinstance(handoff, (dict, str)) or not handoff:
            raise RuntimeError("ARES received no durable VISTA thumbnail/SEO handoff")

        stages.worker_confirms_receipt("ares", "Received VISTA's saved Short for thumbnail and SEO")
        try:
            stages.set_stage("ares", stages.EXECUTING,
                             "Generating Sonia's thumbnail and completing the Short SEO package")
            runner = _load_vista_runner()
            resume = getattr(runner, "resume_thumbnail_seo", None)
            if not callable(resume):
                raise RuntimeError("VISTA runner has no resume_thumbnail_seo(handoff) checkpoint function")
            result = resume(handoff)
            package = Path(str(result.get("package") or "")) if isinstance(result, dict) else Path("")
            if not isinstance(result, dict) or result.get("status") != "qc_passed" or not package.is_file():
                raise RuntimeError("ARES did not receive a QC-passed VISTA distribution package")

            stages.set_stage("ares", stages.CARRYING_TO_HEAD,
                             "Taking the QC-passed Short package to ECHO for private upload")
            # The trigger origin identifies the commissioned story, not the
            # concrete rebuilt cut.  A later VISTA successor for that story
            # must not inherit the completed ECHO job from the withdrawn cut.
            # The originating VISTA job is stable across retries of this ARES
            # stage and unique across intentional rebuilds.
            vista_job_id = str(payload.get("vista_job") or job.get("id") or "")
            handoff_key = f"vista:{origin}:{slot}:{vista_job_id}:publish"
            if payload.get("rebuild_run_dir"):
                import hashlib
                master = Path(str(result.get("master") or ""))
                if not master.is_file():
                    raise RuntimeError("Rebuilt VISTA package has no master for upload dedupe")
                handoff_key += ":" + hashlib.sha256(master.read_bytes()).hexdigest()[:16]
            _require_active_job(job, "hand the QC-passed Short to ECHO")
            echo_payload = {
                **payload,
                "stage": "vista_short_publish",
                "package": str(package),
                "publish_authorized": True,
                "trigger_id": trigger_id,
                "ares_job": job.get("id"),
            }
            echo_job = enqueue_job("echo", json.dumps(echo_payload), mode="execute", tier="fast",
                                   dedupe_key=handoff_key)
            return {"agent": "ARES", **result,
                    "handed_to": {"agent": "ECHO", "job_id": echo_job["id"]}}
        finally:
            stages.clear_stage("ares")
    if payload.get("brand") == "sonia_travel_vlogs" and payload.get("stage") == "seo":
        forwarded = enqueue_job(
            "lyra", json.dumps(payload), mode="execute", tier="fast",
            dedupe_key=f"travel:{payload.get('lao_job')}:lyra-migration",
        )
        return {"agent": "ARES", "mode": "handoff",
                "content": "YouTube packaging moved to LYRA on Floor 12; payload forwarded unchanged.",
                "handed_to": {"agent": "LYRA", "job_id": forwarded["id"]}}
    if payload.get("workflow") == "publishing_portfolio":
        title = str(payload.get("title") or "(untitled)")
        plan = {
            "title": title, "status": "DRAFT", "real_spend": False,
            "channels": ["short-form hooks", "author/brand social", "reader email",
                         "store metadata iteration"],
            "paid_ads": "not started; only proven titles qualify for a bounded test",
        }
        metron_job = enqueue_job(
            "metron", json.dumps({**payload, "phase": "measurement", "growth_plan": plan}),
            mode="execute", tier="fast")
        _publishing_event(job, agent="ARES", event_type="organic_plan",
                          stage="organic_distribution", summary="No-spend launch plan drafted",
                          details={"channels": plan["channels"], "paid_ads": plan["paid_ads"]})
        return {"agent": "ARES", "organic_distribution": plan,
                "handed_to": {"agent": "METRON", "job_id": metron_job["id"]},
                "content": "Organic distribution plan drafted; no ad spend or external post executed."}
    return _local_plan(job)


ECHO_LANGUAGE_UPLOADS_PER_SWEEP = 1  # at most ~15 min of ECHO per hour, so a VISTA upload never waits long
ECHO_LANGUAGE_BUDGET_SECONDS = float(os.environ.get("ONE_ECHO_LANGUAGE_BUDGET_SECONDS", "900"))


def _echo_missing_languages(uploader: Any) -> list[dict[str, Any]]:
    """Translate and add the languages recent uploads still lack, newest first, one upload per hourly sweep.

    A Short's upload translates inside a time budget, so some of its 14 languages can be missing at upload; until
    2026-10-13 nothing added them later. Each language is saved as soon as it is translated, so a sweep that runs
    out of time leaves its work for the next one. Only the translations are sent: the live title stays as it is."""
    from openjarvis.one_agents import youtube_publish
    results: list[dict[str, Any]] = []
    for sha, entry, missing in uploader.pending_localization_entries()[:ECHO_LANGUAGE_UPLOADS_PER_SWEEP]:
        try:
            added, failed = youtube_publish.ensure_localizations(Path(entry["package"]), tuple(missing),
                                                                 budget_seconds=ECHO_LANGUAGE_BUDGET_SECONDS)
            fresh = uploader.ledger_load().get(sha) or entry
            applied = uploader.apply_localizations(sha, fresh) if added else {"localized": []}
            results.append({"video_id": entry.get("video_id"), "translated": sorted(added),
                            "localized": applied.get("localized"), "still_missing": sorted(failed)})
        except Exception as exc:  # noqa: BLE001 - one upload's trouble never stops the next one
            results.append({"video_id": entry.get("video_id"), "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
    return results


def _run_echo(job: dict[str, Any]) -> dict[str, Any]:
    """Finish Sonia's private YouTube draft after LYRA returns its package to HELIOS."""
    payload = _json_task(job)
    if payload.get("brand") == "origin_to_ovation":
        from openjarvis.one_agents.origin_to_ovation import run_stage
        return run_stage(job, enqueue=enqueue_job)
    if payload.get("brand") == "planexium":
        if payload.get("stage") != "private_upload":
            raise ValueError("PLANEXIUM distribution requires explicit private-upload stage")
        from openjarvis.one_agents.planexium import stage_private
        return {"agent": "ECHO", "brand": "planexium", "published": False, **stage_private(payload)}
    if payload.get("brand") == "sonia_travel_vlogs" and payload.get("stage") == "vista_short_publish":
        package = Path(str(payload.get("package") or ""))
        slot = str(payload.get("slot") or "")
        if not package.is_file() or slot not in {"0900", "1300", "1800"}:
            raise RuntimeError("ECHO received an incomplete VISTA distribution package")
        if not _job_fired_by_trigger(f"daily-vista-short-{slot}", str(payload.get("origin_job") or "")):
            raise RuntimeError("VISTA upload has no authentic scheduler fire receipt")
        stages.worker_confirms_receipt("echo", "Received VISTA's QC-passed Short package")
        try:
            from openjarvis.one_agents import youtube_publish
            pkg = json.loads(package.read_text(encoding="utf-8"))
            blockers = youtube_publish.media_metadata_blockers(pkg)
            if blockers:
                raise RuntimeError("VISTA private upload blocked: " + " | ".join(blockers))
            master = Path(str(pkg.get("master") or ""))
            thumbnail = Path(str(pkg.get("thumbnail") or ""))
            caption = Path(str(pkg.get("caption") or ""))
            if not master.is_file() or not thumbnail.is_file() or not caption.is_file():
                raise RuntimeError("VISTA master, thumbnail or manual subtitle file is missing")
            stages.set_stage("echo", stages.EXECUTING,
                             "Uploading VISTA's private Short; Studio will attach its separate thumbnail")
            uploader = youtube_publish._load("youtube_api_upload")
            # Upload and Studio thumbnailing are two durable stages. If Studio is temporarily unavailable, an ECHO
            # retry resumes the already-created private video instead of uploading the exact master a second time.
            upload_receipt = package.with_name("private-upload-receipt.json")
            with master.open("rb") as master_handle:
                master_sha256 = hashlib.file_digest(master_handle, "sha256").hexdigest()
            try:
                saved_upload = json.loads(upload_receipt.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved_upload = {}
            if (saved_upload.get("master_sha256") == master_sha256
                    and (saved_upload.get("report") or {}).get("video_id")):
                upload_report = dict(saved_upload["report"])
            else:
                # The API creates the private draft and attaches subtitles/SEO, but deliberately does not set the
                # thumbnail. Shorts must begin with the actual video hook rather than a 0.5 s embedded cover.
                upload_report = uploader.run(package, video=master, thumbnail=None, synthetic="yes", execute=True,
                                             caption=caption, caption_language="hi")
                temporary = upload_receipt.with_suffix(upload_receipt.suffix + ".tmp")
                temporary.write_text(json.dumps({"schema": "vista-private-upload/1",
                                                 "master_sha256": master_sha256,
                                                 "report": upload_report}, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
                os.replace(temporary, upload_receipt)
            from openjarvis.one_agents import youtube_studio_thumbnail
            thumbnail_report = youtube_studio_thumbnail.set_short_thumbnail(
                str(upload_report.get("video_id") or ""), thumbnail,
                receipt_path=package.with_name("studio-thumbnail-receipt.json"),
            )
            upload_report = {**upload_report, "thumbnail_set": "youtube_studio_persistent_session",
                             "studio_thumbnail": thumbnail_report}
            stages.set_stage("echo", stages.CARRYING_TO_HEAD,
                             "Taking VISTA's verified private upload back to HELIOS")
            _require_active_job(job, "report VISTA private upload completion to HELIOS")
            report = enqueue_job(
                "helios",
                json.dumps({**payload, "stage": "distribution_complete",
                            "format": "youtube_private_draft", "worker": "echo",
                            "distribution": upload_report, "published": False,
                            "output": str(package)}, ensure_ascii=False),
                mode="report",
                tier="fast",
                dedupe_key=(
                    f"vista:{payload.get('origin_job')}:{slot}:"
                    f"{payload.get('vista_job') or job.get('id')}:distribution-report"
                ),
            )
            return {"agent": "ECHO", "stage": "vista_short_publish", "status": "uploaded_private",
                    "video_id": upload_report.get("video_id"), "studio_url": upload_report.get("studio_url"),
                    "master": str(master), "thumbnail": str(thumbnail), "subtitles": str(caption),
                    "content": f"VISTA Short uploaded privately: "
                               f"{upload_report.get('studio_url') or upload_report.get('video_id')}",
                    "handed_to": {"agent": "HELIOS", "job_id": report["id"]}}
        finally:
            stages.clear_stage("echo")
    if payload.get("brand") == "sonia_travel_vlogs" and payload.get("stage") == "pending_comments":
        # The channel comment waits for the video to go public (comments are off while it is private).
        stages.worker_confirms_receipt("echo", "Received the owed channel comments from HELIOS")
        try:
            from openjarvis.one_agents import youtube_publish
            stages.set_stage("echo", stages.EXECUTING, "Posting channel comments on videos that are now public")
            uploader = youtube_publish._load("youtube_api_upload")
            posted = uploader.post_pending_comments() if payload.get("videos", True) else []
            languages = _echo_missing_languages(uploader) if payload.get("languages") else []
            planexium_posted: list[dict[str, Any]] = []
            if payload.get("planexium"):
                # Planexium's own channel, credential and ledgers; a failure there is reported, not raised.
                try:
                    from openjarvis.one_agents import planexium
                    planexium_posted = planexium.post_pending_comments()
                except Exception as exc:  # noqa: BLE001
                    planexium_posted = [{"channel": "planexium", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}]
            everything = posted + planexium_posted
            return {"agent": "ECHO", "stage": "pending_comments", "results": posted, "languages": languages,
                    "planexium": planexium_posted,
                    "content": f"{sum(1 for r in everything if r.get('posted'))} comment(s) posted; "
                               f"{sum(1 for r in everything if r.get('waiting'))} video(s) still private. "
                               f"Languages added on {sum(1 for r in languages if r.get('localized'))} upload(s). "
                               "Pin each posted comment in Studio."}
        finally:
            stages.clear_stage("echo")
            stages.worker_finished("helios", str(job.get("id") or ""))
    if payload.get("brand") == "sonia_travel_vlogs" and payload.get("stage") == "community_poll":
        stages.worker_confirms_receipt("echo", "Received today's community poll brief from HELIOS")
        try:
            from openjarvis.one_agents import sonia_community
            stages.set_stage("echo", stages.EXECUTING, "Writing, illustrating and posting Sonia's community poll")
            brief = payload["brief"]
            if not brief.get("publish_authorized"):
                out = sonia_community.load().run(brief, dry_run=True)
                return {"agent": "ECHO", "stage": "community_poll", "status": out.get("status"),
                        "requires_olympus": True, "screenshot": out.get("screenshot"),
                        "question": (out.get("record") or {}).get("question"),
                        "content": "Community poll prepared as a dry run only: this job has no fire receipt from "
                                   "the daily schedule, so posting it needs OLYMPUS."}
            out = sonia_community.load().run(brief)
            if out.get("status") not in ("posted", "already_posted"):
                raise RuntimeError(f"community poll not posted: {out.get('reason') or out.get('status')}")
            record = out.get("record") or {}
            return {"agent": "ECHO", "stage": "community_poll", "status": out["status"], "post_id": out.get("post_id"),
                    "question": record.get("question") or out.get("question"),
                    "options": [o.get("caption") for o in record.get("options", [])],
                    "content": (f"Community poll {out['status'].replace('_', ' ')}: "
                                f"{record.get('question') or out.get('question')}")}
        finally:
            stages.clear_stage("echo")
            stages.worker_finished("helios", str(job.get("id") or ""))
    package = Path(str(payload.get("package") or payload.get("output") or ""))
    if payload.get("brand") != "sonia_travel_vlogs" or not package.is_file():
        return _local_plan(job)
    upstream = "ARES" if payload.get("stage") == "vista_short_publish" else "LYRA"
    stages.worker_confirms_receipt(
        "echo", f"Received {upstream}'s QC-passed package for subtitles and private distribution completion"
    )
    try:
        from openjarvis.one_agents import youtube_distribution, youtube_publish
        stages.set_stage("echo", stages.EXECUTING, "Uploading the governed private draft")
        gate = youtube_publish.autopilot_upload(package)
        if gate.get("status") not in ("uploaded_private", "already_uploaded"):
            raise RuntimeError("private upload gate did not complete: " + str(gate.get("status")))
        stages.set_stage("echo", stages.EXECUTING,
                         "Adding subtitles, requested languages and the channel comment")
        result = youtube_distribution.complete(package)
        # The last step of Sonia's video, so the residue goes here: whether this pass uploaded the cut or found it
        # already on YouTube. Until 2026-10-08 cleanup ran only inside a fresh upload, so a re-checked video
        # (status already_uploaded) kept its ~2 GB of intermediates forever.
        stages.set_stage("echo", stages.EXECUTING, "Clearing intermediates the finished video no longer needs")
        storage = youtube_publish.cleanup_after_upload(gate) if gate.get("master") else {}
        stages.set_stage("echo", stages.CARRYING_TO_HEAD, "Taking the completed private draft back to HELIOS")
        _require_active_job(job, "report distribution completion to HELIOS")
        report = enqueue_job("helios", json.dumps({**payload, "stage": "distribution_complete",
            "format": "youtube_private_draft", "worker": "echo", "distribution": result,
            "storage_cleanup": storage, "published": False, "output": str(package)}), mode="report", tier="fast",
            dedupe_key=f"travel:{payload.get('lao_job')}:distribution-report")
        return {"agent": "ECHO", **result, "storage_cleanup": storage,
                "handed_to": {"agent": "HELIOS", "job_id": report["id"]}}
    finally:
        stages.clear_stage("echo")


def _load_vista_runner() -> Any:
    """Load VISTA's production module without importing its repository as a package."""
    runner_path = Path(os.environ.get("VISTA_RUNNER", r"C:\Users\pc\Documents\LAO\vista\production.py"))
    if not runner_path.is_file():
        raise RuntimeError(f"VISTA production runner is missing: {runner_path}")
    spec = importlib.util.spec_from_file_location("vista_production", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load VISTA production runner: {runner_path}")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


def _run_vista(job: dict[str, Any]) -> dict[str, Any]:
    """Run one HELIOS-researched Short through media, then hand its checkpoint to ARES."""
    payload = _json_task(job)
    if payload.get("brand") != "sonia_travel_vlogs" or payload.get("content_format") != "youtube_short":
        raise RuntimeError("VISTA only accepts Sonia Travel Vlogs youtube_short briefs from HELIOS")
    slot = str(payload.get("slot") or "")
    if slot not in {"0900", "1300", "1800"}:
        raise RuntimeError("VISTA brief has no valid 0900, 1300 or 1800 slot")
    evidence = Path(str(payload.get("evidence_path") or ""))
    if not evidence.is_file() or int(payload.get("evidence_count") or 0) < 1:
        raise RuntimeError("VISTA requires HELIOS's non-empty Sanjeevani evidence receipt")
    origin = str(payload.get("origin_job") or "")
    trigger_id = f"daily-vista-short-{slot}"
    publish_authorized = _job_fired_by_trigger(trigger_id, origin)
    if not publish_authorized:
        raise RuntimeError(f"VISTA slot {slot} has no authentic {trigger_id} fire receipt")

    stages.worker_confirms_receipt("vista", f"Received HELIOS's researched {slot} Short brief")
    try:
        stages.set_stage("vista", stages.EXECUTING, "Producing the slot-bound vertical Short and QC package")
        # VISTA's production runner checkpoints by this job's stable story slug
        # and reuses its saved spec, narration segments and acquired clips on a
        # retry.  Register that durable ownership before entering the runner so
        # restart recovery can requeue this same job instead of treating it as
        # an unknown external start and abandoning the checkpoint.
        recovery_id = job_recovery.resume_target(job) or f"vista:{job['id']}"
        job_recovery.attach(_connect, str(job["id"]), recovery_id,
                            kind="vista_checkpoint")
        runner = _load_vista_runner()
        stages.set_stage("vista", stages.EXECUTING, "Researching and writing the Short with LAO's ChatGPT")
        from openjarvis.one_agents import resource_lanes
        stages.set_stage("vista", stages.EXECUTING,
                         "Waiting for VISTA's own Envato session")
        with resource_lanes.claim(
            "browser:vista-envato",
            heartbeat=lambda: job_recovery.heartbeat(_connect, str(job["id"])),
            cancelled=lambda: not _job_is_active(str(job["id"])),
        ):
            stages.set_stage("vista", stages.EXECUTING,
                             "Producing with VISTA's isolated browser and Envato lane")
            result = runner.run({**payload, "publish_authorized": True, "trigger_id": trigger_id,
                                 "_writer": _vista_chatgpt})
        handoff = result.get("handoff") if isinstance(result, dict) else None
        if (not isinstance(result, dict) or result.get("status") != "thumbnail_ready"
                or not isinstance(handoff, (dict, str)) or not handoff):
            raise RuntimeError("VISTA did not produce a durable thumbnail/SEO handoff")
        stages.set_stage("vista", stages.CARRYING_TO_HEAD,
                         "Taking the saved Short to ARES for thumbnail and SEO")
        _require_active_job(job, "hand the saved Short to ARES")
        ares_job = enqueue_job(
            "ares", json.dumps({**payload, "stage": "vista_thumbnail_seo", "handoff": handoff,
                                 "publish_authorized": True, "trigger_id": trigger_id,
                                 "vista_job": job.get("id")}),
            # A saved HELIOS brief may be intentionally rebuilt after its private
            # draft is withdrawn.  The HELIOS origin is still the same authentic
            # trigger receipt, but the VISTA run and handoff are new.  Keying only
            # on origin+slot returned the *completed ARES job from the old cut*,
            # silently stranding the fresh handoff.  Keep retries of this exact
            # VISTA job idempotent while allowing a later VISTA successor to move.
            mode="execute", tier="fast",
            dedupe_key=f"vista:{origin}:{slot}:{job.get('id')}:thumbnail-seo")
        return {"agent": "VISTA", **result,
                "handed_to": {"agent": "ARES", "job_id": ares_job["id"]}}
    finally:
        stages.clear_stage("vista")


def _vista_chatgpt(prompt: str) -> tuple[str, str]:
    """VISTA's script writer: LAO's logged-in ChatGPT session (the one YATRA, KAIROS and PEITHO already use).

    A worker may write with it; the floor head HELIOS stays local. ChatGPT can open the story's article and the
    official page, which a model given only the headline cannot."""
    output, error = _run_peitho_lao_draft([prompt], expected_markers=["BEGIN_VISTA_JSON", "END_VISTA_JSON"],
                                          timeout_ms=420000)
    return str(output.get("angle_1") or ""), error


def _vista_spec_from_brief(brief: str, slot: str, lane: str, hook: str) -> dict[str, Any]:
    """HELIOS's typed hand-off to VISTA: the verified story and the slot's contract - never a script.

    2026-10-13: the previous adapter cut IRIS's own brief into sentences and used them as the Short's spoken lines,
    title, thumbnail headline and Envato queries. IRIS's brief is reasoning about the pick, so VISTA voiced "The total
    viral score is 15.25." in Sonia's voice (16 ElevenLabs segments on two runs), titled the Short "The hook is
    derived directly from the headline...", and searched Envato for that sentence. The script is now VISTA's
    writer's job (a worker, allowed to use LAO's ChatGPT, which can open the article and the official source);
    IRIS only passes what it actually established: the chosen headline, place, sources, search terms and the
    slot's contract. VISTA refuses to voice anything until its writer's script passes validation.
    """
    text = str(brief or "").strip()
    if not text:
        raise RuntimeError("HELIOS cannot build a VISTA production_spec from an empty brief")

    def section(name: str) -> str:
        match = re.search(rf"(?ims)^###\s*{re.escape(name)}\s*$\s*(.+?)(?=^###\s|^##\s|\Z)", text)
        return match.group(1).strip() if match else ""

    chosen = re.search(r"Chosen from today's scored travel news:\s*(.+?)\s*\(score", text)
    hook_section = section("Strongest Truthful Hook")
    quoted_hook = re.search(r'\*\*"([^"]{12,200})"\*\*', hook_section)
    # The evergreen synthesizer commonly emits TrendBrief fields as bold
    # labels rather than Markdown headings. This remains explicit authored
    # evidence, not a destination-derived guess: accept only the named field
    # and, when present, its quoted hook text.
    hook_field = re.search(
        r'(?im)^[ \t]*(?:\*\*)?Strongest Truthful Hook:(?:\*\*)?[ \t]*(\S[^\r\n]*)$', text)
    hook_field_value = hook_field.group(1).strip() if hook_field else ""
    hook_field_quote = re.search(r'"([^"]{12,200})"', hook_field_value)
    # Evergreen briefs do not have a scored-news receipt. Require an explicit
    # chosen headline instead of depending on incidental bold/quote styling,
    # or guessing one from the destination or the head's reasoning.
    explicit = re.search(
        r"(?im)^[ \t]*(?:\*\*)?Chosen headline:(?:\*\*)?[ \t]*(\S[^\r\n]*)$", text)
    headline = (chosen.group(1) if chosen else
                explicit.group(1).strip(' *"') if explicit else
                quoted_hook.group(1) if quoted_hook else
                hook_field_quote.group(1) if hook_field_quote else
                hook_field_value.strip(' *"')).strip()
    if not headline:
        raise RuntimeError("HELIOS brief names no chosen story headline; VISTA cannot be briefed on a guess")
    place = re.search(r"(?im)^\**Destination/Topic:?\**:?\s*(.+)$", text)
    destination = re.sub(r"\s*\(.*$", "", place.group(1)).strip(" *.") if place else ""
    if not destination:
        destination = re.sub(r"\s+", " ", section("Destination/Topic")).split(".")[0].strip(" *-")
    # ``Destination/Topic`` may include an explanatory topic after a pipe;
    # VISTA's geographic contract needs the explicit place on the left.
    destination = re.split(r"\s*[|–—]\s*", destination, maxsplit=1)[0].strip()
    search_source = section("Viral Search Terms")
    if not search_source:
        search_line = re.search(
            r"(?im)^[ \t]*(?:\*\*)?Viral Search Terms:(?:\*\*)?[ \t]*(\S[^\r\n]*)$", text)
        search_source = search_line.group(1) if search_line else ""
    search_terms = [t.strip() for t in re.findall(r'"([^"\n]{3,80})"', search_source)][:8]
    urls = []
    for url in re.findall(r"https?://[^\s)>\]]+", text):
        url = url.rstrip(".,;")
        if url not in urls and "youtube.com/watch" not in url:
            urls.append(url)
    contract = re.search(r"(?s)# VISTA SLOT CONTRACT\n(.+?)\n\n", text)
    slug_seed = re.sub(r"[^a-z0-9]+", "-", headline.lower()).strip("-")[:58]
    # Portrait identity stays fixed, but the performance direction rotates by
    # slot so a day's Shorts do not all show the same raised-finger pose.
    performance = {
        "0900": {
            "expression": "genuinely surprised, raised brows and alert eyes; identity unchanged",
            "gesture": "one hand lightly covering the mouth in surprise; the other hand relaxed and visible",
            "posture": "front-facing close portrait with a slight lean toward the hook",
            "outfit_colour": "emerald green",
        },
        "1300": {
            "expression": "concerned warning expression, focused eyes; identity unchanged",
            "gesture": "open-palm STOP gesture beside the headline; no pointing finger",
            "posture": "upright three-quarter portrait on the right, shoulders and full hand visible",
            "outfit_colour": "royal blue",
        },
        "1800": {
            "expression": "excited reveal, wide eyes and confident smile; identity unchanged",
            "gesture": "both palms open in a presenting reveal toward the destination; no pointing finger",
            "posture": "energetic three-quarter portrait on the right with both hands inside frame",
            "outfit_colour": "bright red",
        },
    }.get(slot, {
        "expression": "curious and skeptical, one eyebrow raised; identity unchanged",
        "gesture": "one hand at the chin in a thinking pose; no pointing finger",
        "posture": "upright three-quarter portrait on the right, shoulders visible",
        "outfit_colour": "bright red",
    })
    return {"slug": f"{slug_seed or 'travel-update'}-{slot}", "slot": slot,
            "angle": lane, "hook": hook, "slot_contract": contract.group(1).strip() if contract else "",
            "story": {"headline": headline, "destination": destination[:80], "search_terms": search_terms,
                      "source_urls": urls[:12]},
            "script_source": "vista_writer_required",
            "sources": urls[:12],
            # The headline is written by VISTA's writer with the script; everything else about the look is IRIS's.
            "thumbnail_brief": {"headline": "", **performance,
                                "background": f"high-contrast destination context for {destination[:80]}, uncluttered"},
            "footage_contract": {"provider": "Envato", "orientation": "Vertical",
                                 "resolution": "1080 x 1920", "unique_clips": 8,
                                 "fresh_for_each_short": True}}


def _run_alfa(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 2 - publishing economics or the existing local plan."""
    payload = _json_task(job)
    if payload.get("workflow") == "publishing_portfolio":
        title = str(payload.get("title") or "(untitled)")
        economics = {
            "title": title, "currency": "USD", "price": None,
            "status": "PROPOSAL", "price_change_executed": False,
            "required_metrics": ["royalty", "ad_spend", "read_through", "refunds"],
            "note": "Price remains unset until title format, page count and royalty band are known.",
        }
        scribe_id = str(payload.get("scribe_job_id") or "")
        if not scribe_id:
            raise RuntimeError("Publishing economics has no SCRIBE job to release to upload review")
        current = get_job(scribe_id)
        if not current or current.get("status") != "awaiting_growth_review":
            raise RuntimeError(f"SCRIBE job {scribe_id} is not awaiting growth review")
        result = _json_task({"task": current.get("result") or "{}"})
        result.update({"distribution": payload.get("distribution"), "economics": economics,
                       "requires_human": "Amazon KDP upload -- growth and rights review passed"})
        mark_awaiting_upload(scribe_id, result)
        publisher_job = enqueue_job("imprimatur", json.dumps({
            "phase": "prepare", "run_dir": result.get("run_dir"),
            "scribe_job_id": scribe_id, "title": title,
        }), mode="execute", tier="heavy")
        stages.set_stage("scribe", stages.AWAITING_UPLOAD,
                         f"“{title}” cleared review — IMPRIMATUR is preparing the KDP draft")
        _publishing_event(job, agent="ALFA", event_type="economics_proposal",
                          stage="economics_gate", summary="Economics reviewed; manual upload gate opened",
                          details=economics, status="awaiting_approval")
        return {"agent": "ALFA", "economics": economics,
                "released_job": scribe_id,
                "handed_to": {"agent": "IMPRIMATUR", "job_id": publisher_job["id"]},
                "content": "Economics proposal attached; KDP draft preparation started."}
    return _local_plan(job)


# The exact objective text a human already ran three times by hand through
# the company-plane CLI (poseidon-ba75d185938b, -eb7f3fcadc52, -9677d9b83977
# -- all completed) before this trigger existed. Reused verbatim rather than
# reworded, since TRITON's own keyword-based job-hunt detection in
# floors/_work/handlers/executive.py matches on this exact proven phrasing.
_SONIA_JOB_HUNT_OBJECTIVE = (
    "Run the corrected end-to-end governed Sonia Chauhan job hunt using her "
    "verified canonical resume and structured verified profile. Research "
    "fresh Manual Testing, Automation Testing, Database Testing, and "
    "Product Owner roles in India through Sanjeevani, apply freshness "
    "gates, deduplicate and rank, then hand qualifying dated openings to "
    "CLIO for truthful local resume evidence packets. Do not email or "
    "submit applications without OLYMPUS approval."
)


def _run_poseidon(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 1 - Corporate Services.

    Bridges a scheduled Sonia Chauhan job-hunt trigger into the governed
    company plane via floors_bridge.dispatch_company_job() -- the exact CLI
    path a human already ran by hand three times before this trigger
    existed, now on a schedule. Everything else POSEIDON might be asked is
    still "Pending LAO integration", same as before.

    The company plane is a completely separate dispatch system from this
    runtime-plane queue: its own company_jobs.db, its own fail-closed
    evaluate()/dispatch() gate (floors/_work/dispatch.py), its own standing
    floors/_work/worker.py poller. This function's only real job is
    deciding whether to start a new cycle at all -- checked against
    company_jobs.db directly first, since a cycle can sit genuinely open
    for days at CLIO's own A2 resume-review gate, and firing a second one
    on top would research the same roles twice and leave two cycles for a
    human to untangle instead of one to approve.
    """
    task = str(job.get("task") or "")
    if "sonia" in task.lower() and "job hunt" in task.lower():
        return _poseidon_sonia_job_hunt(job)
    return _local_plan(job)


def _poseidon_sonia_job_hunt(job: dict[str, Any]) -> dict[str, Any]:
    stages.worker_confirms_receipt(
        "poseidon", "Checking for an already-open Sonia Chauhan job-hunt cycle")
    company_db = _home() / "company_jobs.db"
    open_cycle = None
    if company_db.is_file():
        try:
            con = sqlite3.connect(str(company_db))
            try:
                open_cycle = con.execute(
                    "SELECT job_id, status FROM jobs WHERE assigned_to='poseidon' "
                    "AND floor_id='1' AND status NOT IN ('completed','cancelled') "
                    "AND objective LIKE '%Sonia%job hunt%' LIMIT 1"
                ).fetchone()
            finally:
                con.close()
        except Exception as exc:
            stages.clear_stage("poseidon")
            return {
                "agent": "POSEIDON", "mode": "blocked", "_blocked": True,
                "content": "Could not check the company plane for an open Sonia job-hunt cycle.",
                "blocked_reason": f"{type(exc).__name__}: {exc}",
            }
    if open_cycle:
        stages.clear_stage("poseidon")
        return {
            "agent": "POSEIDON", "mode": "skipped",
            "content": (f"A Sonia Chauhan job-hunt cycle is already open "
                        f"({open_cycle[0]}, {open_cycle[1]}) -- not starting a second "
                        "one on top of it."),
            "existing_job_id": open_cycle[0], "existing_status": open_cycle[1],
        }

    stages.set_stage("poseidon", stages.CARRYING_TO_WORKER,
                     "Starting a governed Sonia Chauhan job-hunt cycle", worker="triton")
    result = floors_bridge.dispatch_company_job(
        agent_id="poseidon", floor_id="1", objective=_SONIA_JOB_HUNT_OBJECTIVE,
        capability="network:fetch", action="internal_analysis",
    )
    stages.clear_stage("poseidon")
    if not result or not result.get("ok"):
        error = (result or {}).get("error") or "company-plane dispatch bridge unavailable"
        return {
            "agent": "POSEIDON", "mode": "blocked", "_blocked": True,
            "content": "Could not start the Sonia Chauhan job-hunt cycle.",
            "blocked_reason": error,
        }
    return {
        "agent": "POSEIDON", "mode": "execute",
        "content": f"Started a governed Sonia Chauhan job-hunt cycle: {result.get('job_id') or '(id not parsed)'}.",
        "company_job_id": result.get("job_id"),
        "note": ("POSEIDON → TRITON → CLIO on the company plane; CLIO stops for an "
                 "owner resume review before anything leaves ONE."),
    }


def _run_argus(job: dict[str, Any]) -> dict[str, Any]:
    """Floor B2 - Security & SRE. Pending LAO integration."""
    return _local_plan(job)


def _run_beta(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 7 - Digital Utilities. Pending LAO integration."""
    return _local_plan(job)


def _run_hephaistos(job: dict[str, Any]) -> dict[str, Any]:
    """Floor B1 - Platform Engineering. Pending LAO integration.

    The old body of this function called LaoOrchestratorTool directly to
    start a real LAO job. That's intentionally retired for now — LAO stays
    untouched and unwired until the full floor set is built, at which point
    the LaoOrchestratorTool call is the natural thing to reintroduce here.
    """
    return _local_plan(job)


def _run_titan(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 8 - Apps / Websites / Games. Pending LAO integration.

    The old body of this function called the PostForge API directly
    (refresh -> generate -> carousel-images -> instagram). Retired for now,
    same reasoning as _run_hephaistos above.
    """
    return _local_plan(job)


SONIA_COMMENT_SWEEP = "[sonia-comment-sweep]"


def _youtube_sonia_brand() -> dict[str, Any]:
    """Stable channel contract used by HELIOS without Floor 4's brand router."""
    return {
        "slug": "sonia_travel_vlogs",
        "display_name": "Sonia Travel Vlogs",
        "worker_agent_id": "fabula",
        "vault_floor_name": "YouTube Studio (Sonia Travel Vlogs)",
        "social_channel_slug": "sonicsonia",
        "status": "live",
    }


def _iris_comment_sweep(job: dict[str, Any], *, head_id: str = "ia",
                        head_name: str = "IRIS") -> dict[str, Any]:
    """Hourly: when a Sonia video still owes its channel comment, brief ECHO to post it once the video is public.

    Uploads are private and YouTube disables comments on a private video, so the comment can only go up after a
    person makes the video public in Studio. Nothing did that until 2026-10-09: Air France went public with no
    comment. IRIS reads the upload ledger first (local, instant) and only walks to ECHO when something is owed."""
    from openjarvis.one_agents import youtube_publish
    try:
        ledger = youtube_publish._load("youtube_api_upload").ledger_load()
    except Exception as exc:  # noqa: BLE001
        return {"agent": head_name, "mode": "comment_sweep", "content": f"Upload ledger unreadable: {exc}"[:300]}
    uploader = youtube_publish._load("youtube_api_upload")
    owed = [entry.get("video_id") for _, entry in uploader.pending_comment_entries(ledger)]
    # The same sweep finishes metadata languages a Short's upload ran out of time for (2026-10-13): nothing added
    # them afterwards, so a video could stay with 8 of its 14 languages for good.
    languages = [entry.get("video_id") for _, entry, _ in uploader.pending_localization_entries(ledger)]
    # Then The Planexium, its own channel, credential and per-mission ledgers (Chairman, 2026-10-22: one channel
    # after the other, never merged). Planexium trouble never stops Sonia's sweep.
    try:
        from openjarvis.one_agents import planexium
        planexium_owed = planexium.pending_comment_videos()
    except Exception:  # noqa: BLE001
        planexium_owed = []
    if not owed and not languages and not planexium_owed:
        return {"agent": head_name, "mode": "comment_sweep",
                "content": "No Sonia or Planexium video owes a channel comment or a metadata language."}
    follow = stages.head_briefs_worker(
        head_id, "echo", carrying_detail="Taking the owed channel comments and languages to ECHO",
        briefing_detail=(f"ECHO, post the channel comment on any of {len(owed)} Sonia and {len(planexium_owed)} "
                         f"Planexium video(s) now public, and add the missing languages on {len(languages)} upload(s)."),
        awaiting_detail="Waiting on ECHO for channel comments and languages",
        enqueue=lambda: enqueue_job("echo", json.dumps({"brand": "sonia_travel_vlogs", "stage": "pending_comments",
                                                         "videos": owed, "languages": languages,
                                                         "planexium": planexium_owed}),
                                    mode="execute", tier="fast", dedupe_key=f"sonia:comments:{job['id']}"))
    return {"agent": head_name, "mode": "comment_sweep", "owed": owed, "languages": languages,
            "planexium_owed": planexium_owed,
            "handed_to": {"agent": "ECHO", "job_id": follow["id"]},
            "content": (f"{len(owed)} Sonia and {len(planexium_owed)} Planexium video(s) owe a channel comment; "
                        f"{len(languages)} upload(s) owe languages. ECHO posts each comment once the video is public "
                        "and adds the languages.")}


def _iris_community_poll(job: dict[str, Any], *, head_id: str = "ia",
                         head_name: str = "IRIS") -> dict[str, Any]:
    """Daily: brief ECHO on today's image poll for Sonia's YouTube Community tab.

    The Chairman approved one public poll a day with no per-post approval (2026-10-09). IRIS stays local: the brief
    is the weekday's format, the latest Sanjeevani story ranking (fresh discovery only when none is under three
    days old), the next festival and the places used lately. ECHO writes, illustrates and posts it."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from openjarvis.one_agents import sonia_community
    today = _dt.now(_tz(_td(hours=5, minutes=30))).date()

    def discover() -> list[dict[str, Any]]:
        travel, reusable = _sanjeevani_travel(), _sanjeevani_research()
        if travel is None or reusable is None:
            return []
        return travel.discover(reusable, top_n=12)["candidates"]

    stages.set_stage(head_id, stages.EXECUTING, "Choosing today's community poll for Sonia's channel")
    try:
        brief = sonia_community.brief_for(today, _home() / "agent_outputs", discover=discover)
    except Exception as exc:  # noqa: BLE001
        stages.clear_stage(head_id)
        return {"agent": head_name, "mode": "community_poll", "_blocked": True,
                "content": f"Community poll brief failed: {exc}"[:300]}
    # The standing approval is for the daily schedule only, proven by the scheduler's own fire receipt (as for
    # KAIROS's carousel). Any other run - typed by hand, retried, dispatched from the building - is a dry run:
    # ECHO fills the composer and cancels, and posting it still needs OLYMPUS.
    brief["publish_authorized"] = _job_fired_by_trigger("daily-sonia-community-poll", str(job.get("id") or ""))
    follow = stages.head_briefs_worker(
        head_id, "echo", carrying_detail="Taking today's community poll to ECHO",
        briefing_detail=f"ECHO, post today's {brief['format'].replace('_', ' ')} image poll on Sonia's channel.",
        awaiting_detail="Waiting on ECHO to post the community poll",
        enqueue=lambda: enqueue_job("echo", json.dumps({"brand": "sonia_travel_vlogs", "stage": "community_poll",
                                                         "brief": brief}, ensure_ascii=False),
                                    mode="execute", tier="fast", dedupe_key=f"sonia:community:{brief['today']}"))
    return {"agent": head_name, "mode": "community_poll", "brief": brief,
            "handed_to": {"agent": "ECHO", "job_id": follow["id"]},
            "content": f"Today's poll is a {brief['format'].replace('_', ' ')} poll; ECHO writes, illustrates and posts it."}


def _run_helios(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 12 head for all YouTube channel flows."""
    task = str(job.get("task") or "")
    mode = str(job.get("mode") or "plan").strip().lower()
    payload = _json_task(job)
    if payload.get("brand") == "origin_to_ovation":
        from openjarvis.one_agents.origin_to_ovation import run_stage
        return run_stage(job, enqueue=enqueue_job)
    if payload.get("brand") == "planexium" or (not payload and "planexium" in task.casefold()):
        from openjarvis.one_agents.planexium import head_job
        return head_job(job, enqueue=enqueue_job)
    brand = _youtube_sonia_brand()
    # Stage is authoritative. A malformed handoff once sent seo_complete as
    # execute, which fell through into fresh discovery and commissioned a
    # second FABULA/YATRA chain. Downstream receipts can only be reconciled;
    # they can never start research again regardless of their mode field.
    report_stages = {"seo_complete", "distribution_complete", "production_complete"}
    if mode == "report" or str(payload.get("stage") or "") in report_stages:
        return _iris_report_brand(
            job, brand, head_id="helios", head_name="HELIOS", floor_id="12",
        )
    if SONIA_COMMENT_SWEEP in task:
        return _iris_comment_sweep(job, head_id="helios", head_name="HELIOS")
    if "[sonia-community-poll]" in task:
        return _iris_community_poll(job, head_id="helios", head_name="HELIOS")
    return _iris_dispatch_brand(
        job, brand, head_id="helios", head_name="HELIOS", floor_id="12",
    )


def _run_iris(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 4 head - decides the next reel, then hands it to MUSE.

    Deliberately the same shape as _run_hermes one floor up: IRIS researches
    what is worth shooting, walks the brief to the worker, and waits. MUSE
    drives LAO's ImagineIndia pipeline to completion and walks the finished
    reel back. IRIS then reports upward.

    ``mode='report'`` is the third leg, enqueued by MUSE once the reel exists;
    it is not something a person dispatches by hand.

    ImagineIndia's own 3x/day LAO triggers are untouched by this -- they keep
    running on their schedule. This is the on-demand path through the floor.
    """
    task = str(job.get("task") or "")
    mode = str(job.get("mode") or "plan").strip().lower()

    # A channel Floor 4 no longer owns is declined with a pointer. Without
    # this, text the brand router cannot place falls through to the
    # ImagineIndia reel path below. LinkedIn Authority moved to ARES
    # (Floor 3) on 2026-10-13; the registry in floor_04_media/brands.json
    # names where each moved channel went.
    _moved_router = floors_bridge.load("floor_04_media", "brand_router")
    if _moved_router is not None and hasattr(_moved_router, "moved_channel"):
        try:
            _payload = json.loads(task)
        except json.JSONDecodeError:
            _payload = {}
        _explicit = _payload.get("brand") if isinstance(_payload, dict) else None
        _moved = _moved_router.moved_channel(task, explicit=_explicit)
        if _moved:
            stages.clear_stage("ia")
            _to = str(_moved.get("to_head_agent_id") or "").upper()
            return {"agent": "IRIS", "mode": "blocked", "_blocked": True,
                    "content": (f"{_moved['slug']} is no longer a Floor 4 channel; it moved to Floor "
                                f"{_moved.get('to_floor_id')} ({_to}) on {_moved.get('moved_on')}. Nothing dispatched."),
                    "blocked_reason": f"channel moved to {_to}", "handed_to": None}

    if mode == "report":
        # A revenue review is not a post: it gets its own report, whichever
        # brand it is about.
        try:
            report_payload = json.loads(str(job.get("task") or "{}"))
        except json.JSONDecodeError:
            report_payload = {}
        if isinstance(report_payload, dict) and report_payload.get("format") in (
                "revenue_review", "revenue_pulse", "product_pack"):
            return _iris_report_revenue(job, report_payload)
        # The hand-back leg has to be routed too. _iris_report below is written
        # for ImagineIndia specifically -- its wording, tags and vault folder
        # are all that brand -- so a report from another brand's worker filed
        # there wrongly, and its ANGLE line then polluted ImagineIndia's own
        # dedupe history. Confirmed live 2026-08-20 on job kairos-2d421bff5888.
        report_brand, _ = floors_bridge.route_media("", job)
        if report_brand and report_brand.get("slug") != "imagineindia":
            return _iris_report_brand(job, report_brand)
        return _iris_report(job)

    # Floor 4 serves two brands with two workers. This routing is deliberately
    # additive: an ImagineIndia request -- or anything the floors tree cannot
    # answer -- falls straight through to the original path below, unchanged.
    # Money work never enters a production pipeline: "make ImagineIndia money"
    # must not start an ImagineIndia reel. It goes to the brand's revenue agent.
    revenue_router = floors_bridge.load("floor_04_media", "brand_router")
    if (revenue_router is not None and hasattr(revenue_router, "revenue_intent")
            and revenue_router.revenue_intent(task)):
        return _iris_dispatch_revenue(job, revenue_router.revenue_brand(task))

    if SONIA_COMMENT_SWEEP in task:
        return _iris_comment_sweep(job)
    if "[sonia-community-poll]" in task:
        return _iris_community_poll(job)

    brand, question = floors_bridge.route_media(task, job)
    if question:
        stages.clear_stage("ia")
        return {
            "agent": "IRIS",
            "mode": "blocked",
            "_blocked": True,
            "content": question,
            "blocked_reason": question,
            "handed_to": None,
            "note": "Nothing dispatched - the brand was unclear.",
        }
    if brand and brand.get("slug") != "imagineindia":
        return _iris_dispatch_brand(job, brand)

    stages.set_stage("ia", stages.RESEARCHING,
                     task.strip()[:180] or "Choosing the next ImagineIndia reel")

    # Same reasoning as HERMES reading its own prior titles: without this the
    # floor cheerfully re-shoots a location it already published.
    already = memory.prior_titles("4", "Media & Content (ImagineIndia)")
    avoid = (
        "\n\nAlready produced by this floor — do not repeat or closely "
        "overlap these:\n" + "\n".join(f"- {t}" for t in already[:15])
        if already else ""
    )

    # Media research follows the same Sanjeevani contract as Publishing:
    # capture current public evidence first, then let an approved local Ollama
    # model interpret only that snapshot.  Paid providers are never consulted
    # Cloud-model fallback is forbidden for autonomous floor work.
    #
    # Category-query discipline (added 2026-09-12): a single collect() call
    # built from the whole task sentence returned almost nothing eligible in
    # a live comparison, because query_plan() requires lexical overlap with
    # real headlines. imagineindia-trend-radar (this floor's own skill, see
    # _media_skill_text below) runs four short targeted category queries
    # instead and merges them -- see that skill's SKILL.md for why.
    media_evidence: dict[str, Any] = {"eligible": [], "catalog_evidence": [], "categories": {}}
    reusable = _sanjeevani_research()
    _early = task.lower()
    discovery_mode = bool(re.search(r"\b(news.?hook|hook.?reel)\b", _early)
                          and not re.search(r"\b(carousel|slides?|swipe|spotlight)\b", _early))
    discovered: dict[str, Any] = {}
    if discovery_mode:
        stages.set_stage("ia", stages.RESEARCHING, "Scanning today's India-wide trending stories")
        discovered = _iris_news_hook_discovery(avoid)
    if reusable is not None and not discovery_mode:
        try:
            media_evidence = _media_trend_evidence(reusable)
        except Exception as exc:  # evidence failure is surfaced by synthesis
            media_evidence = {
                "eligible": [], "catalog_evidence": [], "categories": {},
                "errors": [{"source": "sanjeevani", "error": f"{type(exc).__name__}: {exc}"[:400]}],
            }

    # Location-aware research (added 2026-09-13, see _peek_next_ia_location's
    # docstring): the 4 category queries above find macro trends untethered
    # to any specific place, which the Bible's Frame-1 rule ("a real local
    # problem at whatever location the rotation lands on") almost never lets
    # ChatGPT honestly connect to. Predicting the real next location and
    # researching THAT place by name gives evidence with an actual chance of
    # a genuine connection, instead of hoping a floating theme happens to fit.
    # Learn from ImagineIndia's own reels first (once a day), so the prediction
    # below and LAO's real pick both use today's performance weights.
    try:
        learning_note = _refresh_imagineindia_learning()
        if learning_note:
            print(f"[one-agents] IRIS ImagineIndia learning: {learning_note}", flush=True)
    except Exception as exc:  # noqa: BLE001 - learning must never stop IRIS
        print(f"[one-agents] IRIS ImagineIndia learning skipped: {type(exc).__name__}: {exc}"[:400], flush=True)
    predicted_location = _peek_next_ia_location(IA_LOCATIONS_MANIFEST_PATH)
    if predicted_location and predicted_location.get("name") and reusable is not None and not discovery_mode:
        try:
            loc_query = (
                f"{predicted_location['name']} {predicted_location.get('state', '')} "
                "India news conservation restoration heritage controversy"
            ).strip()
            snapshot = reusable.collect(loc_query, markets=["IN"])
            loc_items = list(snapshot.get("eligible") or [])
            for item in loc_items:
                item["category"] = "predicted_location"
            media_evidence.setdefault("eligible", []).extend(loc_items)
            media_evidence.setdefault("categories", {})["predicted_location"] = {
                "query": loc_query,
                "eligible_count": len(loc_items),
                "commissioning_eligible": bool(
                    (snapshot.get("corroboration") or {}).get("commissioning_eligible")
                ),
            }
        except Exception as exc:  # noqa: BLE001
            media_evidence.setdefault("categories", {})["predicted_location"] = {
                "query": f"{predicted_location.get('name')}", "eligible_count": 0,
                "commissioning_eligible": False,
                "error": f"{type(exc).__name__}: {exc}"[:400],
            }

    # Ordering matters (fixed 2026-09-12 after a live failure): the prompt
    # used to put "Reply in exactly this shape" BEFORE the evidence dump, so
    # the evidence was the last thing the model read before generating -- it
    # produced an accurate, well-cited, entirely free-form summary instead of
    # the required PRIORITY/REGION/ANGLE shape every time. This is the exact
    # failure mode ollama_synthesize's own docstring already warns about for
    # every Sanjeevani caller: "keeping the required output shape last
    # prevents a large evidence bundle from silently deleting the agent's
    # contract." Evidence now comes first; the reply-shape spec is the last
    # thing in the prompt.
    brief, note = (discovered.get("brief", ""), discovered.get("note", "")) if discovery_mode else _research_synthesis(
        "You are IRIS, head of Media & Content at a digital holding company, "
        "signing off the next ImagineIndia Instagram reel run.\n\n"
        f"Request: {task}\n\n"
        "ImagineIndia posts cinematic short 'restoration story' reels about real "
        "Indian places. IMPORTANT: you do NOT choose the location. The pipeline "
        "picks it deterministically from a zoned manifest so that no place "
        "repeats and all of India is covered over successive weeks. Your job is "
        "the editorial call around the run, not the pick.\n\n"
        "Decide: is now the right time to produce another reel, and what should "
        "this run prioritise editorially? Do not invent internal teams or tools "
        "— production is an automated pipeline.\n\n"
        f"Floor-owned operating method:\n{_media_skill_text()}\n\n"
        + (
            f"PREDICTED NEXT LOCATION: {predicted_location['name']}, "
            f"{predicted_location.get('state', '')} (a live, read-only prediction of the "
            "deterministic rotation's next pick -- not a guarantee, it can shift if "
            "another run consumes a manifest slot first). Evidence tagged "
            "category='predicted_location' below is research specifically about this "
            "real place, not a floating theme -- the IA Bible requires Frame 1's "
            "conflict to be a genuine LOCAL problem at whichever place actually gets "
            "used, so an angle grounded in this place has a real chance of an honest "
            "connection where a generic macro-trend almost never does. Strongly prefer "
            "building PRIORITY/ANGLE from this evidence when it has anything usable; "
            "fall back to the general category evidence only when it does not, and say "
            "so honestly in BRIEF rather than forcing a connection.\n\n"
            if predicted_location and predicted_location.get("name")
            else "PREDICTED NEXT LOCATION: unavailable this run (manifest unreadable) -- "
            "fall back to general trend evidence only.\n\n"
        )
        + "Use only this Sanjeevani-captured evidence for current-market claims. "
        "Each item is tagged with the category query that found it. Cite an "
        "evidence_id in brackets for every specific factual claim; do not "
        "invent people, quotes, figures, or scenarios not present here:\n"
        + json.dumps(_compact_media_evidence(media_evidence), ensure_ascii=False, separators=(",", ":"))
        + avoid
        + "\n\nYou already have everything above -- the location catalogue, the "
        "evidence, and the operating method. Do not write a free-form summary "
        "of the evidence. Reply with ONLY the following nine lines, nothing "
        "before or after them:\n"
        "PRIORITY: <one line — what this run should optimise for>\n"
        "REGION: <the zone you'd prefer if it were free, or 'rotation'>\n"
        "ANGLE: <one line — the editorial through-line to aim for; grounded in the "
        "predicted location's own evidence when available>\n"
        "VIRAL_SCORE: <0-100 estimate against the Bible's Recognition/Emotion/"
        "Visible-Problem/Transformation/Comment-Potential/Human-Experience rubric>\n"
        "SACRED_SITE: <none, or which protocol element applies and how the "
        "angle already respects it>\n"
        "BRIEF: <6-12 lines: who the audience is, why run now, what would make "
        "this one perform, and the honest risk that it underperforms>\n"
        "PLACE: <ONE single, specific, real place only — one market/complex/"
        "landmark name, optionally with its area/city/state appended after "
        "a comma the way a place is normally written (e.g. 'Purohit Ji Ka "
        "Katla, Tripolia Bazaar, Jaipur' is ONE place). NEVER two or more "
        "DIFFERENT places joined by 'and'/'&'/'/' or listed as alternatives "
        "('sites like X or Y'), never a place type or category. This is NOT "
        "limited to fire/disaster/accident stories — a specific infrastructure "
        "project reveal (a real tender/site/budget update), a specific "
        "conservation project starting at one named site, or any other "
        "concrete dated development at one real place all qualify equally; "
        "the requirement is specificity, not subject matter. Only fill this "
        "in if the evidence reports ONE concrete, freshly reported, DATED "
        "EVENT that itself happened or was FIRST reported within the last "
        "2-3 days AT that one place. The EVENT must be new, not just the "
        "article: a follow-up, aftermath, political-fallout, investigation-"
        "update or crackdown story published today about an OLDER incident "
        "(e.g. headlines saying an old tragedy 'has rewritten' a campaign, "
        "or a probe/demolition drive that followed it) does NOT qualify — "
        "prefer items in the 0-24h bucket whose headline reads like a "
        "first report of something that just happened. NOT an ongoing "
        "policy, standing conservation program, "
        "or general state of affairs. A generic sentence like 'emergency "
        "closures to prevent irreversible structural failure and save "
        "irreplaceable knowledge and lived practices' is a THEME, not an "
        "incident, even attached to one named site — it must instead read "
        "like a news report of one specific thing that happened, roughly "
        "when, and any concrete citable consequence (a number, a duration, "
        "a named cause, a budget figure). Judge each category's evidence on "
        "specificity, never on how MANY items a category has — a category "
        "with only 2-3 items can hold a perfectly valid, specific incident, "
        "and a category with many items (a recurring meme/trend format, for "
        "example) is not automatically the strongest PLACE candidate just "
        "because it has volume; check every category's items for a genuine "
        "single-incident candidate before defaulting to whichever category "
        "happens to be largest. If nothing in the evidence is that "
        "specific, leave PLACE empty rather than dressing up a theme as an "
        "incident>\n"
        "INCIDENT_SUMMARY: <only if PLACE is exactly one specific place — "
        "the one concrete reported event there today, per the cited "
        "evidence only, no invented figures/blame, else empty>\n"
        "SEARCH_TERMS: <only if PLACE is non-empty — comma-separated real, "
        "current search phrases from the actual coverage (place name + "
        "incident type + 'today'/'news'), else empty>",
        evidence=media_evidence,
    )

    # Shape safeguard (added 2026-09-12 after a live failure): a local model
    # given too much context abandoned the required PRIORITY/ANGLE shape
    # entirely and returned an ungrounded free-form narrative instead. A
    # brief without even a PRIORITY marker did not follow the contract and
    # must not be handed downstream as if it were a valid editorial call --
    # fail the same honest way as an empty brief rather than accept prose
    # that skipped the format this skill exists to enforce.
    if brief and not _marker(brief, "PRIORITY"):
        note = "local model returned an off-format response (no PRIORITY marker) -- rejected, not used"
        brief = ""

    if not brief:
        stages.clear_stage("ia")
        return {
            "agent": "IRIS", "mode": "blocked", "_blocked": True,
            "content": ("No fresh, verified trending story worth a news-hook reel today."
                        if discovery_mode else
                        "Sanjeevani local research could not produce a grounded editorial brief."),
            "blocked_reason": note,
            "discovery": discovered.get("summary") if discovery_mode else None,
            "handed_to": None,
        }

    # "location" here is IRIS's editorial priority, NOT the place to shoot --
    # the manifest rotation owns that. Named `priority` so nothing downstream
    # mistakes it for a location the pipeline would honour.
    priority = _marker(brief, "PRIORITY")
    region = _marker(brief, "REGION", "rotation").lower()
    angle = _marker(brief, "ANGLE")
    incident_place = _marker(brief, "PLACE")
    incident_summary = _marker(brief, "INCIDENT_SUMMARY")
    incident_search_terms = _marker(brief, "SEARCH_TERMS")
    lowered_task = task.lower()
    facebook_positive = bool(
        "facebook" in lowered_task
        and not re.search(r"\b(do not|don't|dont|without)\s+(?:publish|post|upload)(?:\s+\w+){0,3}\s+(?:to\s+)?facebook\b", lowered_task)
    )
    instagram_positive = bool(
        "instagram" in lowered_task
        and not re.search(r"\b(do not|don't|dont|without)\s+(?:publish|post|upload)(?:\s+\w+){0,3}\s+(?:to\s+)?instagram\b", lowered_task)
    )
    publish_target = "facebook" if facebook_positive else ("instagram" if instagram_positive else "")
    publish_authorized = bool(
        publish_target and re.search(r"\b(publish|post|upload|live)\b", lowered_task)
    )
    # Specific formats must win before the generic word "post". Previously a
    # request such as "post this carousel" silently became a before/after.
    # "spotlight"/"trend spotlight" was added 2026-09-13, replacing the same-
    # day-reverted editorialPriority/Angle wiring into the main reel -- see
    # imagineindia-trend-spotlight's package.json release_notes. "news hook"/
    # "hook reel" added 2026-09-18 after the Purohit Ji Ka Katla fire reel
    # hit 216k views -- see imagineindia-news-hook-reel's package.json.
    # Checked before before_after's "photo" match for the same reason.
    content_type = (
        "carousel" if re.search(r"\b(carousel|slides?|swipe)\b", lowered_task)
        else "trend_spotlight" if re.search(r"\bspotlight\b", lowered_task)
        else "news_hook" if re.search(r"\b(news.?hook|hook.?reel)\b", lowered_task)
        else "before_after" if re.search(r"\b(before.?after|static|image|photo|post)\b", lowered_task)
        else "reel"
    )
    # A governed ImagineIndia carousel is one distribution mission, not two
    # unrelated posts. Facebook must land first, then Instagram; completion is
    # withheld until both provider receipts verify.
    if content_type == "carousel" and publish_authorized:
        publish_target = "facebook_then_instagram"
    content_label = {
        "carousel": "carousel",
        "before_after": "before/after post",
        "trend_spotlight": "trend spotlight",
        "news_hook": "news hook reel",
        "reel": "reel",
    }.get(content_type, "post")

    grounding_ref = None
    if content_type == "reel" and not discovery_mode:
        from openjarvis.one_agents.iris_grounding import bind_regular_brief
        binding, digest, raw = bind_regular_brief(
            brief, _compact_media_evidence(media_evidence), predicted_location)
        evidence_dir = _home() / "agent_outputs"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = evidence_dir / f"{job['id']}.grounding-{digest}.json"
        evidence_path.write_bytes(raw)
        grounding_ref = {"path": str(evidence_path), "sha256": digest}
        if not binding["accepted"]:
            stages.clear_stage("ia")
            return {"agent": "IRIS", "mode": "blocked", "_blocked": True,
                    "content": brief, "blocked_reason": "; ".join(binding["errors"]),
                    "grounding": grounding_ref, "handed_to": None}

    output_dir = _home() / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job['id']}.md"
    output_path.write_text(
        f"# IRIS — ImagineIndia {content_label.title()} Brief\n\n"
        f"Request: {task}\n\nResearched by: Sanjeevani + "
        f"{os.environ.get('ONE_LOCAL_RESEARCH_MODEL', 'qwen3.5:9b')}\n\n"
        f"{brief}\n",
        encoding="utf-8",
    )

    remembered = memory.remember(
        agent="IRIS", floor_id="4", floor_name="Media & Content (ImagineIndia)",
        kind=f"{content_label.title()} Brief", body=brief, task=task,
        tags=["imagineindia", "media", content_type],
    )

    result: dict[str, Any] = {
        "agent": "IRIS",
        "mode": mode,
        "research_engine": "Sanjeevani local-first",
        "priority": priority,
        "region": region,
        "angle": angle,
        "content": brief,
        "output": str(output_path),
        "vault_note": remembered.get("path"),
        "prior_reels_considered": len(already),
        "grounding": grounding_ref,
    }

    # Event-age check (Sanjeevani trend_discovery.first_report_age, carried on
    # the picked candidate -- article dates are not event dates): measured before
    # the research-only return so a research-only run also SHOWS whether the
    # incident IRIS picked is actually fresh -- that is exactly what an owner
    # testing IRIS's self-reliance needs to see.
    max_event_age_hours = float(os.environ.get("ONE_NEWS_HOOK_MAX_EVENT_AGE_HOURS", "72"))
    incident_stale = False
    pick = discovered.get("pick") if discovery_mode else None
    if discovery_mode and incident_place:
        # Grounding: the model may only name a place that literally appears in
        # the picked story's own headlines (it has blended cities before --
        # "Satya Niketan, Mumbai"). Compare the place's core name, case-blind.
        core = re.split(r",|\(", incident_place, maxsplit=1)[0].strip().lower()
        headline_text = " ".join((pick or {}).get("headlines", [])).lower()
        if not pick or len(core) < 4 or core not in headline_text:
            result["discovery_ungrounded_place"] = incident_place
            incident_place = ""
    if discovery_mode:
        result["discovery"] = discovered.get("summary", {})
        if discovered.get("note") and not brief:
            result["discovery_note"] = discovered["note"]
    if content_type == "news_hook" and incident_place:
        age = ({"age_hours": (pick["first_report"] or {}).get("age_hours"),
                "earliest": (pick["first_report"] or {}).get("earliest"),
                "verified": bool(pick.get("verified"))}
               if pick else {"age_hours": None, "earliest": None, "verified": False})
        result["incident_first_report_age_hours"] = age["age_hours"]
        result["incident_first_report_earliest"] = age["earliest"]
        result["incident_age_verified"] = age["verified"]
        incident_stale = bool(age["verified"] and age["age_hours"] > max_event_age_hours)
        result["incident_stale"] = incident_stale

    # Same default as HERMES: dispatching the floor head means "get it done".
    # Research-only is the explicit exception, asked for in plain words.
    research_only = bool(re.search(r"\b(plan|draft|prepare|research)\b", task.lower()))
    if research_only:
        stages.clear_stage("ia")
        result["handed_to"] = None
        result["note"] = (
            "Research only — nothing handed to MUSE, because the request asked "
            "to plan/draft/research. Say it without those words (e.g. 'IRIS, "
            "get the next reel done') to commission it for real."
        )
        return result

    # Trend Spotlight is deliberately ad hoc, per explicit user direction
    # (2026-09-13): unlike the reel/before_after/carousel formats, it has no
    # location catalogue or Bible structure to fall back on if the research
    # is weak -- the whole video IS today's researched story, so a weak day
    # must not ship a forced/thin spotlight. Gate on Sanjeevani's own
    # commissioning_eligible flag (>=3 eligible items, >=2 source types) on
    # ANY category researched above, including predicted_location. A caller
    # (or a future trigger this session was told NOT to build -- "Mn abhi
    # trigger ke liye ONE mn alag se kuch banaunga... abhi wait karo") can
    # dispatch this daily and IRIS will simply no-op on weak days.
    if content_type == "trend_spotlight":
        strong = any(
            bool(cat.get("commissioning_eligible"))
            for cat in media_evidence.get("categories", {}).values()
        )
        if not strong:
            stages.clear_stage("ia")
            result["handed_to"] = None
            result["note"] = (
                "No genuinely strong trend today (nothing hit Sanjeevani's "
                "commissioning_eligible bar across any researched category) -- "
                "not forcing a Trend Spotlight on thin evidence. Try again "
                "later, or ask for the regular reel instead."
            )
            return result

    # News Hook Reel is ad hoc for the same reason as Trend Spotlight, plus
    # a stricter bar: it has NO location catalogue at all, so it needs a
    # genuinely real, SPECIFIC, current local incident (a real named place
    # having a real named problem), not just a strong theme. Gate on BOTH
    # commissioning_eligible evidence AND a non-empty PLACE marker -- the
    # synthesis prompt leaves PLACE empty on any day it cannot honestly name
    # a real specific incident, per its own instructions above.
    if content_type == "news_hook":
        strong = any(
            bool(cat.get("commissioning_eligible"))
            for cat in media_evidence.get("categories", {}).values()
        )
        # Defense-in-depth (added 2026-09-18 after a live failure): the
        # synthesis prompt asks for exactly ONE specific place, but a live
        # run still returned "Konark Sun Temple, Meenakshi Amman Temple" --
        # a multi-site theme dressed as an incident, not the Jaipur-fire-
        # style single concrete event this format needs. Don't just trust
        # the model followed the instructions -- two independent checks:
        # (1) PLACE joining two DIFFERENT places with "and"/"&"/"/" or
        # "like X or Y" -- NOT a bare comma, which is the normal way to
        # write one place's area/city/state ("Purohit Ji Ka Katla, Tripolia
        # Bazaar, Jaipur" is ONE place; an earlier version of this check
        # wrongly flagged that shape as a live false positive on "Sanchi
        # Stupa, Madhya Pradesh", also one place).
        # (2) INCIDENT_SUMMARY reading as a generic ongoing-policy THEME
        # rather than one dated event -- confirmed live twice on 2026-09-18
        # that the model defaults to the same canned "emergency closures to
        # save irreplaceable knowledge/lived practices" phrasing regardless
        # of which site name it plugs in, which is a theme, not a report of
        # something that actually happened this week.
        looks_like_multiple_places = bool(
            incident_place and re.search(r"\b and \b|&|/| like .+ or ", incident_place, re.I)
        )
        looks_like_generic_theme = bool(
            incident_summary and re.search(
                r"irreplaceable knowledge|lived practices|critical safety pause|"
                r"before (it|they) vanish|several (heritage )?sites|multiple sites",
                incident_summary, re.I,
            )
        )
        if incident_place and not result.get("incident_age_verified"):
            # Unverified is NOT fresh. The whole point of this check is that
            # a story can look new (a recent aftermath article) while the
            # event is weeks old -- so if the event's age cannot be measured,
            # do not commission on a guess.
            stages.clear_stage("ia")
            result["handed_to"] = None
            result["note"] = (
                f"Could not verify how old '{incident_place}' is (no wide-window "
                "news match / lookup failed) -- not commissioning a news-hook reel on "
                "an unverified date. Retry, or ask for the regular reel."
            )
            return result
        if incident_stale and incident_place and not looks_like_multiple_places:
            stages.clear_stage("ia")
            result["handed_to"] = None
            result["note"] = (
                f"'{incident_place}' is NOT a fresh incident: the earliest "
                f"news report found for it is ~{result.get('incident_first_report_age_hours')}h old "
                f"(first seen {result.get('incident_first_report_earliest')}), past the "
                f"{max_event_age_hours:.0f}h limit. Sanjeevani's 2-day window matched a recent "
                "follow-up/aftermath article about an older event, not a new event -- a reel "
                "on it now would miss the viral window. Not commissioning; try again when a "
                "genuinely new incident appears."
            )
            return result
        if not strong or not incident_place or looks_like_multiple_places or looks_like_generic_theme:
            stages.clear_stage("ia")
            result["handed_to"] = None
            result["note"] = (
                "No genuinely real, SINGLE specific local incident found "
                "today (either evidence was too thin, or the only usable "
                "signal was a multi-site theme rather than one concrete "
                "event at one place: "
                + (incident_place or "(none)")
                + ") -- not forcing a News Hook Reel on a generic theme. "
                "Try again later, or ask for the regular reel instead."
            )
            return result

    # --- the handoff ------------------------------------------------------
    # head_briefs_worker (stages.py) owns the CARRYING_TO_WORKER/BRIEFING/
    # RECEIVING/AWAITING_WORKER choreography -- see its docstring for why
    # this can't just be a bare set_stage/sleep/enqueue sequence per floor.
    if content_type == "news_hook" and incident_place:
        _news_hook_ledger_record(incident_place, incident_summary, str(job.get("id") or ""))
    # This Floor 4 commissioning path always hands the approved brief to
    # MUSE. `worker_id` belongs to the YouTube/brand router below and is not
    # defined in IRIS; keeping this explicit prevents before/after and reel
    # trigger runs from dying with a NameError after research is complete.
    _require_active_job(job, "commission MUSE")
    worker = stages.head_briefs_worker(
        "ia", "muse",
        carrying_detail=f"Taking the {content_label} brief to MUSE: {(priority or angle)[:60]}",
        briefing_detail=f"MUSE, create the {content_label}: {(priority or angle)[:110]}",
        awaiting_detail=f"Waiting on MUSE to produce the {content_label}",
        enqueue=lambda: enqueue_job(
            "muse",
            json.dumps({"brief_path": str(output_path), "priority": priority,
                        "grounding": grounding_ref,
                        "region": region, "angle": angle, "origin_job": job["id"],
                        "content_type": content_type, "topic": task,
                        "publish_target": publish_target,
                        "publish_authorized": publish_authorized,
                        "incident_place": incident_place,
                        "incident_summary": incident_summary,
                        "incident_search_terms": incident_search_terms}),
            mode="execute",
            tier="fast",
        ),
    )

    result["handed_to"] = {"agent": "MUSE", "job_id": worker["id"]}
    result["note"] = (
        f"Brief handed to MUSE, who will produce the ImagineIndia {content_label} "
        f"to completion and hand the finished {content_label} back."
    )
    return result


def _iris_report(job: dict[str, Any]) -> dict[str, Any]:
    """Third leg: MUSE has delivered, IRIS reports the result upward."""
    try:
        payload = json.loads(str(job.get("task") or "{}"))
    except json.JSONDecodeError:
        payload = {}

    content_type = str(payload.get("content_type") or "reel").strip().lower()
    content_label = {
        "carousel": "carousel",
        "before_after": "before/after post",
        "before-after": "before/after post",
        "trend_spotlight": "trend spotlight",
        "trend-spotlight": "trend spotlight",
        "news_hook": "news hook reel",
        "news-hook": "news hook reel",
        "reel": "reel",
    }.get(content_type, "post")
    stages.set_stage("ia", stages.REPORTING, f"Reviewing MUSE's finished {content_label}")
    run_dir = payload.get("run_dir") or "(not reported by LAO)"
    title = payload.get("title") or "(details in the run folder)"
    published = bool(payload.get("published"))
    publish_receipt = payload.get("publish_receipt") or {}
    platforms = publish_receipt.get("platforms") or {}
    permalink = str(publish_receipt.get("permalink") or "")
    if platforms:
        platform = "Facebook and Instagram"
    else:
        platform = "Facebook" if "facebook.com" in permalink.lower() else "Instagram"

    message = (
        f"Sir, the {content_label} is finished. MUSE has handed it over.\n\n"
        f"{content_label.title()}: {title}\n"
        f"Location: {run_dir}\n\n"
        + (f"It has been published to {platform} by the pipeline."
           if published else
           "It is produced and ready — publishing is whatever the LAO package "
           "is configured to do; I have not touched it by hand.")
    )

    output_dir = _home() / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job['id']}.md"
    output_path.write_text(f"# IRIS — Delivery Report\n\n{message}\n", encoding="utf-8")

    remembered = memory.remember(
        agent="IRIS", floor_id="4", floor_name="Media & Content (ImagineIndia)",
        kind=f"{content_label.title()} Delivery Report",
        body=f"{message}\n\nANGLE: {title}\n",
        tags=["imagineindia", "media", content_type, "delivered"],
    )

    time.sleep(2.0)
    stages.clear_stage("ia")
    return {
        "agent": "IRIS",
        "mode": "report",
        "content": message,
        "run_dir": run_dir,
        "title": title,
        "published": published,
        "output": str(output_path),
        "vault_note": remembered.get("path"),
    }


def _iris_report_brand(job: dict[str, Any], brand: dict[str, Any], *,
                       head_id: str = "ia", head_name: str = "IRIS",
                       floor_id: str = "4") -> dict[str, Any]:
    """Third leg for a Floor 4 brand that is not ImagineIndia.

    Same shape as _iris_report, but every brand-specific detail comes from the
    brand record instead of being hardcoded: the vault folder, the tags, and
    the wording. Keeping this separate leaves the ImagineIndia report exactly
    as it was rather than making one function serve two voices badly.
    """
    try:
        payload = json.loads(str(job.get("task") or "{}"))
    except json.JSONDecodeError:
        payload = {}

    display = brand.get("display_name", brand["slug"])
    worker = str(payload.get("worker") or brand["worker_agent_id"]).upper()

    if (brand.get("slug") == "sonia_travel_vlogs"
            and payload.get("format") == "travel_video_production"
            and payload.get("stage") != "seo_complete"):
        stages.set_stage(head_id, stages.CARRYING_TO_WORKER,
                         "Taking YATRA's verified master to LYRA for YouTube packaging",
                         worker="lyra")
        follow = enqueue_job("lyra", json.dumps({**payload, "stage": "seo"}),
                             mode="execute", tier="fast",
                             dedupe_key=f"travel:{payload.get('lao_job')}:seo")
        stages.set_stage(head_id, stages.AWAITING_WORKER,
                         "Waiting for LYRA SEO and private-upload package", worker="lyra")
        return {"agent": head_name, "mode": "handoff", "brand": brand["slug"],
                "production_complete": True, "published": False,
                "handed_to": {"agent": "LYRA", "job_id": follow["id"]},
                "content": f"YATRA production passed QC; {head_name} handed the verified master to LYRA."}

    if (brand.get("slug") == "sonia_travel_vlogs"
            and payload.get("stage") == "seo_complete"
            and not payload.get("distribution_complete")):
        seo_payload = payload.get("seo") if isinstance(payload.get("seo"), dict) else {}
        package = str(seo_payload.get("path") or payload.get("output") or "")
        stages.set_stage(head_id, stages.CARRYING_TO_WORKER,
                         "Taking LYRA package to ECHO for subtitles, languages and comment", worker="echo")
        follow = enqueue_job("echo", json.dumps({**payload, "package": package}),
                             mode="execute", tier="fast",
                             dedupe_key=f"travel:{payload.get('lao_job')}:distribution")
        stages.set_stage(head_id, stages.AWAITING_WORKER,
                         "Waiting for ECHO to complete the private YouTube draft", worker="echo")
        return {"agent": head_name, "mode": "handoff", "brand": brand["slug"],
                "published": False, "handed_to": {"agent": "ECHO", "job_id": follow["id"]},
                "content": f"LYRA packaging received; {head_name} handed subtitles, languages and comment to ECHO."}

    if str(payload.get("status") or "") == "stopped":
        # The worker ended without anything to deliver. Reported as that, not
        # as "ready", and kept out of the brand's ANGLE history: a post that
        # was never made must not stop tomorrow's run from making it.
        stages.set_stage(head_id, stages.REPORTING, f"Reporting why today's {display} post was not made")
        fmt = payload.get("format") or "post"
        reason = str(payload.get("note") or payload.get("error") or "no reason was given")
        message = (f"Sir, today's {display} {fmt} was not produced. {worker} stopped before making it.\n\n"
                   f"Reason: {reason}")
        output_dir = _home() / "agent_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{job['id']}.md"
        output_path.write_text(f"# {head_name} - Stopped ({display})\n\n{message}\n", encoding="utf-8")
        remembered = memory.remember(
            agent=head_name, floor_id=floor_id, floor_name=brand["vault_floor_name"],
            kind="Stopped Report", body=message,
            tags=[brand["slug"], "media", str(fmt).lower(), "stopped"],
        )
        time.sleep(2.0)
        stages.clear_stage(head_id)
        return {"agent": head_name, "mode": "report", "brand": brand["slug"], "content": message,
                "status": "stopped", "error": payload.get("error"), "published": False,
                "output": str(output_path), "vault_note": remembered.get("path")}

    stages.set_stage(head_id, stages.REPORTING, f"Reporting the finished {display} post")
    title = payload.get("title") or "(details in the plan)"
    fmt = payload.get("format") or "post"
    output = payload.get("output") or "(not reported)"
    published = bool(payload.get("published"))
    blocked = payload.get("publish_blocked_reason") or ""

    learned = str(payload.get("learning_summary") or "").strip()
    proposals = [str(name) for name in payload.get("layout_proposals") or [] if str(name).strip()]
    gate_note = ""
    seo_payload = payload.get("seo") if isinstance(payload.get("seo"), dict) else {}
    gate = seo_payload.get("upload_gate")
    if gate:
        from openjarvis.one_agents import youtube_publish
        if gate.get("status") == "awaiting_approval" and gate.get("package"):
            stages.set_stage(head_id, stages.EXECUTING, "Uploading the private YouTube draft under the standing policy")
            try:
                gate = youtube_publish.autopilot_upload(Path(gate["package"]))
            except Exception as exc:  # noqa: BLE001 - report it; the gate stays retryable
                gate = {**gate, "status": "upload_failed", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}
            stages.set_stage(head_id, stages.REPORTING, f"Reporting the finished {display} post")
        gate_note = "\n\n" + youtube_publish.summarize(gate)
        if isinstance(payload.get("storage_cleanup"), dict) and gate.get("status") != "uploaded_private":
            gate_note += youtube_publish.storage_note(payload["storage_cleanup"])
        receipt = seo_payload.get("thumbnail_receipt") or {}
        if receipt and not receipt.get("ok"):
            gate_note += (f"\nThumbnail: automatic generation did not finish ({receipt.get('stage')}: "
                          f"{str(receipt.get('error', ''))[:160]}).")
    message = (
        f"Sir, the {display} {fmt} is ready. {worker} has handed it over.\n\n"
        f"Angle: {title}\n"
        f"Plan: {output}\n\n"
        + ("It has been published." if published else
           f"It is not published. {blocked}".strip())
        + gate_note
        + (f"\n\nWhat {worker} has learned so far: {learned}" if learned else "")
        + (f"\nNew carousel formats creators are using, waiting for your pick: {', '.join(proposals)}"
           if proposals else "")
    )

    output_dir = _home() / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job['id']}.md"
    output_path.write_text(f"# {head_name} — Delivery Report ({display})\n\n{message}\n", encoding="utf-8")

    remembered = memory.remember(
        agent=head_name, floor_id=floor_id, floor_name=brand["vault_floor_name"],
        kind="Delivery Report",
        body=f"{message}\n\nANGLE: {title}\n",
        tags=[brand["slug"], "media", str(fmt).lower(), "delivered"],
    )

    time.sleep(2.0)
    stages.clear_stage(head_id)
    return {
        "agent": head_name,
        "mode": "report",
        "brand": brand["slug"],
        "content": message,
        "title": title,
        "format": fmt,
        "published": published,
        "output": str(output_path),
        "vault_note": remembered.get("path"),
    }


def _floor4_carousel_module() -> Any:
    """Load Floor 4's owned adapter without making one-company a package."""
    path = (Path(__file__).resolve().parents[4] / "one-company" / "floors" /
            "floor_04_media" / "lib" / "imagineindia_carousel.py")
    spec = importlib.util.spec_from_file_location("one_floor4_imagineindia_carousel", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load Floor 4 carousel adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves the defining module through sys.modules.
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_lao_secret(asset_name: str) -> str:
    """Resolve one LAO-vault value in memory; never persist or log it."""
    import urllib.parse
    import urllib.request

    config_path = _find_lao_robot_config()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    folder_id = os.environ.get("LAO_ASSET_FOLDER_ID", _PEITHO_LAO_FOLDER_ID)
    url = (str(config["orchestrator_url"]).rstrip("/") + "/assets/resolve/" +
           urllib.parse.quote(asset_name) + "?folder_id=" + urllib.parse.quote(folder_id))
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + config["robot_token"]})
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.loads(response.read())["value"]
    secret = value if isinstance(value, str) else str(value.get("password") or "")
    if not secret:
        raise RuntimeError(f"LAO vault asset {asset_name!r} is empty")
    return secret


def _run_muse_carousel(job: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    """Create two candidates, select transparently, render, and optionally post."""
    module = _floor4_carousel_module()
    topic = str(brief.get("topic") or brief.get("angle") or brief.get("priority") or "").strip()
    if not topic:
        raise RuntimeError("Carousel brief has no topic")
    stages.set_stage("muse", stages.EXECUTING, "Collecting grounded carousel evidence with Sanjeevani")
    reusable = _sanjeevani_research()
    evidence: dict[str, Any] = {"eligible": [], "catalog_evidence": []}
    if reusable is not None:
        evidence = reusable.collect(topic, markets=["IN"])
    prompt = module.carousel_prompt(topic, evidence)

    stages.set_stage("muse", stages.EXECUTING, "Creating ChatGPT and Sanjeevani carousel candidates")
    chatgpt_output, chatgpt_error = _run_peitho_lao_draft([prompt])
    chatgpt_raw = str(chatgpt_output.get("angle_1") or "")
    if not chatgpt_raw:
        raise RuntimeError(f"ChatGPT carousel candidate failed: {chatgpt_error}")
    sanjeevani_raw, local_error = _research_synthesis(prompt, evidence=evidence)
    if not sanjeevani_raw:
        raise RuntimeError(f"Sanjeevani carousel candidate failed: {local_error}")

    selection = module.select_candidate(chatgpt_raw, sanjeevani_raw)
    winner = selection["winner"]
    output_dir = _home() / "agent_outputs" / "carousels" / f"{job['id']}-{module.content_hash(selection)}"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")
    slides = module.render(winner, output_dir)
    caption = "\n\n".join(filter(None, [winner.get("caption", ""), " ".join(winner.get("hashtags") or [])]))
    receipt: dict[str, Any] = {"required_order": ["facebook", "instagram"], "platforms": {}}
    published = False
    if bool(brief.get("publish_authorized")):
        target = str(brief.get("publish_target") or "").lower()
        if target not in {"facebook_then_instagram", "instagram", "facebook"}:
            raise RuntimeError("Carousel publication target is not governed")
        # Current product contract is intentionally stricter than a caller's
        # one-platform wording: Facebook first, then Instagram, both required.
        stages.set_stage("muse", stages.EXECUTING, "1/2 Publishing carousel to ImagineIndia Facebook")
        facebook_token = _resolve_lao_secret(os.environ.get(
            "LAO_FACEBOOK_PUBLISH_ASSET", "imagineIndiaFacebookPublishingToken"))
        page_id = os.environ.get("IMAGINEINDIA_FACEBOOK_PAGE_ID", "1208655322324462")
        facebook_receipt = module.publish_facebook(
            page_id=page_id, token=facebook_token, slides=slides, caption=caption)
        receipt["platforms"]["facebook"] = facebook_receipt
        if not facebook_receipt.get("verified"):
            raise RuntimeError("Facebook did not return a verified carousel receipt; Instagram was not attempted")

        stages.set_stage("muse", stages.EXECUTING, "2/2 Publishing carousel to ImagineIndia Instagram")
        instagram_token = _resolve_lao_secret(os.environ.get(
            "LAO_INSTAGRAM_PUBLISH_ASSET", "imagineIndiaInstagramPublishingToken"))
        account_id = os.environ.get("IMAGINEINDIA_INSTAGRAM_ACCOUNT_ID", "28638709669130556")
        cloudflared = Path(os.environ.get("CLOUDFLARED_EXE", str(Path.home() / "AppData/Local/Programs/cloudflared/cloudflared.exe")))
        if not cloudflared.is_file():
            raise RuntimeError("cloudflared is required to give Meta temporary HTTPS access to slides")
        instagram_receipt = module.publish_instagram(
            account_id=account_id, token=instagram_token, slides=slides,
            caption=caption, cloudflared=cloudflared)
        receipt["platforms"]["instagram"] = instagram_receipt
        published = all(
            bool(receipt["platforms"].get(platform, {}).get("verified"))
            for platform in receipt["required_order"]
        )
        if not published:
            raise RuntimeError("MUSE cannot complete until Facebook and Instagram both verify")

    title = str(winner.get("title") or topic)
    memory.remember(
        agent="MUSE", floor_id="4", floor_name="Media & Content (ImagineIndia)",
        kind="Carousel Production Run",
        body=(f"Two candidates evaluated; {selection['decision']}.\n\n"
              f"Output: `{output_dir}`\nPublished: {published}"),
        task=topic, tags=["imagineindia", "media", "carousel", winner["source"]],
    )
    enqueue_job("ia", json.dumps({"run_dir": str(output_dir), "title": title,
                "published": published, "content_type": "carousel",
                "publish_receipt": receipt}), mode="report", tier="fast")
    stages.clear_stage("muse")
    return {"agent": "MUSE", "mode": job.get("mode"), "content_type": "carousel",
            "status": "Successful", "run_dir": str(output_dir), "title": title,
            "winner": winner["source"], "score": winner["score"],
            "published": published, "publish_receipt": receipt,
            "content": f"Carousel finished: {title}. {selection['decision']}",
            "handed_to": {"agent": "IRIS"}}


def _run_muse(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 4 worker - runs LAO's ImagineIndia pipeline(s) and waits for the
    result. MUSE is the sole ImagineIndia-brand worker on Floor 4: it drives
    BOTH the video reel and the static before/after post (added 2026-09-04),
    selected by `content_type` in the brief ("reel", the default -- kept for
    every existing caller that never set this field -- or "before_after").
    Every other Floor 4 worker's brand is untouched by this addition.

    Same shape as _run_scribe on Floor 5: this blocks on a long external LAO
    job and polls it, so the floor genuinely shows the worker busy for as long
    as the run actually takes.
    """
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool

    try:
        brief = json.loads(str(job.get("task") or "{}"))
    except json.JSONDecodeError:
        brief = {}
    priority = str(brief.get("priority") or "").strip()
    region = brief.get("region") or "india"
    angle = str(brief.get("angle") or "").strip()
    headline = angle or priority
    content_type = str(brief.get("content_type") or "reel").strip().lower()
    if content_type == "carousel":
        stages.worker_confirms_receipt(
            "muse", f"Got it — {(str(brief.get('angle') or brief.get('topic') or 'carousel'))[:110]}")
        return _run_muse_carousel(job, brief)
    is_before_after = content_type in ("before_after", "before-after", "beforeafter")
    is_trend_spotlight = content_type in ("trend_spotlight", "trend-spotlight", "spotlight")
    is_news_hook = content_type in ("news_hook", "news-hook")
    kind_label = (
        "before/after post" if is_before_after
        else "trend spotlight" if is_trend_spotlight
        else "news hook reel" if is_news_hook
        else "reel"
    )

    stages.worker_confirms_receipt(
        "muse",
        f"Got it — {headline[:110]}" if headline else "Taking the brief from IRIS",
    )

    tool = LaoOrchestratorTool()
    process_name = (
        os.environ.get("LAO_IA_BEFORE_AFTER_PROCESS", IA_BEFORE_AFTER_PROCESS_NAME) if is_before_after
        else os.environ.get("LAO_IA_TREND_SPOTLIGHT_PROCESS", IA_TREND_SPOTLIGHT_PROCESS_NAME) if is_trend_spotlight
        else os.environ.get("LAO_IA_NEWS_HOOK_PROCESS", IA_NEWS_HOOK_PROCESS_NAME) if is_news_hook
        else os.environ.get("LAO_IA_PROCESS", IA_PROCESS_NAME)
    )

    stages.set_stage("muse", stages.EXECUTING,
                     f"Starting the {kind_label}: {headline[:110]}" if headline
                     else f"Starting LAO ImagineIndia {kind_label} pipeline")

    # Deliberately EMPTY -- confirmed against LAO's own process detail
    # (2026-08-14): this process carries input_defaults for everything it
    # needs (chatgptLogin / leonardoLogin credential names, IA_Bible.md,
    # IA_Locations.json, outputDir, publishMode="manual_review"), and its
    # 3x/day triggers start it with no arguments at all. Passing {} means
    # MUSE starts it exactly the way the scheduled runs do.
    #
    # Note there is NO location override to pass: the package picks the
    # location deterministically from IA_Locations.json via its zoned
    # rotation (v1.2.0 made this deliberate, to guarantee no repeats and
    # full India coverage -- "ChatGPT never chooses the location"). IRIS's
    # brief is editorial intent and a durable record; it does not and must
    # not steer which location comes next.
    #
    # mode="dry_run" only avoids the tool's publish gate (mode="publish"
    # demands confirm_publish=true). What actually gets published is the
    # package's own publishMode default, which is manual_review.
    #
    # Caption and hashtags, for BOTH the reel and the before/after post, are
    # NEVER MUSE's to supply -- per explicit user direction (2026-09-04):
    # "jab MUSE inko create karke post karega, to caption and hashtags jo
    # bhi relevant ho wo leke tab post karega" (whatever caption/hashtags
    # are relevant get taken at post time). This is exactly why input_args
    # stays {} below -- each LAO run's own ChatGPT call generates a fresh
    # minimal_caption/seo_hashtags (or instagram_caption/instagram_hashtags
    # for the reel) specific to THAT run's location and format, and
    # meta_publish_image/meta_publish_reel use exactly that value when
    # publishMode is auto_publish. MUSE must never pass a fixed/stale
    # caption or hashtag override here -- doing so would post yesterday's
    # or a hardcoded caption on today's images.
    #
    # A restart while this was polling leaves the LAO id on the job row. When
    # it is there, re-attach to that run instead of starting a second one --
    # the poll loop below is the same either way.
    resume_id = job_recovery.resume_target(job)
    if resume_id:
        lao_job_id = resume_id
        stages.set_stage(
            "muse", stages.EXECUTING,
            f"Picking the {kind_label} back up — LAO job {resume_id[:8]} after a restart",
            lao_job=resume_id)
    else:
        # A provider's explicit no-token/no-credit response is an external
        # capacity condition, not a transient browser failure.  Starting the
        # same paid workflow again cannot heal it and previously burned two
        # full 900-second Kling waits before anyone could see the real modal.
        # Re-attaching to an existing LAO job remains allowed above; this gate
        # applies only before a new paid Leonardo start.
        from openjarvis.one_agents import provider_capacity
        provider_capacity.require_available("leonardo")
        # LAO integration wiring (governance approval
        # 61c59bc2-15ae-4deb-bc2f-c65a984bcbb8, decided_by=olympus) was tried
        # 2026-09-13 and REVERTED the same day: live verification showed it
        # structurally couldn't work against the reel's own Bible (Frame 1's
        # conflict must be a real LOCAL problem at whatever location the
        # deterministic rotation lands on, so an abstract researched theme
        # almost never has an honest connection to a random pick). The reel
        # and before_after paths pass input_args={} -- there is NO location
        # override to pass, and no editorial hint either now. IRIS's
        # Sanjeevani research instead drives the separate trend_spotlight
        # path below, added the same day: that package has no location
        # catalogue or Bible structure to fall back on, so priority/angle
        # ARE its required content, not an optional hint.
        lao_input_args: dict[str, Any] = (
            {"editorialPriority": priority, "editorialAngle": angle}
            if is_trend_spotlight
            else {
                "incidentPlace": str(brief.get("incident_place") or ""),
                "incidentSummary": str(brief.get("incident_summary") or ""),
                "incidentSearchTerms": str(brief.get("incident_search_terms") or ""),
            }
            if is_news_hook
            # 2026-09-19: the static before/after package (v1.7.0) writes its
            # image prompts from short guardrails + this optional trend angle,
            # so IRIS's Sanjeevani finding is a soft theme hint for ChatGPT,
            # not a script. Empty = ChatGPT picks the place's natural story.
            else {"trendBrief": str(angle or "")[:400]} if is_before_after
            else {}
        )
        started = tool.execute(
            action="start", mode="dry_run", process_name=process_name,
            scope="production",
            input_args=lao_input_args,
        )
        if not started.success:
            stages.clear_stage("muse")
            stages.clear_stage("ia")
            raise RuntimeError(f"LAO refused the ImagineIndia run: {started.content}")
        try:
            start_payload = json.loads(started.content)
        except json.JSONDecodeError:
            start_payload = {"raw": started.content}
        lao_job_id = ((start_payload.get("job") or {}).get("id")) or ""
        # Recorded before the first poll: the window between starting the run
        # and writing down its id is where a restart orphans the reel.
        job_recovery.attach(_connect, job["id"], lao_job_id)

    # --- wait for the reel ------------------------------------------------
    poll_seconds = float(os.environ.get("ONE_LAO_POLL_SECONDS", "30"))
    # 2.75h: LAO's own timeout_seconds on this process is 9000 (2.5h), so
    # waiting less than that would abandon a run LAO is still legitimately
    # working on and leave MUSE's stage stuck. Sit just past LAO's limit.
    max_wait = float(os.environ.get("ONE_IA_MAX_WAIT_SECONDS", "9900"))
    deadline = time.time() + max_wait
    terminal = {"Successful", "Failed", "Stopped", "Cancelled", "Faulted"}
    status = "Pending"
    last: dict[str, Any] = {}
    consecutive_probe_failures = 0
    # 5 consecutive failed polls (~2.5min at the default 30s cadence) means
    # ONE has genuinely lost contact with LAO's API, not a one-off blip.
    # Without this check, a failed probe fell through to "keep the old
    # status" below forever -- confirmed live (2026-08-15): a user manually
    # stopped the underlying LAO job via LAO Studio, but MUSE's floor card
    # kept showing "LAO Running" indefinitely because nothing ever detected
    # that status polling itself had stopped succeeding.
    max_consecutive_probe_failures = 5

    while time.time() < deadline:
        time.sleep(poll_seconds)
        # Says "this worker is still alive" to the restart sweep. Without it a
        # long healthy poll looks exactly like an orphan.
        job_recovery.heartbeat(_connect, job["id"])
        probe = tool.execute(action="status", process_name=process_name,
                             scope="production", job_id=lao_job_id)
        if not probe.success:
            consecutive_probe_failures += 1
            stages.set_stage(
                "muse", stages.EXECUTING,
                f"Lost contact with LAO, retrying ({consecutive_probe_failures}/{max_consecutive_probe_failures})…",
                lao_job=lao_job_id, lao_process=process_name)
            if consecutive_probe_failures >= max_consecutive_probe_failures:
                stages.clear_stage("muse")
                stages.clear_stage("ia")
                raise RuntimeError(
                    f"Lost contact with LAO after {consecutive_probe_failures} consecutive "
                    f"failed status polls (last: {probe.content[:200]}) -- cannot confirm "
                    "whether the underlying LAO job is still running."
                )
            continue
        consecutive_probe_failures = 0
        try:
            last = json.loads(probe.content)
        except json.JSONDecodeError:
            last = {"raw": probe.content}
        status = str((last.get("job") or {}).get("status") or status)
        elapsed = int((time.time() - (deadline - max_wait)) // 60)
        verb = (
            "Composing" if is_before_after
            else "Spotlighting" if is_trend_spotlight
            else "Hooking" if is_news_hook
            else "Shooting"
        )
        stages.set_stage(
            "muse", stages.EXECUTING,
            (f"{verb} “{headline[:70]}” · LAO {status} · {elapsed}m" if headline
             else f"LAO job {status} · {elapsed}m"),
            lao_job=lao_job_id, lao_process=process_name)
        if status in terminal:
            break
    else:
        stages.clear_stage("muse")
        stages.clear_stage("ia")
        raise RuntimeError(
            f"LAO ImagineIndia job did not finish within {max_wait/3600:.1f}h "
            f"(last status: {status})"
        )

    if status != "Successful":
        stages.clear_stage("muse")
        stages.clear_stage("ia")
        raise RuntimeError(f"LAO ImagineIndia job ended as {status}")

    # Trust LAO's own response for what it produced -- same reasoning as
    # SCRIBE: this process runs under a sandboxed runtime_home, so
    # re-discovering the output folder locally would look in the wrong place.
    out = ((last.get("job") or {}).get("output_result") or {})
    if is_before_after:
        # Verified live (2026-09-04) against a real run's actual
        # output_result shape -- this package has no "reel"/"meta_publish"
        # nesting, its fields are top-level.
        location = out.get("chosen_location") or {}
        location_name = str(location.get("name") or "")
        style = str((out.get("before_after_format_result") or {}).get("before_after_style") or "")
        title = f"{location_name} before/after ({style})" if (location_name and style) else (location_name or headline or "")
        run_dir = str((out.get("composite_image_path") or {}).get("path") or "")
        published = str((out.get("meta_publish_result") or {}).get("status") or "") == "published"
    elif is_trend_spotlight:
        # imagineindia-trend-spotlight has no location catalogue -- title is
        # always the researched headline, never a place name.
        run_dir = str((out.get("final_video") or {}).get("path") or "")
        title = headline or f"Trend Spotlight (LAO job {lao_job_id[:8]})"
        published = str((out.get("meta_publish_result") or {}).get("status") or "") == "published"
    elif is_news_hook:
        # imagineindia-news-hook-reel has no location catalogue either --
        # title is the real incident place IRIS/MUSE carried through, not a
        # catalogue name.
        run_dir = str((out.get("final_video_with_audio") or out.get("final_video") or {}).get("path") or "")
        incident_place_out = str(brief.get("incident_place") or "")
        title = incident_place_out or headline or f"News Hook Reel (LAO job {lao_job_id[:8]})"
        published = str((out.get("meta_publish_result") or {}).get("status") or "") == "published"
    else:
        reel = out.get("reel") or out.get("meta_publish") or {}
        run_dir = str(reel.get("run_dir") or reel.get("output_dir") or "")
        title = str(reel.get("title") or reel.get("location") or headline or "")
        published = bool(reel.get("published") or reel.get("permalink"))

    publish_receipt: dict[str, Any] = {}
    publish_target = str(brief.get("publish_target") or "").strip().lower()
    if (is_before_after and bool(brief.get("publish_authorized"))
            and publish_target == "facebook" and not published):
        manifest_path = Path(run_dir).with_name("before_after_publish_manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stages.set_stage("muse", stages.EXECUTING, "Publishing to ImagineIndia Facebook via Graph API")
        publish_receipt = _muse_publish_facebook(run_dir, str(manifest.get("caption") or ""))
        published = bool(publish_receipt.get("verified"))
        if not published:
            raise RuntimeError("Facebook delivery did not return verified publication evidence")
    if bool(brief.get("publish_authorized")) and not published:
        raise RuntimeError(
            f"MUSE cannot complete: requested {publish_target or 'social'} publication "
            "has no verified provider receipt"
        )

    if not title:
        # LAO said Successful but told us nothing identifiable -- report the
        # job id rather than walking a phantom result across the floor.
        title = f"ImagineIndia {kind_label} (LAO job {lao_job_id[:8]})"

    # --- walk the finished reel back to the floor head --------------------
    stages.set_stage("muse", stages.CARRYING_TO_HEAD, f"Delivering: {title}")
    time.sleep(float(os.environ.get("ONE_HANDOFF_SECONDS", "6")))
    stages.set_stage("muse", stages.DELIVERING,
                     f"It's done — “{title}” is finished.")
    time.sleep(float(os.environ.get("ONE_BRIEFING_SECONDS", "8")))

    celebration = f"“{title}” shipped! 🎉"
    stages.set_stage("muse", stages.CELEBRATING, celebration)
    stages.set_stage("ia", stages.CELEBRATING, celebration)
    time.sleep(float(os.environ.get("ONE_CELEBRATION_SECONDS", "5")))

    memory.remember(
        agent="MUSE", floor_id="4", floor_name="Media & Content (ImagineIndia)",
        kind="Production Run",
        body=(f"Ran LAO's ImagineIndia {kind_label} pipeline to completion.\n\n"
              f"- LAO job: `{lao_job_id}` — {status}\n"
              f"- Output: `{run_dir or '(not reported)'}`\n"
              f"- {kind_label.title()}: {title}\n\n"
              f"Handed the finished {kind_label} to IRIS."),
        task=f"{priority or 'rotation pick'} / {region}",
        tags=["imagineindia", "media", "production", content_type],
    )

    enqueue_job(
        "ia",
        json.dumps({"run_dir": run_dir, "title": title,
                    "published": published, "lao_job": lao_job_id,
                    "content_type": content_type,
                    "publish_receipt": publish_receipt}),
        mode="report", tier="fast",
    )
    stages.clear_stage("muse")

    return {
        "agent": "MUSE",
        "mode": job.get("mode"),
        "content_type": content_type,
        "lao_job": lao_job_id,
        "status": status,
        "run_dir": run_dir,
        "title": title,
        "published": published,
        "publish_receipt": publish_receipt,
        "content": f"{kind_label.capitalize()} finished: {title}",
        "handed_to": {"agent": "IRIS"},
    }


# LinkedIn Authority's weekly pillars moved to Floor 3 with the channel:
# one-company/floors/floor_03_growth/lib/linkedin_authority.py (2026-10-13).


def _iris_dispatch_brand(job: dict[str, Any], brand: dict[str, Any], *,
                         head_id: str = "ia", head_name: str = "IRIS",
                         floor_id: str = "4") -> dict[str, Any]:
    """Hand a non-ImagineIndia Floor 4 brand to that brand's own worker.

    Deliberately a separate path from the ImagineIndia flow in _run_iris: that
    flow is live and produces real reels, so it is left exactly as it was.

    IRIS coordinates here rather than producing. (The scheduled LinkedIn
    Authority lane moved to ARES on Floor 3 on 2026-10-13 and no longer comes
    through here.)
    """
    task = str(job.get("task") or "")
    mode = str(job.get("mode") or "plan").strip().lower()
    is_vista_short = bool(re.search(r"\[vista-short\s+slot=(0900|1300|1800)\s+lane=([a-z_]+)\]", task, re.I))
    vista_production_spec: dict[str, Any] | None = None
    vista_match = re.search(r"\[vista-short\s+slot=(0900|1300|1800)\s+lane=([a-z_]+)\]", task, re.I)
    worker_id = "vista" if is_vista_short else brand["worker_agent_id"]
    display = brand.get("display_name", brand["slug"])
    # Standing authority is intentionally narrower than "brand is KAIROS".
    # Only ONE's canonical scheduled carousel fire may publish without a new
    # OLYMPUS click. Manual/ad-hoc aibyvineet jobs still arrive unapproved.
    # The envelope check here is text; the scheduler's receipt is checked just
    # before the worker is briefed.
    router = floors_bridge.load("floor_04_media", "brand_router") if head_id == "ia" else None
    routine_trigger_id = str(brand.get("routine_trigger_id") or "")
    routine_publish_authorized = bool(
        router is not None
        and router.routine_publish_allowed(brand.get("slug", ""), task)
    )
    if is_vista_short and vista_match:
        routine_trigger_id = f"daily-vista-short-{vista_match.group(1)}"
        routine_publish_authorized = True

    # stages.set_stage() keeps one record per agent_id, so a second concurrent
    # flow would overwrite this head's own worker_job pointer and make the
    # first flow invisible in the building. Decline with a reason instead.
    busy = floors_bridge.media_head_busy(head_id) if head_id == "ia" else None
    if busy:
        detail = str(busy.get("detail") or "").strip()
        return {
            "agent": head_name, "mode": mode, "handed_to": None,
            "content": (
                f"I'm already mid-flow on the other brand ({busy.get('stage')}"
                + (f" - {detail}" if detail else "")
                + f"). Ask me again for {display} once that one lands; running "
                "both at once would hide one of them."
            ),
            "note": "Declined to start a second Floor 4 flow.",
        }

    stages.set_stage(head_id, stages.RESEARCHING,
                     task.strip()[:180] or f"Choosing the next {display} post")

    # Per-brand history, never the floor's. Reading ImagineIndia's titles here
    # would make IRIS refuse an angle this channel has never published.
    prior = memory.prior_titles(floor_id, brand["vault_floor_name"])
    policy = _sonia_content_policy() if brand.get("slug") == "sonia_travel_vlogs" else {}
    duplicate_days = float(policy.get("duplicate_window_days") or 30)
    if brand.get("slug") == "sonia_travel_vlogs":
        # A Short must see the other Shorts, and must see them by date rather
        # than by position in a list. Counting list positions is not a calendar.
        # Two windows, because the policy names two rules. The destination gate
        # is same_day_destination_reuse and lasts a day: stretching it to the
        # 30-day duplicate window left Japan, Singapore, Thailand, Vietnam and
        # the UAE all "covered" and nothing could be commissioned. The story
        # gate is duplicate_window_days and is applied to the headline itself,
        # in _sonia_story_pick.
        prior = _sonia_recent_topics(
            prior, limit=60 if is_vista_short else 25,
            include_shorts=bool(is_vista_short),
            within_days=1.0 if is_vista_short else None)
        recent_stories = _sonia_recent_topics(
            [], limit=120, include_shorts=True,
            within_days=duplicate_days) if is_vista_short else []
    vista_commissions = _vista_same_day_commissions() if is_vista_short else []
    if vista_commissions:
        # travel_discovery rejects destination aliases found in prior titles.
        # Feed it the durable same-day queue before asking it to choose.
        prior = [
            " - ".join(filter(None, (row["headline"], row["destination"])))
            for row in vista_commissions
        ] + prior

    grounded_angle = task.strip()
    evidence_path = ""
    evidence_count = 0
    video_language = ""
    if brand.get("slug") == "sonia_travel_vlogs":
        reusable = _sanjeevani_research()
        if reusable is None:
            stages.clear_stage(head_id)
            return {"agent": head_name, "mode": "blocked", "_blocked": True,
                    "content": "Sonia Travel Vlogs stopped: Sanjeevani is unavailable.",
                    "blocked_reason": "Sanjeevani unavailable", "handed_to": None}
        try:
            # Scored, news-led discovery first (Sanjeevani travel_discovery, 2026-10-05): the latest travel news from
            # ANY country is pooled live, clustered, scored for how likely it is to go viral for Indian viewers,
            # age-verified and corroborated by fresh YouTube velocity; code picks the winner, the model only writes
            # it up. The old single-query dump (which produced a brief about thirteen countries) is the fallback
            # for when that module cannot run at all.
            story = _sonia_story_pick(reusable, prior, job["id"],
                                      check_all_prior=bool(is_vista_short),
                                      recent_stories=recent_stories)
            no_news_reason = story.get("reason", "") if story["status"] == "none" else ""
            travel_query = "Indian travellers international trip visa flight hotel"
            if story["status"] == "picked":
                eligible = story["evidence"]
                synthesis_prompt = story["prompt"]
                synthesis_evidence = story["synthesis_evidence"]
                snapshot = {}
            else:
                snapshot = reusable.collect_travel_video_signals(
                    travel_query, markets=["IN"], youtube_maximum=12,
                )
                eligible = list(snapshot.get("primary_signals") or []) + list(snapshot.get("context_signals") or [])
                synthesis_prompt = (
                    f"You are {head_name}, YouTube Studio floor head. Commission ONE travel-video idea for "
                    "Sonia Travel Vlogs from ONLY the evidence supplied. Produce a structured "
                    "TrendBrief containing: discovery date; target viewer; destination/topic; "
                    "viral search terms; why-now signal; evidence IDs and URLs; strongest truthful "
                    "hook; locations/scenes; practical flight/hotel/visa questions; volatile facts "
                    "requiring same-day verification; and explicit exclusions. Never invent a trend "
                    "or imply Sonia personally visited. End with COMMISSION: YES or NO. "
                    "The line 'Destination/Topic: <one country or city>' is mandatory. "
                    "The line 'Chosen headline: <the single evidence-backed idea selected>' is mandatory. "
                    f"Avoid prior topics: {json.dumps((recent_stories[:40] if is_vista_short else prior[:15]), ensure_ascii=False)}")
                synthesis_evidence = {"eligible": eligible, "catalog_evidence": [],
                                      "signal_policy": "Google Trends and YouTube public-search metadata are "
                                                       "primary discovery. News is context only. YouTube views are "
                                                       "a comparison signal, not proof of virality. If the fresh-news "
                                                       "gate found no unique story, commission a useful evergreen "
                                                       "travel decision only when current search/video evidence supports "
                                                       "it; never present it as breaking news.",
                                      "news_gate_reason": no_news_reason}
            evidence_count = len(eligible)
            if not eligible:
                output_dir = _home() / "agent_outputs"
                output_dir.mkdir(parents=True, exist_ok=True)
                diagnostic_file = output_dir / f"{job['id']}-yatra-research-diagnostic.json"
                diagnostic_file.write_text(json.dumps({
                    "request": task, "travel_query": travel_query,
                    "weights": snapshot.get("weights"),
                    "source_health": snapshot.get("source_health"),
                    "errors": snapshot.get("errors"),
                    "reason": "No current, usable Google Trends or YouTube metadata signals.",
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                stages.clear_stage(head_id)
                return {"agent": head_name, "mode": "blocked", "_blocked": True,
                        "content": "Sonia Travel Vlogs stopped: no usable current search-demand signals.",
                        "blocked_reason": "No usable Google Trends/news or YouTube metadata signals",
                        "evidence_count": 0, "research_diagnostic_path": str(diagnostic_file),
                        "handed_to": None}
            brief, note = _research_synthesis(synthesis_prompt, evidence=synthesis_evidence)
            if story["status"] != "picked" and brief and "COMMISSION: NO" not in brief.upper():
                brief, note, repeat, reselection_attempts = _sonia_unique_evergreen_brief(
                    brief,
                    note,
                    prompt=synthesis_prompt,
                    evidence=synthesis_evidence,
                    recent=recent_stories if is_vista_short else prior,
                )
                if reselection_attempts:
                    output_dir = _home() / "agent_outputs"
                    output_dir.mkdir(parents=True, exist_ok=True)
                    (output_dir / f"{job['id']}-evergreen-reselection.json").write_text(
                        json.dumps(reselection_attempts, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                if repeat:
                    stages.clear_stage(head_id)
                    reason = ("evergreen fallback failed the selection contract: " + repeat)
                    return {"agent": head_name, "mode": "blocked", "_blocked": True,
                            "content": f"Sonia Travel Vlogs stopped: {reason}",
                            "blocked_reason": reason, "evidence_count": evidence_count,
                            "story_ranking_path": story.get("ranking_path"), "handed_to": None}
            # A rejected proposal is useful operational evidence, not an
            # execution exception.  Preserve what Sanjeevani and IRIS saw so
            # the dashboard can explain *why* YATRA was not briefed.  Before
            # this, the only visible outcome was the generic string "IRIS did
            # not commission the candidate", which made a correct stop look
            # like a broken run.
            if not brief or "COMMISSION: NO" in brief.upper():
                rejection_reason = (
                    _marker(brief, "REJECTION_REASON")
                    or _marker(brief, "COMMISSION_REASON")
                    or _marker(brief, "REASON")
                    or note
                    or (f"{head_name} returned COMMISSION: NO based on the supplied "
                        "current evidence." if brief else
                        "Sanjeevani's local synthesis returned no commissionable "
                        "TrendBrief.")
                )
                output_dir = _home() / "agent_outputs"
                output_dir.mkdir(parents=True, exist_ok=True)
                rejection_file = output_dir / f"{job['id']}-yatra-rejected-brief.md"
                evidence_index = [
                    {key: row.get(key) for key in
                     ("id", "evidence_id", "title", "url", "source", "published_at", "score", "viral_score")
                     if row.get(key) is not None}
                    for row in eligible[:20]
                ]
                rejection_file.write_text(
                    f"# {head_name} — Sonia Travel Vlogs Rejected Candidate\n\n"
                    f"Request: {task}\n\n"
                    f"Eligible current evidence: {evidence_count}\n\n"
                    f"Rejection reason: {rejection_reason}\n\n"
                    f"## {head_name} local synthesis\n\n"
                    f"{brief or '(No TrendBrief returned by the local model.)'}\n\n"
                    "## Evidence index\n\n```json\n"
                    f"{json.dumps(evidence_index, ensure_ascii=False, indent=2)}\n```\n",
                    encoding="utf-8",
                )
                memory.remember(
                    agent=head_name, floor_id=floor_id, floor_name=brand["vault_floor_name"],
                    kind="YATRA Rejected TrendBrief",
                    body=f"Reason: {rejection_reason}\n\n{brief}", task=task,
                    tags=["sonia-travel-vlogs", "yatra", "sanjeevani", "rejected"],
                )
                stages.clear_stage(head_id)
                return {
                    "agent": head_name, "mode": "blocked", "_blocked": True,
                    "content": f"Sonia Travel Vlogs stopped: {rejection_reason}",
                    "blocked_reason": rejection_reason,
                    "evidence_count": evidence_count,
                    "rejected_brief_path": str(rejection_file),
                    "handed_to": None,
                }
            if story["status"] == "picked":
                # The model never saw the (very long) news URLs; attach the real ones and the scoring receipt so
                # the brief that travels on to the script writer carries its own proof.
                pick = story["pick"]
                video_language = sonia_video_language(pick)
                source_lines ="\n".join(f"- {t} - {u}" for t, u in zip(pick["headlines"][:6], (pick.get("urls") or []) + [""] * 6)
                                         if u)
                demand = (pick.get("demand") or {}).get("fastest") or {}
                brief = (brief.rstrip() + "\n\n## SANJEEVANI SELECTION RECEIPT\n"
                         f"Chosen from today's scored travel news: {pick['title']} (score {pick['score']}, "
                         f"{pick['n_sources']} outlets, latest report {pick.get('latest_age_hours')} h ago, first report "
                         f"{(pick.get('first_report') or {}).get('age_hours')} h ago).\n"
                         + (f"Fastest fresh YouTube video: {demand.get('title')} - {demand.get('views_per_hour')} views/h "
                            f"({demand.get('url')}).\n" if demand else "")
                         + (f"Source URLs:\n{source_lines}\n" if source_lines else "")
                         + f"Ranking file: {story['ranking_path']}\n"
                         + f"Video language: {SONIA_LANGUAGES[video_language]['label']} "
                           f"({'the story concerns India or Indian travellers' if video_language == 'hinglish' else 'the story is about travel outside India'}).\n")
            if is_vista_short and vista_match:
                slot, lane = vista_match.group(1), vista_match.group(2)
                weekday = datetime.now(ZoneInfo("Asia/Kolkata")).weekday()
                hooks = {
                    0: ("mistake_warning", "problem -> consequence -> correction -> save checklist"),
                    1: ("hidden_gem", "familiar destination -> unexpected alternative -> three reasons -> reveal"),
                    2: ("price_budget", "budget challenge -> cost components -> hidden cost -> final total"),
                    3: ("myth_reversal", "assumption -> contradiction -> evidence -> practical takeaway"),
                    4: ("destination_comparison", "A vs B -> three rounds -> winner by traveller type"),
                    5: ("countdown_curiosity", "open loop -> escalating discoveries -> strongest reveal -> replay ending"),
                    6: ("news_wall", "verified headline -> why it matters now -> three sourced facts -> practical takeaway"),
                }
                hook, structure = hooks[weekday]
                grounded_angle = (
                    f"# VISTA SLOT CONTRACT\nSlot: {slot}\nLane: {lane}\nHook family: {hook}\n"
                    f"Required structure: {structure}\nDuration: 25-40 seconds. Every beat adds information within 4 seconds. "
                    "The first 0-3 seconds must stop the swipe. Use a save/share/comment CTA appropriate to the hook. "
                    "Do not reuse a destination or information angle from the recent content calendar.\n\n"
                    + brief
                )
                # Save the researched contract before parsing so a malformed
                # handoff can be repaired without rediscovering the story.
                brief_checkpoint = _home() / "agent_outputs" / f"{job['id']}-vista-slot-brief.md"
                brief_checkpoint.parent.mkdir(parents=True, exist_ok=True)
                brief_checkpoint.write_text(grounded_angle, encoding="utf-8")
                vista_production_spec = _vista_spec_from_brief(
                    grounded_angle, slot, lane, hook
                )
                repeated = _vista_repeat_story(
                    vista_production_spec.get("story") or {}, vista_commissions
                )
                if repeated:
                    raise RuntimeError(
                        "VISTA same-day story blocked before production: "
                        f"{vista_production_spec['story'].get('headline') or vista_production_spec['story'].get('destination')} "
                        f"already belongs to {repeated['job_id']}"
                    )
            else:
                grounded_angle = brief
            output_dir = _home() / "agent_outputs"
            output_dir.mkdir(parents=True, exist_ok=True)
            evidence_file = output_dir / f"{job['id']}-{'vista-slot' if is_vista_short else 'yatra-trend'}-brief.md"
            evidence_file.write_text(
                f"# {head_name} -> {'VISTA SlotBrief' if is_vista_short else 'YATRA TrendBrief'}\n\nRequest: {task}\n\n"
                f"Researched by: Sanjeevani\n\n{grounded_angle}\n", encoding="utf-8")
            evidence_path = str(evidence_file)
            memory_body = grounded_angle
            if story.get("status") == "picked":
                memory_body = f"ANGLE: {story['pick']['title']}\n\n{grounded_angle}"
            if is_vista_short and vista_production_spec:
                story_record = vista_production_spec.get("story") or {}
                memory_body += (
                    "\n\nANGLE: "
                    + " - ".join(filter(None, (
                        str(story_record.get("headline") or "").strip(),
                        str(story_record.get("destination") or "").strip(),
                    )))
                )
            memory.remember(agent=head_name, floor_id=floor_id, floor_name=brand["vault_floor_name"],
                            kind="VISTA Slot Brief" if is_vista_short else "YATRA TrendBrief",
                            body=memory_body, task=task,
                            tags=["sonia-travel-vlogs", "vista" if is_vista_short else "yatra", "sanjeevani", "commissioned"])
        except Exception as exc:
            stages.clear_stage(head_id)
            reason = f"{type(exc).__name__}: {exc}"[:500]
            return {"agent": head_name, "mode": "blocked", "_blocked": True,
                    "content": f"Sonia Travel Vlogs stopped: {reason}.",
                    "blocked_reason": reason, "handed_to": None}

    if brand.get("slug") == "aibyvineet":
        grounded_angle, evidence_path, evidence_count = _kairos_grounded_angle(
            task, str(job.get("id") or ""), prior)
        if evidence_count:
            memory.remember(
                agent=head_name, floor_id=floor_id, floor_name=brand["vault_floor_name"],
                kind="aibyvineet Verified Sources", body=grounded_angle, task=task,
                tags=["aibyvineet", "postforge", "sanjeevani", "verified"])

    # ``worker`` names who this handover is actually for. Without it the
    # building can only guess, and a head briefing its second worker walks to
    # the first worker's desk instead. Carried on the walking and briefing
    # stages because that is exactly when the destination has to be known --
    # worker_job below only exists after the job has been queued.
    # head_briefs_worker (stages.py) owns the CARRYING_TO_WORKER/BRIEFING/
    # RECEIVING/AWAITING_WORKER choreography, including passing `worker=`
    # through the walking/briefing stages so the building knows which desk
    # to walk to -- see its docstring for why this can't just be a bare
    # set_stage/sleep/enqueue sequence per floor.
    if routine_publish_authorized:
        routine_publish_authorized = _job_fired_by_trigger(
            routine_trigger_id, str(job.get("id") or ""))
        if not routine_publish_authorized:
            print(f"[one-agents] {job.get('id')} names the {display} schedule but has no fire receipt; "
                  "the worker is briefed without publish authority", flush=True)
    worker = stages.head_briefs_worker(
        head_id, worker_id,
        carrying_detail=f"Taking the {display} brief to {worker_id.upper()}",
        briefing_detail=f"{worker_id.upper()}, next {display} post: {task.strip()[:110]}",
        awaiting_detail=f"Waiting on {worker_id.upper()} to produce the {display} post",
        enqueue=lambda: enqueue_job(
            worker_id,
            json.dumps({"brand": brand["slug"], "angle": grounded_angle,
                        "trendBrief": grounded_angle if brand["slug"] == "sonia_travel_vlogs" else "",
                        "priority": "", "prior_angles": prior[:15],
                        **({"language": video_language} if video_language else {}),
                        "origin_job": job["id"], "evidence_path": evidence_path,
                        "evidence_count": evidence_count,
                        **({"content_format": "youtube_short", "slot": vista_match.group(1),
                            "lane": vista_match.group(2),
                            "production_spec": vista_production_spec}
                           if is_vista_short and vista_match else {}),
                        "publish_authorized": routine_publish_authorized,
                        "publish_authority": (
                            f"standing_owner_policy:{routine_trigger_id}"
                            if routine_publish_authorized else "none"
                        )}),
            mode="execute",
            tier="fast",
        ),
    )

    return {
        "agent": head_name,
        "mode": mode,
        "brand": brand["slug"],
        "content": f"Briefed {worker_id.upper()} on the next {display} post.",
        "prior_posts_considered": len(prior),
        "sanjeevani_evidence_count": evidence_count,
        "evidence_path": evidence_path,
        "handed_to": {"agent": worker_id.upper(), "job_id": worker["id"]},
        "note": (
            f"{worker_id.upper()} will execute the head-approved brief and hand back its receipt."
        ),
    }


def _sanjeevani_reel() -> Any | None:
    """Sanjeevani's reel collector, for its metadata-only yt-dlp YouTube discovery."""
    import importlib.util
    path = Path(os.environ.get("SANJEEVANI_REEL_LIBRARY", r"E:\ONE-SUITE\sanjeevani\reel_research.py"))
    if not path.is_file():
        return None
    key = "sanjeevani_reel_research"
    cached = sys.modules.get(key)
    if cached is not None:
        return cached
    try:
        spec = importlib.util.spec_from_file_location(key, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(key, None)
        return None


def _kairos_video_search(query: str) -> list[dict[str, Any]]:
    """KAIROS's hook-library port: public YouTube metadata from the last 48 hours, via Sanjeevani."""
    reel = _sanjeevani_reel()
    if reel is None:
        raise RuntimeError("Sanjeevani reel collector is unavailable")
    return list(reel.discover_youtube(query, maximum=15).get("observations") or [])


def _kairos_web_search(queries: list[str], time_range: str) -> list[dict[str, Any]]:
    """KAIROS's layout-scout port: Sanjeevani's self-hosted SearXNG."""
    reusable = _sanjeevani_research()
    if reusable is None:
        raise RuntimeError("Sanjeevani research library is unavailable")
    rows, _mode = reusable.searxng(list(queries), time_range=time_range)
    return rows


def _kairos_read_page(url: str) -> str:
    """KAIROS's layout-scout reader: one public article's visible text.

    Through Sanjeevani's own bounded, TLS-verified fetcher, which refuses private
    and loopback addresses. The text is only matched against format names; it is
    never treated as an instruction.
    """
    import html as _html

    reusable = _sanjeevani_research()
    if reusable is None:
        raise RuntimeError("Sanjeevani research library is unavailable")
    raw = reusable._get(reusable._safe_public_url(url), timeout=12, limit=1_500_000, attempts=1)
    text = raw.decode("utf-8", "replace")
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", _html.unescape(text))[:200_000]


def _kairos_collect(query: str) -> dict[str, Any]:
    """KAIROS's evidence port: Sanjeevani, the only researcher a floor may use."""
    reusable = _sanjeevani_research()
    if reusable is None:
        raise RuntimeError("Sanjeevani research library is unavailable")
    return reusable.collect(query, markets=["IN", "US"])


def _kairos_verified_feed(pillar: str = "news", *,
                          force: bool = False) -> dict[str, Any]:
    """KAIROS's source port: PostForge's verified last-24-hours feed.

    The same call the cockpit tab makes, so the carousel job and the operator
    are looking at one list. Deliberately additive to `collect`, not a
    replacement: `collect` answers an open question, this answers "what is
    publishable in this pillar right now", and only items whose own source page
    proved their date and claim come back.
    """
    from openjarvis.postforge import feed

    return feed.refresh(pillar, force=force)


def _ports_accepts(ports_type: Any, name: str) -> bool:
    """Whether the floors-side Ports declares `name`.

    Ports is defined in one-company/floors, which is not part of this
    repository and is versioned separately, so a checkout can be older than
    this file. An unknown keyword would TypeError every KAIROS job -- carousel
    and revenue both -- so a new port is offered, never assumed.
    """
    import inspect

    try:
        return name in inspect.signature(ports_type).parameters
    except (TypeError, ValueError):
        return False


def _kairos_grounded_angle(task: str, job_id: str,
                           prior: list[str]) -> tuple[str, str, int]:
    """Ground the aibyvineet carousel brief in PostForge's verified feed.

    Deliberately the same shape as the LinkedIn Authority grounding in
    _iris_dispatch_brand: the head researches, the brief carries the evidence,
    and the worker executes a brief it did not invent. It needs nothing from
    the floors tree -- `angle`, `evidence_path` and `evidence_count` are
    existing fields of the handover JSON that this file already builds.

    The facts are copied from the feed verbatim rather than summarised by a
    model: every item has already been re-opened at its own URL and proved its
    date and claim, so a synthesis step here could only add drift.

    On any miss -- feed off, Sanjeevani absent, nothing verified today -- this
    returns the operator's own task untouched. That lane can publish under a
    standing authority, so a research failure has to leave today's behaviour
    exactly as it was rather than post something thinner.
    """
    switch = os.environ.get("ONE_KAIROS_VERIFIED_FEED", "1").strip().lower()
    if switch in ("0", "false", "no"):
        return task, "", 0

    pillar = (os.environ.get("ONE_KAIROS_PILLAR")
              or os.environ.get("TITAN_DEFAULT_PILLAR") or "news").strip()
    try:
        payload = _kairos_verified_feed(pillar)
    except Exception as exc:  # noqa: BLE001 - a research miss must not stop the lane
        print(f"[one-agents] {job_id} verified feed unavailable "
              f"({type(exc).__name__}: {exc}); briefing KAIROS with "
              "the operator's own angle", flush=True)
        return task, "", 0

    items = list(payload.get("items") or [])
    if not items:
        print(f"[one-agents] {job_id} verified feed returned nothing inside "
              f"{payload.get('freshnessHours')}h ({payload.get('rejected')} rejected); "
              "briefing KAIROS with the operator's own angle", flush=True)
        return task, "", 0

    lines = [
        f"{index}. {item.get('headline', '')}"
        f"\n   Source: {item.get('source', '')}"
        f" | Published: {item.get('publishedAt', '')}"
        f"\n   URL: {item.get('url', '')}"
        f"\n   Summary: {item.get('summary', '')}"
        for index, item in enumerate(items, start=1)
    ]
    body = "\n".join(lines)
    angle = (
        f"{task.strip()}\n\n"
        "Use ONLY these source-verified items from the last "
        f"{payload.get('freshnessHours')} hours. Each one was re-opened at its "
        "own URL and kept only because the page proved its date and supported "
        "its headline. Do not introduce any other claim, product name, number "
        "or date.\n\n"
        f"{body}"
    )
    if prior:
        seen = json.dumps(prior[:15], ensure_ascii=False)
        angle += f"\n\nAvoid repeating these prior angles: {seen}"

    output_dir = _home() / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_file = output_dir / f"{job_id}-aibyvineet-sources.md"
    evidence_file.write_text(
        f"# IRIS - aibyvineet verified sources\n\nPillar: {pillar}\nRequest: {task}\n"
        f"Window: {payload.get('freshnessHours')}h"
        f" | Rejected: {payload.get('rejected')}\n\n"
        f"Researched by: Sanjeevani, verified by PostForge\n\n{body}\n",
        encoding="utf-8")
    return angle, str(evidence_file), len(items)


def _kairos_chatgpt(prompt: str) -> tuple[str, str]:
    """One carousel copy candidate through LAO's logged-in ChatGPT session.

    The draft path PEITHO and MUSE already use: the session the LAO robot keeps
    open on the existing subscription, not a metered API.
    """
    carousel = floors_bridge.load("floor_04_media", "aibyvineet_carousel")
    markers = list(getattr(carousel, "COPY_MARKERS", ()) or ())
    output, error = _run_peitho_lao_draft([prompt], expected_markers=markers or None, timeout_ms=240000)
    return str(output.get("angle_1") or ""), error


def _kairos_lao_images(prompts: list[str], target_dir: Path, job_id: str = "") -> dict[int, str]:
    """PostForge-style slides through LAO's reusable ChatGPT image component.

    One draft, one logged-in browser, one chat for every slide - the first
    version opened a new chat per image and filled ChatGPT's history with five
    unrelated conversations for one carousel. Each file lands
    at an absolute host path: the handler joins its artifacts directory with
    the filename, and joining with an absolute path yields that path - the same
    way SCRIBE's cover refresh already gets its art back. A failed step ends
    the whole draft, so a second pass asks only for what is still missing.

    Heartbeats, deliberately never attaches. job_recovery re-queues an attached
    job after a restart, and KAIROS does not resume: it would write fresh copy
    and draw a second set of images. An honest failure after a restart is
    better than spending the subscription's image allowance twice.
    """
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool

    target_dir.mkdir(parents=True, exist_ok=True)
    wanted = {index: target_dir / f"visual-{index + 1:02d}.png" for index in range(len(prompts))}

    def ready() -> dict[int, str]:
        return {i: str(p) for i, p in wanted.items() if p.is_file() and p.stat().st_size > 0}

    tool = LaoOrchestratorTool()
    poll_seconds = float(os.environ.get("ONE_LAO_POLL_SECONDS", "30"))
    max_wait = float(os.environ.get("ONE_KAIROS_IMAGES_MAX_WAIT", "5400"))
    terminal = {"Successful", "Failed", "Stopped", "Cancelled", "Faulted"}
    for attempt in (1, 2):
        missing = [index for index in wanted if index not in ready()]
        if not missing:
            break
        steps: list[dict[str, Any]] = [
            {"action": "open_browser"},
            {"action": "get_credential", "args": {"assetName": "chatgptLogin", "as": "chatgpt_credential"}},
            {"action": "chatgpt_login_with_credential", "args": {"credential": "{{chatgpt_credential}}"}},
        ]
        # One fresh chat for the whole carousel, then every slide in it. Fresh-
        # chat recovery is switched off so a stall is nudged in place instead of
        # silently opening another conversation.
        steps.append({"action": "navigate", "args": {"url": "https://chatgpt.com/"}})
        for position, index in enumerate(missing):
            steps.append({"action": "generate_and_download_chatgpt_image", "args": {
                "prompt": prompts[index], "filename": str(wanted[index]),
                "stall_timeout_ms": 180000, "max_attempts": 4, "poll_ms": 3000,
                "always_nudge_fresh_image": position == 0,
                "allow_fresh_chat_recovery": False,
                "as": f"visual_{index + 1:02d}"}})
        started = tool.execute(action="run_draft", steps=steps,
                               draft_name="kairos-carousel-visuals", folder_id=_PEITHO_LAO_FOLDER_ID)
        if not started.success:
            if attempt == 1:
                raise RuntimeError(f"LAO refused the visuals draft: {str(started.content)[:300]}")
            break
        try:
            lao_job_id = ((json.loads(started.content).get("job") or {}).get("id")) or ""
        except json.JSONDecodeError:
            lao_job_id = ""
        if not lao_job_id:
            break
        status = "Pending"
        deadline = time.time() + max_wait
        while time.time() < deadline:
            time.sleep(poll_seconds)
            if job_id:
                job_recovery.heartbeat(_connect, job_id)
            probe = tool.execute(action="status", process_name="", scope="production", job_id=lao_job_id)
            if probe.success:
                try:
                    status = str((json.loads(probe.content).get("job") or {}).get("status") or status)
                except json.JSONDecodeError:
                    pass
            stages.set_stage("kairos", stages.EXECUTING,
                             f"LAO is drawing slide visuals · {len(ready())}/{len(prompts)} ready · {status}",
                             lao_job=lao_job_id)
            if status in terminal:
                break
    return ready()


def _iris_dispatch_revenue(job: dict[str, Any], slug: str) -> dict[str, Any]:
    """IRIS briefs KAIROS, the Floor 4 revenue agent, on one brand's money work.

    Added 2026-09-16: the Chairman made KAIROS responsible for turning the
    brands' reach into income. KAIROS reads, prices and drafts; sending,
    signing and spending stay with the Chairman.
    """
    task = str(job.get("task") or "")
    display = "ImagineIndia" if slug == "imagineindia" else "AI by Vineet" if slug == "aibyvineet" else slug
    busy = floors_bridge.media_head_busy("ia")
    if busy:
        detail = str(busy.get("detail") or "").strip()
        return {"agent": "IRIS", "mode": "execute", "handed_to": None,
                "content": (f"I'm mid-flow on another Floor 4 job ({busy.get('stage')}"
                            + (f" - {detail}" if detail else "")
                            + f"). Ask me again for {display}'s revenue review once it lands."),
                "note": "Declined to start a second Floor 4 flow."}
    worker = stages.head_briefs_worker(
        "ia", "kairos",
        carrying_detail=f"Taking the {display} revenue brief to KAIROS",
        briefing_detail=f"KAIROS, where is {display}'s reach leaking money?",
        awaiting_detail=f"Waiting on KAIROS's {display} revenue review",
        enqueue=lambda: enqueue_job(
            "kairos",
            json.dumps({"mode": "revenue", "brand": slug, "task": task, "origin_job": job["id"]}),
            mode="execute", tier="fast",
        ),
    )
    return {"agent": "IRIS", "mode": "execute", "brand": slug,
            "content": f"Briefed KAIROS on {display}'s revenue review.",
            "handed_to": {"agent": "KAIROS", "job_id": (worker or {}).get("id") if isinstance(worker, dict) else None}}


def _iris_report_revenue(job: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """IRIS reports KAIROS's revenue review upward: the leaks, the drafts, and what only the Chairman can do."""
    slug = str(payload.get("brand") or "imagineindia")
    display = "ImagineIndia" if slug == "imagineindia" else "AI by Vineet" if slug == "aibyvineet" else slug
    pulse = payload.get("format") == "revenue_pulse"
    product = payload.get("format") == "product_pack"
    what = "daily pulse" if pulse else "product pack" if product else "revenue review"
    stages.set_stage("ia", stages.REPORTING, f"Reporting {display}'s {what}")
    if str(payload.get("status") or "") == "stopped":
        message = (f"Sir, KAIROS could not finish {display}'s {what}.\n\n"
                   f"Reason: {payload.get('note') or payload.get('error') or 'no reason was given'}")
    elif product:
        missing = payload.get("missing") or []
        message = (
            f"Sir, KAIROS has built {display}'s first sellable product.\n\n"
            f"{payload.get('title') or 'Product pack'}: {payload.get('made')} of "
            f"{payload.get('requested')} images are ready"
            + (f"; {', '.join(missing)} did not come back." if missing else ".")
            + "\n\nNothing is priced and nothing is listed - the store, the price and the payout "
            "are yours.\n\n"
            f"Images and listing copy: {payload.get('run_dir') or payload.get('output') or '(not reported)'}"
        )
    elif pulse:
        def count(value: Any) -> str:
            return f"{int(value):,}" if isinstance(value, (int, float)) else "n/a"

        change = payload.get("follower_change")
        alerts = "\n".join(f"- {alert}" for alert in payload.get("alerts") or []) or "- none, all good"
        message = (
            f"Sir, {display}'s daily pulse.\n\n"
            f"Followers: {count(payload.get('followers'))}"
            + (f" ({'+' if change >= 0 else ''}{change} since yesterday)" if isinstance(change, int) else "")
            + f"\nLast 24h: reach {count(payload.get('reach_1d'))}, profile visits "
            f"{count(payload.get('profile_views_1d'))}, link taps {count(payload.get('link_taps_1d'))}\n"
            f"Bio: collab email {'present' if payload.get('has_contact') else 'MISSING'}, "
            f"link {'present' if payload.get('has_link') else 'MISSING'}\n\n"
            f"Alerts:\n{alerts}\n\nFull pulse: {payload.get('output') or '(not reported)'}"
        )
    else:
        leaks = "\n".join(f"- {leak}" for leak in payload.get("leaks") or []) or "- none found"
        actions = "\n".join(f"- {ask}" for ask in payload.get("chairman_actions") or [])
        rate = payload.get("profile_visit_rate_pct")
        message = (
            f"Sir, KAIROS has finished {display}'s revenue review.\n\n"
            f"Reach in the last 28 days: {int(payload.get('reach_28d') or 0):,}"
            + (f"; only {rate}% of those accounts opened the profile." if rate is not None else ".")
            + f"\n\nWhere the money leaks:\n{leaks}\n\n"
            f"{int(payload.get('pitches_drafted') or 0)} brand pitches are drafted and waiting for your approval - "
            "nothing has been sent.\n\n"
            + (f"Only you can do these:\n{actions}\n\n" if actions else "")
            + f"Full review: {payload.get('output') or '(not reported)'}"
        )
    output_dir = _home() / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job['id']}.md"
    heading = "Daily Pulse" if pulse else "Product Pack" if product else "Revenue Report"
    output_path.write_text(f"# IRIS - {heading} ({display})\n\n{message}\n", encoding="utf-8")
    router = floors_bridge.load("floor_04_media", "brand_router")
    brand = router.route("", explicit=slug) if router is not None else None
    remembered = memory.remember(
        agent="IRIS", floor_id="4",
        floor_name=(brand or {}).get("vault_floor_name") or "Media & Content",
        kind=heading, body=message, tags=[slug, "media", "revenue"] + (["pulse"] if pulse else []),
    )
    time.sleep(2.0)
    stages.clear_stage("ia")
    return {"agent": "IRIS", "mode": "report", "brand": slug, "content": message,
            "format": payload.get("format") or "revenue_review",
            "output": str(output_path), "vault_note": (remembered or {}).get("path")}


def _company_revenue_ledger() -> Any | None:
    """one-company's revenue ledger (floors/_services/revenue/money.py), loaded by path."""
    import importlib.util
    key = "one_company_revenue_money"
    if key in sys.modules:
        return sys.modules[key]
    path = floors_bridge.floors_root() / "_services" / "revenue" / "money.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(key, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
        return module
    except Exception:  # noqa: BLE001
        sys.modules.pop(key, None)
        return None


def _run_kairos(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 4 worker for aibyvineet: PostForge's carousel job, rebuilt on ONE.

    Its logic lives in one-company/floors. This wrapper only injects the ports:
    Sanjeevani for evidence and local copy, PostForge's verified feed for
    publishable sources, LAO for ChatGPT copy and visuals, and the one-media
    host for public URLs. ``verified_feed`` is offered only when the floors-side
    Ports declares it, so an older floors checkout keeps working untouched. The Instagram publisher goes
    through social_accounts' cross-post guard, and KAIROS itself refuses to
    call it while the brand is not marked postable. If the floors tree is
    unavailable this degrades to the local planner rather than failing the job.
    """
    kairos = floors_bridge.load("floor_04_media", "kairos_agent")
    if kairos is None:
        return _local_plan(job)
    media = floors_bridge.load("floor_04_media", "aibyvineet_publish")
    host = media.MediaHost.from_env() if media is not None else None
    job_id = str(job.get("id") or "")

    def upload(path: Path, pathname: str) -> str:
        return media.upload_slide(host, path, pathname)

    def publish(image_urls: list[str], caption: str) -> dict[str, Any]:
        from openjarvis.core import social_accounts

        account = social_accounts.resolve_for_post("aibyvineet", "instagram")
        return media.publish_carousel(
            account_id=account.account_id, token=account.token, image_urls=image_urls,
            caption=caption, graph_base=social_accounts.PLATFORMS["instagram"]["graph_base"])

    def insights(path: str, params: dict[str, Any]) -> dict[str, Any]:
        # Read-only: how earlier carousels did. The account comes from the vault
        # by channel, never from a shared environment variable.
        from openjarvis.core import social_accounts

        account = social_accounts.get_account("aibyvineet", "instagram")
        if account is None:
            raise RuntimeError("aibyvineet's Instagram account is not in ONE's vault")
        reader = media.graph_reader(token=account.token,
                                    graph_base=social_accounts.PLATFORMS["instagram"]["graph_base"])
        return reader(path, params)

    def graph_for(slug: str):
        # Revenue mode reads any Floor 4 account KAIROS earns for, each from its
        # own vault channel - read-only, token in a header.
        from openjarvis.core import social_accounts

        account = social_accounts.get_account(slug, "instagram")
        if account is None:
            raise RuntimeError(f"{slug}'s Instagram account is not in ONE's vault")
        return media.graph_reader(token=account.token,
                                  graph_base=social_accounts.PLATFORMS["instagram"]["graph_base"])

    def declare_revenue_source(floor_id: str, name: str, *, connected: bool, blocked_on: str = "") -> Any:
        ledger = _company_revenue_ledger()
        if ledger is None:
            raise RuntimeError("the company revenue ledger is unavailable")
        return ledger.declare_source(floor_id, name, connected=connected, blocked_on=blocked_on)

    ports: dict[str, Any] = dict(
        research=_research_synthesis,
        remember=memory.remember,
        set_stage=stages.set_stage,
        clear_stage=stages.clear_stage,
        enqueue=enqueue_job,
        output_dir=_home() / "agent_outputs",
        collect=_kairos_collect if _sanjeevani_research() is not None else None,
        chatgpt=_kairos_chatgpt,
        generate_images=lambda prompts, target: _kairos_lao_images(prompts, target, job_id=job_id),
        upload=upload if host is not None else None,
        publish=publish if media is not None else None,
        confirm_receipt=stages.worker_confirms_receipt,
        insights=insights if media is not None and hasattr(media, "graph_reader") else None,
        video_search=_kairos_video_search if _sanjeevani_reel() is not None else None,
        web_search=_kairos_web_search if _sanjeevani_research() is not None else None,
        read_page=_kairos_read_page if _sanjeevani_research() is not None else None,
        graph_for=graph_for if media is not None and hasattr(media, "graph_reader") else None,
        declare_revenue_source=declare_revenue_source,
    )
    if _ports_accepts(kairos.Ports, "verified_feed"):
        ports["verified_feed"] = _kairos_verified_feed
    return kairos.run(job, kairos.Ports(**ports))


def _herald_v2(job: dict[str, Any], payload: dict[str, Any], v2p: dict[str, Any],
               resume_id: str) -> dict[str, Any] | None:
    """LinkedIn v2: write -> gate -> render -> publish. Returns None ONLY when it
    fell back before anything was published (the v1 post then runs)."""
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool

    tool = LaoOrchestratorTool()
    home, roots = _home(), _YATRA_ROBOT_ARTIFACTS
    poll = float(os.environ.get("ONE_LAO_POLL_SECONDS", "15"))
    heartbeat = lambda: job_recovery.heartbeat(_connect, job["id"])  # noqa: E731
    attach = lambda lao_job: job_recovery.attach(_connect, job["id"], lao_job)  # noqa: E731

    if resume_id:  # ONE restarted while the publish run was in flight: only finish tracking it
        done = linkedin_growth.finish_publish(lao_job=resume_id, tool=tool, heartbeat=heartbeat, roots=roots, poll=poll)
        draft = {}
        made = {"draft": draft, "verdict": {"warnings": []}}
        return _herald_v2_deliver(job, payload, v2p, made, done)

    made = linkedin_growth.produce(v2_payload=v2p, job_id=str(job["id"]), tool=tool, home=home, roots=roots, poll=poll)
    if made["status"] != "ready":
        print(f"[one-agents] LinkedIn v2 fell back to the v1 post: {made.get('reason')}", flush=True)
        stages.clear_stage("herald")
        return None

    authorized = bool(payload.get("publish_authorized"))
    mode = str(v2p.get("publish_mode") or "auto")
    if not authorized or mode != "auto":
        text = linkedin_growth.digest(v2_payload=v2p, draft=made["draft"], verdict=made["verdict"], published=False,
                                      fallback="held for review" if authorized else "no standing publish authority")
        (Path(made["out_dir"]) / "digest.txt").write_text(text, encoding="utf-8")
        stages.clear_stage("herald"); stages.clear_stage("ares")
        return {"agent": "HERALD", "mode": "held", "published": False, "v2": True, "content": text,
                "draft_dir": made["out_dir"], "handed_to": None}

    stages.set_stage("herald", stages.EXECUTING, f"Publishing the LinkedIn {v2p['format']}",
                     lao_process=linkedin_growth.PUBLISH_PROCESS)
    done = linkedin_growth.publish(ready=made, v2_payload=v2p, tool=tool, attach=attach, heartbeat=heartbeat,
                                   roots=roots, poll=poll)
    if done["status"] == "not_started" or (done["status"] == "failed" and done.get("unknown_action")):
        # Nothing reached LinkedIn: the publish run never started, or LAO's robot does not yet know the
        # document action. Safe to let the v1 post fill the slot.
        print(f"[one-agents] LinkedIn v2 publish did not start ({done}); v1 post follows", flush=True)
        stages.clear_stage("herald")
        return None
    return _herald_v2_deliver(job, payload, v2p, made, done)


def _herald_v2_deliver(job: dict[str, Any], payload: dict[str, Any], v2p: dict[str, Any],
                       made: dict[str, Any], done: dict[str, Any]) -> dict[str, Any]:
    if done["status"] != "published":
        stages.clear_stage("herald"); stages.clear_stage("ares")
        # The run started, so it may have posted: never retry and never fall back to v1 (a double post).
        raise RuntimeError(f"LinkedIn v2 publish ended as {done.get('lao_status')}; not retried because it may have posted")
    draft = made.get("draft") or {}
    story = v2p["story"]
    text = linkedin_growth.digest(v2_payload=v2p, draft=draft, verdict=made.get("verdict") or {"warnings": []},
                                  published=True, receipt=f"LAO job {done['lao_job']}") if draft else ""
    linkedin_growth.record(home=_home(), v2_payload=v2p, draft=draft or {"caption": "", "format": v2p.get("format")},
                           published=True, lao_job=done["lao_job"])
    stages.set_stage("herald", stages.CARRYING_TO_HEAD, "Taking the verified LinkedIn receipt back to ARES")
    report = enqueue_job("ares", json.dumps({
        "brand": "linkedin_authority", "worker": "herald", "title": story.get("title") or "LinkedIn Authority post",
        "format": f"LinkedIn {v2p.get('format')}", "published": True, "output": f"LAO job {done['lao_job']}",
        "origin_job": payload.get("origin_job"), "v2_digest": text}), mode="report", tier="fast")
    stages.set_stage("herald", stages.DELIVERING, "Delivered the LinkedIn publish receipt to ARES")
    time.sleep(1); stages.clear_stage("herald")
    return {"agent": "HERALD", "mode": "publish", "published": True, "v2": True, "lao_job": done["lao_job"],
            "handed_to": {"agent": "ARES", "job_id": report["id"]}}


def _run_herald(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 3 LinkedIn worker: LAO executes; HERALD tracks and reports to ARES."""
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool
    payload = _json_task(job)
    if str(payload.get("brand") or "") != "linkedin_authority":
        raise RuntimeError("HERALD refuses work outside linkedin_authority")
    stages.worker_confirms_receipt("herald", "Received the LinkedIn Authority brief from ARES")
    v2_payload = payload.get("v2") if isinstance(payload.get("v2"), dict) else None
    if v2_payload:
        outcome = _herald_v2(job, payload, v2_payload, job_recovery.resume_target(job))
        if outcome is not None:
            return outcome
        # None: v2 fell back before anything was published, so the v1 post below fills the slot.
    # Standing authority is the daily trigger's alone (floor_03_growth/channels.json):
    # ARES sets publish_authorized only when the scheduler's own fire receipt
    # exists. Anything else (a hand-typed dispatch) is not a post.
    # A job resuming after a restart is already tracking a started LAO run, so
    # the gate applies only to starting one.
    if not payload.get("publish_authorized") and not job_recovery.resume_target(job):
        stages.clear_stage("herald"); stages.clear_stage("ares")
        reason = ("No standing publish authority on this job: only the daily-linkedin-authority "
                  "trigger's own fire may post without a fresh approval.")
        return {"agent": "HERALD", "mode": "blocked", "_blocked": True, "published": False,
                "content": reason, "blocked_reason": reason, "handed_to": None}
    tool = LaoOrchestratorTool()
    process_name = "Daily LinkedIn Authority Post"
    resume_id = job_recovery.resume_target(job)
    if resume_id:
        lao_job_id = resume_id
    else:
        started = tool.execute(action="start", mode="publish", process_name=process_name,
                               scope="production", confirm_publish=True)
        if not started.success:
            raise RuntimeError(f"LAO refused LinkedIn production: {started.content}")
        started_payload = started.metadata or {}
        lao_job_id = str((started_payload.get("job") or {}).get("id") or "")
        if not lao_job_id:
            raise RuntimeError("LAO started LinkedIn production without returning a job id")
        job_recovery.attach(_connect, job["id"], lao_job_id)
    terminal = {"Successful", "Failed", "Stopped", "Cancelled", "Faulted"}
    deadline = time.time() + float(os.environ.get("ONE_LINKEDIN_MAX_WAIT_SECONDS", "3600"))
    status = "Pending"
    last: dict[str, Any] = {}
    while time.time() < deadline:
        stages.set_stage("herald", stages.EXECUTING, f"Publishing LinkedIn authority post · LAO {status}",
                         lao_job=lao_job_id, lao_process=process_name)
        time.sleep(float(os.environ.get("ONE_LAO_POLL_SECONDS", "30")))
        job_recovery.heartbeat(_connect, job["id"])
        probe = tool.execute(action="status", process_name=process_name, scope="production", job_id=lao_job_id)
        if not probe.success:
            continue
        last = probe.metadata or {}
        status = str((last.get("job") or {}).get("status") or status)
        # LAO marks a failed parent Retried and creates a newer child job.
        # Follow that child so HERALD reports the actual publish result rather
        # than waiting forever on the bookkeeping parent.
        if status == "Retried":
            latest_probe = tool.execute(action="status", process_name=process_name, scope="production")
            child = (latest_probe.metadata or {}).get("job") if latest_probe.success else None
            if child and child.get("id") and child.get("id") != lao_job_id:
                lao_job_id = str(child["id"])
                status = str(child.get("status") or "Pending")
                stages.set_stage("herald", stages.EXECUTING, f"Following LAO retry child · {status}",
                                 lao_job=lao_job_id, lao_process=process_name)
                continue
        if status in terminal:
            break
    if status != "Successful":
        stages.clear_stage("herald"); stages.clear_stage("ares")
        raise RuntimeError(f"LinkedIn Authority workflow ended as {status}")
    stages.set_stage("herald", stages.CARRYING_TO_HEAD, "Taking the verified LinkedIn receipt back to ARES")
    report = enqueue_job("ares", json.dumps({"brand":"linkedin_authority", "worker":"herald",
        "title":"Daily LinkedIn Authority Post", "format":"LinkedIn post", "published":True,
        "output":f"LAO job {lao_job_id}", "origin_job":payload.get("origin_job")}), mode="report", tier="fast")
    stages.set_stage("herald", stages.DELIVERING, "Delivered the LinkedIn publish receipt to ARES")
    time.sleep(1); stages.clear_stage("herald")
    return {"agent":"HERALD", "mode":"publish", "published":True, "lao_job":lao_job_id,
            "handed_to":{"agent":"ARES", "job_id":report["id"]}}


_YATRA_TOOLS = Path(r"C:\Users\pc\Documents\LAO")
# LAO's API lists artifacts by their path inside the backend container and
# offers no route to download one, but the robot that ran the job also wrote
# them to its own folder on this machine -- which robot took the job is not
# known in advance, so all three are searched.
_YATRA_ROBOT_ARTIFACTS = (
    # The recovered Windows robot now runs from ONE's durable worker tree.
    # Keep the legacy Claude session root as a read-compatible fallback for
    # jobs created before that recovery; collectors must follow the robot that
    # actually executed the job instead of assuming one historical checkout.
    Path(r"E:\ONE-Suite\lao-robot\worker"),
    Path(r"C:\Users\pc\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude"
         r"\local-agent-mode-sessions\cb3dc5b9-a76c-45ff-bbcf-b330fe30c84a"
         r"\21738b93-8e02-4c20-a83c-0abb35d85c72\local_374e1c90-a56c-4744-840b-8f0118a3547a"
         r"\outputs\lao-platform\robot-worker"),
)
_YATRA_NARRATION_PROCESS = "Sonia YATRA - Narration"
# Where a video's own footage, narration and manifests live. This has to stay
# equal to ASSET_ROOT in yatra-acquisition/acquire_scenes.py: the tool writes
# acquisition-manifest.json there, and when the two drifted apart the agent
# read an absent manifest and reported footage with no per-scene coverage at
# all, which is the one thing that receipt exists to show.
_YATRA_ASSET_ROOT = Path(r"C:\Users\pc\Downloads\YATRA")
_YATRA_EDIT_TOOLS = _YATRA_TOOLS / "yatra-edit"
_YATRA_UPLOAD_PROCESS = "Sonia YATRA - Upload"
_YATRA_EXPECTED_SCENES = 20
# Sonia's channel, compared against the signed-in one before an upload starts.
# The robot's Chrome has been found signed into a different channel, and a
# YouTube upload cannot be moved between channels afterwards.
_SONIA_CHANNEL = "Sonia Travel Vlogs"


_YATRA_SLUG_FILLER = {
    "a", "an", "and", "are", "for", "from", "in", "is", "of", "on", "or", "the",
    "to", "you", "your", "need", "know", "this", "that", "with", "what", "why",
}


def _yatra_slug(text: str) -> str:
    """A stable folder name per video, so a re-run reuses footage already bought."""
    words = [w for w in re.findall(r"[a-z0-9]+", str(text).lower())
             if w not in _YATRA_SLUG_FILLER]
    return "-".join(words[:6]) or "untitled-video"


def _yatra_preproduction_file(lao_job_id: str) -> Path:
    for root in _YATRA_ROBOT_ARTIFACTS:
        for folder in ("artifacts", "artifacts-02", "artifacts-studio"):
            candidate = root / folder / lao_job_id / "yatra_preproduction.json"
            if candidate.exists():
                return candidate
    raise RuntimeError(
        f"LAO job {lao_job_id} reported success but left no yatra_preproduction.json "
        "on this machine, so there is no scene plan to acquire footage against."
    )


def _validate_yatra_contract(record: dict[str, Any], expected_scenes: int | None = None) -> dict[str, Any]:
    """Validate the writer-to-voice-to-acquisition contract before voice spend."""
    expected_scenes = int(expected_scenes or record.get("expected_scene_count") or _YATRA_EXPECTED_SCENES)
    script = str(record.get("full_script") or "")
    cue_count = len(re.findall(r"(?m)^\[\d{1,2}:\d{2}(?:\s*[-–—]\s*\d{1,2}:\d{2})?\]", script))
    parser_path = _YATRA_TOOLS / "yatra-acquisition" / "acquire_scenes.py"
    spec = importlib.util.spec_from_file_location("yatra_contract_parser", parser_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load YATRA scene parser: {parser_path}")
    module = importlib.util.module_from_spec(spec)
    # acquire_scenes imports its small sibling helpers (progress,
    # robot_chrome) by module name because it normally runs with this folder
    # as cwd.  Preserve that import context when reusing its parser in ONE.
    sys.path.insert(0, str(parser_path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    scenes = list(module.parse_scenes(str(record.get("scene_plan") or "")))
    ids = [str(scene.get("id") or "") for scene in scenes]
    missing_queries = [sid for sid, scene in zip(ids, scenes)
                       if not str(scene.get("query") or "").strip()]
    bad_times = [sid for sid, scene in zip(ids, scenes)
                 if float(scene.get("seconds") or 0) <= 0]
    expected_ids = [str(i) for i in range(1, expected_scenes + 1)]
    problems = []
    if cue_count != expected_scenes:
        problems.append(f"narration has {cue_count}/{expected_scenes} timed cues")
    if ids != expected_ids:
        problems.append(f"visual plan IDs are {ids or 'none'}, expected 1..{expected_scenes}")
    if missing_queries:
        problems.append("missing scene-specific stock query: " + ", ".join(missing_queries))
    if bad_times:
        problems.append("unreadable/zero time span: " + ", ".join(bad_times))
    # Validate the same saved plan against every downstream reader before
    # FABULA spends credits. Previously acquisition understood YAML-list scenes
    # while graphics/edit/OBS silently returned empty plans hours later.
    for name, path, parser, value in (
        ("graphics", _YATRA_TOOLS / "yatra-edit" / "plan_to_specs.py", "parse_blocks", str(record.get("scene_plan") or "")),
        ("edit", _YATRA_TOOLS / "yatra-edit" / "assemble.py", "parse_scenes", str(record.get("scene_plan") or "")),
        ("OBS", _YATRA_TOOLS / "yatra-capture" / "plan_captures.py", "parse_capture_plan", str(record.get("browser_capture_plan") or "")),
    ):
        if name == "OBS" and not value.strip():
            continue
        parser_spec = importlib.util.spec_from_file_location(f"yatra_contract_{name}", path)
        if parser_spec is None or parser_spec.loader is None:
            problems.append(f"{name} parser unavailable: {path}")
            continue
        parser_module = importlib.util.module_from_spec(parser_spec)
        sys.path.insert(0, str(path.parent))
        try:
            parser_spec.loader.exec_module(parser_module)
            parsed = getattr(parser_module, parser)(value)
        except Exception as exc:
            problems.append(f"{name} parser failed: {exc}")
            continue
        finally:
            sys.path.pop(0)
        if name == "graphics":
            actual = [str(item[0]) for item in parsed]
        elif name == "edit":
            actual = [str(item.get("id") or "") for item in parsed]
            if any(float(item.get("seconds") or 0) <= 0 for item in parsed):
                problems.append("edit parser has zero-duration scenes")
        else:
            actual = parsed
        if name != "OBS" and actual != expected_ids:
            problems.append(f"{name} parser IDs are {actual or 'none'}, expected 1..{expected_scenes}")
        if name == "OBS" and not actual:
            problems.append("OBS capture plan has no parseable source blocks")
    if problems:
        raise RuntimeError("YATRA preproduction contract is incomplete; narration was not started and no voice "
                           "credits were spent. " + "; ".join(problems))
    return {"scene_count": len(scenes), "cue_count": cue_count,
            "query_count": len(scenes) - len(missing_queries)}


def _yatra_editorial_hold(record: dict[str, Any]) -> bool:
    """Do not buy voice for a structurally valid draft the writer rejected."""
    gate = str(record.get("quality_gate") or "")
    return bool(re.search(r"(?im)^\s*final_verdict\s*:\s*REWRITE\s*$", gate))


def _normalize_yatra_json_block(value: Any) -> Any:
    """Remove only ChatGPT's rendered JSON language label from JSON fields."""
    if not isinstance(value, str):
        return value
    cleaned = re.sub(r"^\s*(?:```json\s*|json\s+)", "", value,
                     flags=re.IGNORECASE).strip()
    return cleaned.removesuffix("```").strip()


def _yatra_motion_manifest(asset_root: Path) -> Path:
    """Prepare cached H.264 proxies for ProRes 10-bit inputs before Motion V3.

    FFmpeg 8.1.1 on this workstation errors in swscale when compositing some
    Envato ProRes yuv422p10le MOVs. Normalize those sources once with PyAV and
    render from a derived manifest, preserving the acquisition manifest and
    original downloads for provenance and recovery.
    """
    manifest_path = asset_root / "director-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cache = asset_root / ".motion-proxies"
    changed = False
    try:
        import av
    except ImportError as exc:
        raise RuntimeError("Motion V3 needs PyAV to normalize ProRes 10-bit Envato clips; install the YATRA media runtime") from exc

    for scene in manifest.get("scenes") or []:
        for beat in scene.get("beats") or []:
            source_value = beat.get("media")
            if not source_value:
                continue
            source = Path(str(source_value))
            if not source.is_file():
                continue
            try:
                container = av.open(str(source))
                stream = next((item for item in container.streams if item.type == "video"), None)
                codec = str(stream.codec_context.name or "").lower() if stream else ""
                pixel_format = str(getattr(stream.codec_context.format, "name", "") or "").lower() if stream else ""
                container.close()
            except Exception:
                continue
            if codec != "prores" or "10le" not in pixel_format:
                continue
            cache.mkdir(parents=True, exist_ok=True)
            fingerprint = hashlib.sha1(
                f"yatra-proxy-v3|{source.resolve()}|{source.stat().st_size}|{source.stat().st_mtime_ns}".encode("utf-8")
            ).hexdigest()[:16]
            proxy = cache / f"{source.stem}-{fingerprint}.mp4"
            if not proxy.is_file() or proxy.stat().st_size < 10000:
                rotation = 0
                try:
                    probe = subprocess.run(
                        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                         "stream_side_data=rotation", "-of", "json", str(source)],
                        capture_output=True, text=True, timeout=30, check=False,
                    )
                    side_data = json.loads(probe.stdout or "{}").get("streams", [{}])[0].get("side_data_list", [])
                    rotation = int(round(float(next((item["rotation"] for item in side_data if "rotation" in item), 0))))
                except (ValueError, KeyError, IndexError, TypeError, subprocess.SubprocessError):
                    rotation = 0
                partial = proxy.with_suffix(".partial.mp4")
                src = av.open(str(source))
                video = next(item for item in src.streams if item.type == "video")
                dst = av.open(str(partial), mode="w")
                rate = Fraction(video.average_rate or 30)
                output = dst.add_stream("libx264", rate=rate)
                width, height = int(video.width), int(video.height)
                if rotation % 180:
                    width, height = height, width
                output.width, output.height, output.pix_fmt = width, height, "yuv420p"
                output.options = {"crf": "18", "preset": "medium"}
                for index, frame in enumerate(src.decode(video)):
                    if rotation:
                        frame = av.VideoFrame.from_image(frame.to_image().rotate(rotation, expand=True))
                    frame = frame.reformat(width=width, height=height, format="yuv420p")
                    frame.pts = index
                    frame.time_base = Fraction(rate.denominator, rate.numerator)
                    for packet in output.encode(frame):
                        dst.mux(packet)
                for packet in output.encode():
                    dst.mux(packet)
                dst.close()
                src.close()
                partial.replace(proxy)
            beat["media"] = str(proxy)
            changed = True
    if not changed:
        return manifest_path
    derived = asset_root / "director-manifest.motion-v3.json"
    derived.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return derived


def _yatra_run_tool(script: Path, args: list[str], minutes: int) -> dict[str, Any]:
    """Run one of YATRA's own tools and summarise how it went.

    The coverage, de-duplication and rejection rules live in those scripts and
    are not duplicated here; this only reports what they did."""
    import subprocess

    # The tools print UTF-8 ("·", Hindi titles). Decoding with the Windows
    # default (cp1252) crashed the reader thread and lost the whole output, so a
    # failing motion_v2 render left no trace of why (2026-10-06).
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    try:
        finished = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=minutes * 60, cwd=str(script.parent), env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": f"{script.name} did not finish within {minutes} minutes"}
    tail = (finished.stdout or "").strip().splitlines()[-25:]
    if finished.returncode != 0:
        # The traceback is on stderr; without it a failure only shows progress lines.
        tail += (finished.stderr or "").strip().splitlines()[-25:]
    elif not tail:
        tail = (finished.stderr or "").strip().splitlines()[-25:]
    return {"ok": finished.returncode == 0, "detail": "\n".join(tail)}


def _yatra_acquire_footage(plan_file: Path, asset_folder: str,
                           narration_manifest: str = "") -> dict[str, Any]:
    script = _YATRA_TOOLS / "yatra-acquisition" / "acquire_scenes.py"
    # How many seconds a scene owes is decided by how long the narration
    # actually runs, not by the timecodes guessed before the voice existed --
    # the guess ran short, and footage bought against it leaves every scene
    # under-covered.
    args = [str(plan_file), asset_folder]
    if narration_manifest:
        args.append(f"--narration={narration_manifest}")
    result = _yatra_run_tool(script, args, minutes=720)
    manifest = _YATRA_ASSET_ROOT / asset_folder / "acquisition-manifest.json"
    if manifest.exists():
        scenes = json.loads(manifest.read_text(encoding="utf-8"))
        result["scenes"] = [
            {"scene": s["scene_id"], "required": s["required_seconds"],
             "required_unique_shots": s.get("required_unique_shots"),
             "acquired": s["acquired_seconds"], "covered": s["covered"],
             "clips": len(s["clips"])}
            for s in scenes
        ]
        # A partial manifest must never satisfy a complete production.
        plan = json.loads(plan_file.read_text(encoding='utf-8'))[0]
        import importlib.util
        spec = importlib.util.spec_from_file_location('yatra_acquire_validation', script)
        import sys
        if str(script.parent) not in sys.path:
            sys.path.insert(0, str(script.parent))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        expected = {str(s['id']) for s in module.parse_scenes(plan['scene_plan'])}
        result["all_covered"] = bool(expected) and expected == {str(s['scene_id']) for s in scenes} and all(s['covered'] for s in scenes)
        positive = [s for s in scenes if int(s.get("required_unique_shots") or 0) > 0]
        real_clips = [clip for s in scenes for clip in (s.get("clips") or [])]
        if not positive or not real_clips:
            result["all_covered"] = False
            result["ok"] = False
            result["detail"] = (result.get("detail", "") +
                "\nREFUSED: the plan produced zero required stock shots / zero Envato clips. "
                "A YATRA travel video cannot pass as graphics-only.").strip()
    return result


def _yatra_acquire_complete_footage(plan_file: Path, asset_folder: str,
                                     narration_manifest: str = "") -> dict[str, Any]:
    """Give a cleanly-finished partial acquisition one bounded resume.

    acquire_scenes persists accepted slots, query cursors and rejection
    streaks.  Its stuck-shot fallback is checked before the next attempt, so a
    rejection that reaches the threshold at the end of a run leaves a SHORT
    manifest even though the next resume can immediately fill only those open
    slots.  Infrastructure/tool failures remain terminal and are never retried
    here.
    """
    result = _yatra_acquire_footage(plan_file, asset_folder, narration_manifest)
    if result.get("ok") and not result.get("all_covered"):
        result = _yatra_acquire_footage(plan_file, asset_folder, narration_manifest)
    return result


def _yatra_render_opening_map(plan_file: Path, asset_folder: str) -> dict[str, Any]:
    """Turn ChatGPT's checked map brief into two reusable 1080p opening shots."""
    script = _YATRA_TOOLS / "yatra-map" / "render_opening_map.py"
    result = _yatra_run_tool(script, [str(plan_file), asset_folder], minutes=10)
    receipt = (_YATRA_ASSET_ROOT / asset_folder / "graphics" / "maps" /
               "scene-1" / "map-receipt.json")
    if result["ok"] and receipt.is_file():
        result["receipt"] = json.loads(receipt.read_text(encoding="utf-8"))
    else:
        result["ok"] = False
        result["detail"] = result.get("detail") or "Opening map receipt or clips are missing"
    return result


def _yatra_acquire_music(tool: Any, plan_record: dict[str, Any],
                         asset_folder: str) -> dict[str, Any]:
    """Acquire the one quiet Envato music bed before editing the master."""
    import urllib.parse
    process_name = "Sonia YATRA - Envato Ambient Music"
    folder = _YATRA_ASSET_ROOT / asset_folder / "music"
    # A resumed run reuses the track it already licensed (unpacked or still in
    # its archive) instead of buying another.
    _yatra_unpack_music(folder)
    existing = _yatra_pick_music_track(folder)
    if existing:
        return {"ok": True, "reused": True, "track": str(existing), "query": "", "status": "Reused"}
    query = str(plan_record.get("envato_music_query") or
                "light ambient travel documentary instrumental background music no vocals")
    started = tool.execute(
        action="start", mode="publish", process_name=process_name,
        scope="production", confirm_publish=True,
        input_args={"envatoQuery": query, "envatoQueryUrl": urllib.parse.quote_plus(query),
                    "assetFolder": asset_folder, "resultIndex": "1", "enablePaidDownload": True},
    )
    if not started.success:
        return {"ok": False, "detail": f"LAO refused YATRA ambient music acquisition: {started.content}"}
    job_id = str(((started.metadata or {}).get("job") or {}).get("id") or "")
    if not job_id:
        return {"ok": False, "detail": "LAO started ambient music acquisition without a job id"}
    terminal = {"Successful", "Failed", "Stopped", "Cancelled", "Faulted"}
    deadline = time.time() + float(os.environ.get("ONE_YATRA_MUSIC_WAIT_SECONDS", "3600"))
    status = "Pending"
    while time.time() < deadline:
        time.sleep(float(os.environ.get("ONE_LAO_POLL_SECONDS", "30")))
        probe = tool.execute(action="status", process_name=process_name,
                             scope="production", job_id=job_id)
        if not probe.success:
            continue
        status = str(((probe.metadata or {}).get("job") or {}).get("status") or status)
        if status in terminal:
            break
    _yatra_unpack_music(folder)
    track = _yatra_pick_music_track(folder)
    return {"ok": status == "Successful" and track is not None, "lao_job": job_id,
            "status": status, "query": query, "track": str(track) if track else None}


def _yatra_unpack_music(folder: Path) -> None:
    """Unpack each Envato music archive into a folder of its own name.

    Envato delivers music as one archive: the main mix and a main instrumental
    at the top, plus stems/, loops/ and shorts/ (verified 2026-10-06, 17 WAVs).
    The structure is kept so the picker can tell the main track from a drum
    stem or a 63-second short."""
    import zipfile
    for archive in (folder.glob("*.zip") if folder.exists() else []):
        target = folder / archive.stem
        if target.exists():
            continue
        partial = folder / (archive.stem + ".unpacking")
        try:
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.infolist():
                    name = Path(member.filename)
                    if (member.is_dir() or name.suffix.lower() not in {".mp3", ".wav"}
                            or name.name.startswith(".") or "__MACOSX" in name.parts or ".." in name.parts):
                        continue
                    out = partial / name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(bundle.read(member))
            partial.rename(target)  # only a complete unpack counts as present
        except zipfile.BadZipFile:
            continue


_MUSIC_PART_DIRS = {"stems", "stem", "loops", "loop", "shorts", "short", "cutdowns", "alternates"}


def _yatra_pick_music_track(folder: Path) -> Path | None:
    """The one full-length music bed in a YATRA music folder, or None.

    Prefers the main instrumental (no vocals) over the main mix, never a stem,
    loop or short; otherwise the largest remaining track."""
    if not folder.exists():
        return None
    candidates = [p for p in folder.rglob("*") if p.is_file()
                  and p.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
                  and not ({part.lower() for part in p.relative_to(folder).parts[:-1]} & _MUSIC_PART_DIRS)
                  and not re.search(r"(?:^|[_-])(stem|loop|short)[_-]?\d", p.stem, re.I)]
    if not candidates:
        return None

    def rank(p: Path) -> tuple[int, int]:
        name = p.stem.lower()
        preference = 0 if "main-instrumental" in name or "main_instrumental" in name else (
            1 if "instrumental" in name else 2 if "main" in name else 3)
        return preference, -p.stat().st_size

    return min(candidates, key=rank)


def _yatra_record_captures(payload: dict[str, Any], video_title: str) -> dict[str, Any]:
    """Film the browser demos, when a verified recipe exists for the destination.

    Recipes are per-destination on purpose: a brief asks for "the official entry
    rules", and pointing that at the wrong country's immigration site would put
    confident, wrong evidence on screen."""
    recipes_file = _YATRA_TOOLS / "yatra-capture" / "recipes.json"
    if not recipes_file.exists():
        return {"ok": True, "skipped": True, "detail": "No capture recipes are installed."}
    known = list(json.loads(recipes_file.read_text(encoding="utf-8")).keys())

    # Match the destination against the recipes that exist rather than trusting
    # a guessed country: a recipe is only usable where its source URLs were
    # verified, and filming the wrong country's immigration site would put
    # confident, wrong evidence on screen.
    # This video's own plan-derived recipe, keyed by its title, and nothing else.
    # Falling back to a destination word found in the brief is how the Qatar
    # video came to be filmed with Thailand's recordings on 2026-10-17: the
    # brief's own sentence was "no runner-ups: do not discuss singapore ...,
    # thailand (visa-free lists), china ...", and the word that matched was
    # inside the instruction NOT to cover it. A brief names other countries to
    # compare them or rule them out; none of that makes their immigration
    # pages evidence for this one. With no recipe of its own the demo scenes
    # become cards, which is the honest outcome.
    destination = video_title.lower().strip() if video_title.lower().strip() in known else ""
    if not destination:
        return {"ok": True, "skipped": True,
                "detail": f"No capture recipe matches this brief. Recipes exist for: "
                          f"{', '.join(known) or 'none'}. Add one before this video's "
                          "browser-demo scenes can be filmed."}
    script = _YATRA_TOOLS / "yatra-capture" / "record_briefs.py"
    outcome = _yatra_run_tool(script, [destination, video_title, str(payload.get('assetFolder') or '')], minutes=90)
    outcome["destination"] = destination
    return outcome


def _yatra_narrate(tool: Any, plan_record: dict[str, Any], asset_folder: str,
                   video_title: str) -> dict[str, Any]:
    """Speak the approved script in Sonia's own cloned voice.

    Narration runs in LAO rather than here because the ElevenLabs key lives in
    LAO's vault and only a robot token can resolve it -- the admin API returns
    has_secret and never the value.

    There is no fallback voice on purpose. Every other backend can produce
    speech, but a cloned voice exists only inside the account that owns it, so
    a substitute would put a stranger on Sonia's channel. If this fails the
    video waits; it does not get somebody else's voice.
    """
    full_script = str(plan_record.get("full_script") or "").strip()
    if not full_script:
        return {"ok": False, "detail": "The approved package carried no full_script to speak."}

    folder = _YATRA_ASSET_ROOT / asset_folder / "narration"
    folder.mkdir(parents=True, exist_ok=True)
    script_file = folder / "script.txt"
    manifest_file = folder / "narration.segments.json"
    # An acquisition retry must never silently spend another full voice budget.
    # Reuse only a matching script with real, non-empty segment files.
    if manifest_file.exists():
        try:
            existing = json.loads(manifest_file.read_text(encoding="utf-8"))
            segments = existing.get("segments") or []
            matching = script_file.exists() and script_file.read_text(encoding="utf-8").strip() == full_script
            valid = segments and all(
                Path(s.get("path") or "").is_file()
                and Path(s["path"]).stat().st_size > 0
                and float(s.get("seconds") or 0) > 0 for s in segments)
            if matching and valid:
                return {"ok": True, "status": "Reused", "reused": True,
                        "script_file": str(script_file), "manifest": str(manifest_file),
                        "minutes": existing.get("total_minutes"), "cues": len(segments),
                        "timeline": [{k: s.get(k) for k in ("cue", "start", "end", "seconds")}
                                     for s in segments]}
            return {"ok": False, "detail": "Existing narration does not match the script or has missing segments. Preserve it; approve a targeted voice repair instead of regenerating the full track."}
        except (ValueError, OSError, TypeError, KeyError) as exc:
            return {"ok": False, "detail": f"Existing narration checkpoint needs repair; no credits spent: {exc}"}
    # ElevenLabs takes at most 10,000 characters per request; the robot stays under it by speaking each
    # bracketed cue on its own. A long script with no cues would be refused after LAO had already started.
    if len(re.findall(r"(?m)^\[\d{1,2}:\d{2}", full_script)) < 2 and len(full_script) > 9500:
        return {"ok": False, "detail": (f"the script is {len(full_script)} characters with no [m:ss-m:ss] cue lines; "
                                        "ElevenLabs refuses more than 10,000 in one request. No credits were spent.")}

    # Reusing a completed narration above is always safe.  A new paid start is
    # not: once ElevenLabs has explicitly reported exhausted quota, hold every
    # later start until capacity has been verified and the durable block is
    # cleared.  This is an external account condition, not a source repair.
    from openjarvis.one_agents import provider_capacity
    try:
        provider_capacity.require_available("elevenlabs")
    except provider_capacity.ProviderCapacityBlocked as exc:
        return {"ok": False, "status": "Blocked", "capacity_blocked": True,
                "detail": str(exc), "script_file": str(script_file)}
    script_file.write_text(full_script, encoding="utf-8")

    # The Hinglish lexicon respells Hindi words in Devanagari; an English script has none to respell.
    lexicon = (_YATRA_TOOLS / "yatra-narration" / "pronunciation-hinglish.json"
               if sonia_language_profile(plan_record)["lexicon"] else Path(""))
    started = tool.execute(
        action="start", mode="publish", process_name=_YATRA_NARRATION_PROCESS,
        scope="production", confirm_publish=True,
        input_args={
            "scriptFile": str(script_file), "videoTitle": video_title,
            "destDir": str(folder), "filename": "narration.mp3",
            # Hinglish spelled in Latin letters does not encode vowel length,
            # so the voice reads it with English phonics and says "shayaad"
            # for shayad. The lexicon respells those words in Devanagari.
            "pronunciationFile": str(lexicon) if lexicon.is_file() else "",
        },
    )
    if not started.success:
        return {"ok": False, "detail": f"LAO refused narration: {started.content}"}
    narration_job = str(((started.metadata or {}).get("job") or {}).get("id") or "")
    if not narration_job:
        return {"ok": False, "detail": "LAO started narration without returning a job id"}

    terminal = {"Successful", "Failed", "Stopped", "Cancelled", "Faulted"}
    deadline = time.time() + float(os.environ.get("ONE_YATRA_NARRATION_WAIT_SECONDS", "3600"))
    status = "Pending"
    last_job: dict[str, Any] = {}
    while time.time() < deadline:
        time.sleep(float(os.environ.get("ONE_LAO_POLL_SECONDS", "30")))
        probe = tool.execute(action="status", process_name=_YATRA_NARRATION_PROCESS,
                             scope="production", job_id=narration_job)
        if not probe.success:
            continue
        last_job = (probe.metadata or {}).get("job") or {}
        status = str(last_job.get("status") or status)
        if status in terminal:
            break
    result = {"ok": status == "Successful", "lao_job": narration_job, "status": status,
              "script_file": str(script_file)}
    if status != "Successful":
        provider_error = str(last_job.get("error_message") or "no error message")
        # Carry LAO's own reason; "requires repair: None" told nobody that ElevenLabs had refused the text.
        result["detail"] = (f"LAO narration {narration_job} ended {status}: "
                            f"{provider_error[:400]}")
        compact_error = "".join(provider_error.casefold().split())
        if ('"code":"quota_exceeded"' in compact_error
                or "exceedsyourquota" in compact_error):
            provider_capacity.record_block(
                "elevenlabs",
                reason="ElevenLabs reported quota_exceeded while generating approved narration",
                evidence_kind="provider_response",
                source_job=narration_job,
            )
            result["capacity_blocked"] = True

    manifest = folder / "narration.segments.json"
    if manifest.exists():
        result["manifest"] = str(manifest)
        record = json.loads(manifest.read_text(encoding="utf-8"))
        # The cue times in the script were an estimate written before the voice
        # existed. The measured timeline is what the edit is cut against, and
        # it is what says how many seconds of footage each scene owes.
        result["minutes"] = record.get("total_minutes")
        result["cues"] = len(record.get("segments") or [])
        result["timeline"] = [
            {"cue": s.get("cue"), "start": s.get("start"),
             "end": s.get("end"), "seconds": s.get("seconds")}
            for s in record.get("segments") or []
        ]
    return result


def _yatra_render_director(asset_root: Path, run=None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Draw scenes with a reversible Motion V3 -> V2 -> Remotion chain."""
    run = run or _yatra_run_tool
    legacy = _YATRA_EDIT_TOOLS / "render_director.py"
    v2 = _YATRA_EDIT_TOOLS / "motion_v2" / "render_director_v2.py"
    v3 = _YATRA_EDIT_TOOLS / "motion_v3" / "render_director_v3.py"
    engine = os.environ.get("ONE_YATRA_ENGINE", "motion_v3")
    if engine == "remotion":
        outcome = run(legacy, [str(asset_root)], minutes=180)
        outcome["engine"] = "remotion"
        return outcome, None
    v3_failure = None
    if engine == "motion_v3" and v3.is_file():
        history = _YATRA_EDIT_TOOLS / "motion_v3" / "direction-history"
        try:
            render_manifest = _yatra_motion_manifest(asset_root)
        except Exception as exc:
            return {"ok": False, "detail": f"Motion V3 media normalization failed: {exc}", "engine": "motion_v3"}, None
        outcome = run(v3, [str(asset_root), "--manifest", str(render_manifest), "--history", str(history)], minutes=240)
        outcome["engine"] = "motion_v3"
        if outcome["ok"]:
            return outcome, None
        v3_failure = outcome
        for stamp in (asset_root / "efficient-pilot" / "director").glob("scene-*.v3.json"):
            stamp.with_suffix("").with_suffix(".mp4").unlink(missing_ok=True)
            stamp.unlink(missing_ok=True)
    if not v2.is_file():
        outcome = run(legacy, [str(asset_root)], minutes=180)
        outcome["engine"] = "remotion (fallback; motion_v2 unavailable)"
        return outcome, v3_failure
    outcome = run(v2, [str(asset_root)], minutes=240)
    outcome["engine"] = "motion_v2"
    if outcome["ok"]:
        return outcome, v3_failure
    for stamp in (asset_root / "efficient-pilot" / "director").glob("scene-*.v2.json"):
        stamp.with_suffix("").with_suffix(".mp4").unlink(missing_ok=True)
        stamp.unlink(missing_ok=True)
    fallback = run(legacy, [str(asset_root)], minutes=180)
    fallback["engine"] = "remotion (fallback after motion_v2 failed)"
    return fallback, v3_failure or outcome


def _yatra_cut_video(plan_file: Path, asset_folder: str, run=None) -> dict[str, Any]:
    """Draw the cards, cut the picture to the voice, then check the result.

    Half a YATRA video has no footage behind it -- the plan marks those scenes
    `graphic/map`, or `original_optional` for shots that would need a camera
    nobody is holding. Those are drawn from the plan's own words. Everything is
    then laid out in plan order under one narration track and checked, because
    the failures worth catching here are silent ones: picture drifting off the
    voice, a card that renders as a black screen, a mix too quiet to hear.
    """
    asset_root = _YATRA_ASSET_ROOT / asset_folder
    runner = run or _yatra_run_tool
    efficient = asset_root / "efficient-pilot"
    # route_visuals, compile_director and render_director_v2 read the plan from
    # <video folder>/production-plan.json. Nothing put it there, so every video
    # after Thailand (whose copy was placed by hand) failed its first cut step.
    # The copy is byte-identical, so _travel_checkpoint's "reviewed plan" check
    # (same narration) still holds; an existing reviewed plan is never replaced.
    local_plan = asset_root / "production-plan.json"
    if not local_plan.exists() and Path(plan_file).is_file():
        asset_root.mkdir(parents=True, exist_ok=True)
        local_plan.write_bytes(Path(plan_file).read_bytes())
    steps = [
        ("routes", _YATRA_EDIT_TOOLS / "route_visuals.py", [str(asset_root)], 10),
        ("render", _YATRA_EDIT_TOOLS / "render_graphics.py",
         [str(efficient / "graphic-specs.json"), str(efficient / "graphics")], 10),
        # A readable card is not automatically an engaging moving picture.
        # Expand every information-heavy scene into a sequence of distinct
        # local motion beats before assembly; this costs no render credits and
        # prevents long, near-black holds in the middle of the video.
        ("kinetic", _YATRA_EDIT_TOOLS / "render_kinetic.py", [str(asset_root)], 30),
        # Compile verified receipts into an exact edit decision list, then
        # render typography, maps, icons, masks, parallax, particles, stock
        # micro-shots and official proof as one narration-timed scene file.
        # One point per ~6 s of narration, so cards in a scene say different things instead of repeating one
        # title. Optional: without it (no hosted model) the composer shows the scene title once, then footage.
        ("scene_points", _YATRA_EDIT_TOOLS / "scene_points.py", [str(asset_root)], 40),
        ("director_manifest", _YATRA_EDIT_TOOLS / "compile_director.py", [str(asset_root)], 10),
        ("director_render", None, [str(asset_root)], 0),  # drawn by _yatra_render_director below
        ("assemble", _YATRA_EDIT_TOOLS / "assemble.py", [str(plan_file), asset_folder], 90),
        ("qc", _YATRA_EDIT_TOOLS / "qc.py", [asset_folder], 30),
    ]
    result: dict[str, Any] = {"ok": True}
    for name, script, args, minutes in steps:
        if name == "director_render":
            outcome, earlier = _yatra_render_director(asset_root, run=runner)
            if earlier:
                result[f"director_render_{earlier.get('engine', 'fallback')}"] = earlier
        else:
            outcome = runner(script, args, minutes=minutes)
        result[name] = outcome
        if name == "routes" and outcome.get("ok"):
            integrity = _yatra_validate_capture_integrity(asset_root)
            result["capture_integrity"] = integrity
            if not integrity.get("ok"):
                result.update({"ok": False, "failed_at": "capture_integrity"})
                return result
        if name == "scene_points" and not outcome["ok"]:
            continue  # optional step: the composer falls back to title-then-footage
        if not outcome["ok"]:
            # QC failing is not a tool crash; it is the answer. Either way the
            # cut is not fit to upload, so the run stops before the gate.
            result["ok"] = False
            result["failed_at"] = name
            return result
    report = _YATRA_ASSET_ROOT / asset_folder / "edit" / "qc-report.json"
    if report.exists():
        result["qc_report"] = json.loads(report.read_text(encoding="utf-8"))
    result["master"] = str(_YATRA_ASSET_ROOT / asset_folder / "edit" / "master.mp4")
    return result


def _yatra_validate_capture_integrity(asset_root: Path) -> dict[str, Any]:
    """Fail a cut if any routed OBS source is missing, non-HD, or mostly black.

    Checking only the final composite misses a broken source range when motion
    cards or overlays cover it. The raw source must pass before we assemble it.
    """
    routes_path = asset_root / "visual-routes.json"
    if not routes_path.is_file():
        return {"ok": False, "detail": "visual-routes.json is missing; OBS sources cannot be audited"}
    try:
        routes = json.loads(routes_path.read_text(encoding="utf-8")).get("scenes") or {}
    except (OSError, ValueError) as exc:
        return {"ok": False, "detail": f"visual-routes.json is unreadable: {exc}"}
    capture_dir = asset_root / "captures"
    routed_ids = {str(row.get("capture_id") or "") for row in routes.values()
                  if row.get("route") == "obs" and row.get("capture_id")}
    active_ids = {re.sub(r"-capture$", "", path.stem)
                  for path in capture_dir.glob("*-capture.*")
                  if path.is_file() and path.suffix.lower() in {".mkv", ".mp4", ".mov"}}
    planned_ids: set[str] = set()
    plan_path = asset_root / "obs-capture-plan.json"
    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            planned_ids = {str(row.get("captureId") or row.get("capture_id") or "")
                           for row in (plan.get("recipes") or [])
                           if row.get("captureId") or row.get("capture_id")}
        except (OSError, ValueError) as exc:
            return {"ok": False, "detail": f"obs-capture-plan.json is unreadable: {exc}"}
    # Validate preserved captures too, not only the ones selected by the
    # current director route. A later scene-plan/routing change must not make
    # an already-recorded maintenance page silently eligible for reuse.
    capture_ids = sorted(routed_ids | active_ids | planned_ids)
    issues: list[str] = []
    semantic_receipts: list[dict[str, Any]] = []
    for capture_id in capture_ids:
        candidates = [path for path in capture_dir.glob(f"{capture_id}-capture.*")
                      if path.suffix.lower() in {".mkv", ".mp4", ".mov"} and path.is_file()]
        if len(candidates) != 1:
            issues.append(f"{capture_id}: expected one active recording, found {len(candidates)}")
            continue
        path = candidates[0]
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=width,height:format=duration", "-of", "json", str(path)],
                capture_output=True, text=True, timeout=60,
            )
            if probe.returncode:
                issues.append(f"{capture_id}: ffprobe failed: {probe.stderr[-300:]}")
                continue
            media = json.loads(probe.stdout)
            streams = media.get("streams") or []
            video = next((stream for stream in streams if "width" in stream and "height" in stream), {})
            duration = float((media.get("format") or {}).get("duration") or 0)
            if (int(video.get("width") or 0), int(video.get("height") or 0)) != (1920, 1080) or duration < 8:
                issues.append(f"{capture_id}: invalid format/duration ({video.get('width')}x{video.get('height')}, {duration:.1f}s)")
                continue
            scan = subprocess.run(
                ["ffmpeg", "-hide_banner", "-i", str(path), "-vf",
                 "blackdetect=d=2:pix_th=0.10:pic_th=0.98", "-an", "-f", "null", "NUL"],
                capture_output=True, text=True, timeout=180,
            )
            if scan.returncode:
                issues.append(f"{capture_id}: black-frame scan failed: {scan.stderr[-300:]}")
                continue
            spans = [float(value) for value in re.findall(r"black_duration:([0-9.]+)", scan.stderr)]
            if any(seconds >= 2.0 for seconds in spans):
                issues.append(f"{capture_id}: {max(spans):.2f}s full-frame black interval")
                continue
            semantic = _yatra_capture_semantic_state(path)
            semantic_receipts.append({
                "capture_id": capture_id,
                "media_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "media_size": path.stat().st_size,
                **semantic,
            })
            if not semantic.get("ok"):
                issues.append(f"{capture_id}: {semantic.get('detail')}")
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            issues.append(f"{capture_id}: capture validation error: {exc}")
    result = {"ok": not issues, "captures": len(capture_ids),
              "semantic_receipts": semantic_receipts,
              "detail": (f"all {len(capture_ids)} active OBS capture(s) passed integrity and semantic checks"
                         if not issues else "; ".join(issues))}
    receipt = capture_dir / "capture-semantic-qc.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({
        "schema": "yatra-capture-semantic-qc/1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    result["receipt"] = str(receipt)
    return result


_YATRA_INVALID_PAGE_TEXT = (
    "website under maintenance", "under maintenance", "service unavailable",
    "temporarily unavailable", "access denied", "bad gateway",
    "internal server error", "404 not found", "403 forbidden",
)


def _yatra_capture_semantic_state(path: Path) -> dict[str, Any]:
    """Read the pixels OBS recorded and reject visible terminal/error pages."""
    from openjarvis.tools import kdp_cover_qc

    with tempfile.TemporaryDirectory(prefix="yatra-capture-semantic-") as temporary:
        pattern = str(Path(temporary) / "frame-%02d.png")
        extract = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
             "-vf", "fps=1/7,scale=1280:-2", "-frames:v", "4", "-y", pattern],
            capture_output=True, text=True, timeout=180,
        )
        if extract.returncode:
            return {"ok": False, "detail": f"semantic frame extraction failed: {extract.stderr[-300:]}"}
        frames = sorted(Path(temporary).glob("frame-*.png"))
        if not frames:
            return {"ok": False, "detail": "semantic check produced no capture frames"}
        texts = [kdp_cover_qc.read_text(frame) for frame in frames]
    normalized = " ".join(" ".join(texts).split()).casefold()
    blocked = next((phrase for phrase in _YATRA_INVALID_PAGE_TEXT if phrase in normalized), "")
    if blocked:
        return {"ok": False, "samples": len(texts),
                "detail": f"invalid webpage state visible in recording: {blocked!r}"}
    if not re.search(r"[a-z]{3}", normalized):
        return {"ok": False, "samples": len(texts),
                "detail": "OCR found no meaningful webpage text in sampled frames"}
    return {"ok": True, "samples": len(texts),
            "text_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "detail": "sampled pixels contain readable page text and no maintenance/error state"}


def _yatra_upload(tool: Any, asset_folder: str, video_title: str,
                  description: str, cut: dict[str, Any]) -> dict[str, Any]:
    """Put the finished cut on the channel as a private draft.

    Only ever private. Nothing in this pipeline is in a position to decide that
    a video is ready for an audience -- a person decides that in Studio, after
    watching it. The workflow also refuses to upload unless the signed-in
    channel is Sonia's, because an upload cannot be moved afterwards.
    """
    if not cut.get("ok"):
        return {"ok": False, "skipped": True,
                "detail": f"QC did not pass ({cut.get('failed_at')}), so nothing was uploaded."}
    master = Path(str(cut.get("master") or ""))
    if not master.exists():
        return {"ok": False, "skipped": True, "detail": "No master cut to upload."}

    started = tool.execute(
        action="start", mode="publish", process_name=_YATRA_UPLOAD_PROCESS,
        scope="production", confirm_publish=True,
        input_args={"masterFile": str(master), "videoTitle": video_title,
                    "videoDescription": description, "expectedChannel": _SONIA_CHANNEL},
    )
    if not started.success:
        return {"ok": False, "detail": f"LAO refused the upload: {started.content}"}
    upload_job = str(((started.metadata or {}).get("job") or {}).get("id") or "")
    terminal = {"Successful", "Failed", "Stopped", "Cancelled", "Faulted"}
    deadline = time.time() + float(os.environ.get("ONE_YATRA_UPLOAD_WAIT_SECONDS", "5400"))
    status = "Pending"
    while time.time() < deadline:
        time.sleep(float(os.environ.get("ONE_LAO_POLL_SECONDS", "30")))
        probe = tool.execute(action="status", process_name=_YATRA_UPLOAD_PROCESS,
                             scope="production", job_id=upload_job)
        if not probe.success:
            continue
        status = str(((probe.metadata or {}).get("job") or {}).get("status") or status)
        if status in terminal:
            break
    return {"ok": status == "Successful", "lao_job": upload_job, "status": status,
            "visibility": "private draft", "channel": _SONIA_CHANNEL}


def _narration_bound_reviewed_plan(
    source_record: dict[str, Any], repair_file: Path, reviewed_path: Path, narration_dir: Path,
) -> dict[str, Any] | None:
    """Return an already-approved plan only when paid narration proves its identity.

    A later recovery may normalize or repair the immutable LAO artifact after a
    targeted editorial sidecar has already produced ``production-plan.json``.
    Reapplying the sidecar then fails its original byte hash even though the
    approved plan and paid narration remain intact.  Never update the sidecar
    hash to force a pass: accept the saved plan only when its repair receipt,
    title, 20-segment manifest, and exact stripped script all agree.
    """
    manifest_path = narration_dir / "narration.segments.json"
    script_path = narration_dir / "script.txt"
    if not (reviewed_path.is_file() and manifest_path.is_file() and script_path.is_file()):
        return None
    try:
        repair = json.loads(repair_file.read_text(encoding="utf-8"))
        existing = json.loads(reviewed_path.read_text(encoding="utf-8"))[0]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None
    approval = existing.get("editorial_repair") or {}
    base_sha = str(repair.get("base_sha256") or "").lower()
    if (not base_sha
            or str(repair.get("status") or "") != "approved_for_voice"
            or str(approval.get("status") or "") != "approved_for_voice"
            or str(approval.get("source_sha256") or "").lower() != base_sha
            or existing.get("video_title") != source_record.get("video_title")):
        return None
    script = str(existing.get("full_script") or "").strip()
    script_sha = hashlib.sha256(script.encode("utf-8")).hexdigest()
    segments = manifest.get("segments") or []
    if (str(manifest.get("script_sha256") or "").lower() != script_sha
            or len(segments) != _YATRA_EXPECTED_SCENES
            or script_path.read_text(encoding="utf-8").strip() != script):
        return None
    _validate_yatra_contract(existing, _YATRA_EXPECTED_SCENES)
    return existing


def _travel_checkpoint(payload: dict[str, Any]) -> tuple[Path, dict[str, Any], str, str]:
    """Only resume a known LAO checkpoint, never an arbitrary external file."""
    if payload.get("brand") != "sonia_travel_vlogs":
        raise RuntimeError("Travel production handoff requires sonia_travel_vlogs")
    checkpoint = str(payload.get("preproduction_job") or "")
    if not re.fullmatch(r"[a-f0-9-]{36}", checkpoint):
        raise RuntimeError("Missing valid preproduction checkpoint id")
    source = _yatra_preproduction_file(checkpoint)
    record = json.loads(source.read_text(encoding="utf-8"))[0]
    folder = f"{_yatra_slug(record.get('video_title') or '')}-{checkpoint[:8]}"
    asset_root = _YATRA_ASSET_ROOT / folder
    repair_file = asset_root / "targeted-repair.json"
    if repair_file.is_file():
        from openjarvis.one_agents.yatra_repair import apply_targeted_repair
        reviewed_path = asset_root / "production-plan.json"
        existing = json.loads(reviewed_path.read_text(encoding="utf-8"))[0] if reviewed_path.is_file() else None
        narration_dir = asset_root / "narration"
        try:
            repaired = apply_targeted_repair(source, repair_file)
        except RuntimeError as exc:
            if str(exc) != "Editorial repair does not match its frozen LAO checkpoint":
                raise
            repaired = _narration_bound_reviewed_plan(
                record, repair_file, reviewed_path, narration_dir,
            )
            if repaired is None:
                raise
        if repaired["editorial_repair"]["status"] != "approved_for_voice":
            raise RuntimeError("Targeted YATRA repair is structurally ready but not approved for Sonia voice credits")
        _validate_yatra_contract(repaired, _YATRA_EXPECTED_SCENES)
        if (narration_dir / "narration.segments.json").exists() and (
                existing is None or existing.get("full_script") != repaired.get("full_script")):
            raise RuntimeError("Cannot revise a YATRA script after narration exists")
        if existing is not None and existing not in (record, repaired):
            before, after = dict(existing), dict(repaired)
            before.pop("opening_map_spec", None)
            after.pop("opening_map_spec", None)
            before.pop("browser_capture_plan", None)
            after.pop("browser_capture_plan", None)
            if before != after:
                raise RuntimeError("Existing reviewed YATRA plan differs beyond approved visual repairs")
        if existing != repaired:
            reviewed_path.write_text(json.dumps([repaired], ensure_ascii=False, indent=2), encoding="utf-8")
        return reviewed_path, repaired, folder, checkpoint
    # A locally reviewed plan may augment stock slots without altering voice.
    reviewed = _YATRA_ASSET_ROOT / folder / "production-plan.json"
    if reviewed.is_file():
        revised = json.loads(reviewed.read_text(encoding="utf-8"))[0]
        if revised.get("full_script") != record.get("full_script"):
            raise RuntimeError("Reviewed visual plan changed narration; explicit voice revision required")
        source, record = reviewed, revised
    return source, record, folder, checkpoint


def _run_fabula(job: dict[str, Any]) -> dict[str, Any]:
    """Own narration separately; deliver a durable visual-stage handoff."""
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool
    payload = _json_task(job)
    if payload.get("brand") == "sonia_travel_vlogs" and not payload.get("preproduction_job"):
        return _run_yatra_prepare(job, owner="fabula")
    if payload.get("stage") != "narration":
        raise RuntimeError("FABULA runtime accepts approved travel narration handoffs only")
    _, record, folder, checkpoint = _travel_checkpoint(payload)
    stages.worker_confirms_receipt("fabula", "Received approved narration checkpoint")
    try:
        stages.set_stage("fabula", stages.EXECUTING, "Validating or producing approved narration and measured scene timings")
        narration = _yatra_narrate(LaoOrchestratorTool(), record, folder, record["video_title"])
        if not narration.get("ok"):
            if narration.get("capacity_blocked"):
                return {"agent": "FABULA", "stage": "narration", "_blocked": True,
                        "status": "provider_capacity_blocked",
                        "blocked_reason": narration.get("detail"),
                        "narration": narration, "production_complete": False}
            raise RuntimeError(f"FABULA narration requires repair: {narration.get('detail')}")
        receipt = _YATRA_ASSET_ROOT / folder / "narration" / "fabula-receipt.json"
        receipt.write_text(json.dumps({"agent": "FABULA", "job": job["id"],
                                      "checkpoint": checkpoint, "narration": narration}, indent=2), encoding="utf-8")
        _require_active_job(job, "hand narration to YATRA")
        follow = stages.head_briefs_worker(
            "fabula", "yatra", carrying_detail="Taking approved voice and measured scene timings to YATRA",
            briefing_detail="YATRA, use these voice timings for Envato, OBS and the edit. Do not regenerate narration.",
            awaiting_detail="Narration delivered; waiting for YATRA's video QC",
            enqueue=lambda: enqueue_job("yatra", json.dumps({**payload, "stage": "visuals",
                             "narration_job": job["id"], "narration_receipt": str(receipt)}),
                             mode="execute", dedupe_key=f"travel:{checkpoint}:visuals"))
        return {"agent": "FABULA", "stage": "narration", "narration": narration,
                "handed_to": {"agent": "YATRA", "job_id": follow["id"]}, "production_complete": False}
    finally:
        stages.clear_stage("fabula")


def _run_planexium(job: dict[str, Any]) -> dict[str, Any]:
    from openjarvis.one_agents.planexium import run_job, enqueue_deferred_commission
    stages.set_stage("planexium", stages.EXECUTING, "Producing The Planexium local science review bundle")
    try:
        result = run_job(job)
        if result.get("production_complete") and not result.get("uploaded"):
            report = enqueue_job("lyra", json.dumps({"brand": "planexium", "stage": "package", "mission_id": result["mission_id"]}),
                                 mode="execute", dedupe_key=f"planexium:{result['mission_id']}:packaging")
            result["handed_to"] = {"agent": "LYRA", "job_id": report["id"]}
            deferred = enqueue_deferred_commission(result, enqueue=enqueue_job)
            if deferred:result["next_daily_job"] = deferred["id"]
        return result
    finally:
        stages.clear_stage("planexium")


def _run_yatra(job: dict[str, Any]) -> dict[str, Any]:
    payload = _json_task(job)
    if payload.get("stage") == "visuals":
        return _run_yatra_visuals(job)
    if payload.get("preproduction_job"):
        _, _, _, checkpoint = _travel_checkpoint(payload)
        follow = enqueue_job("fabula", json.dumps({**payload, "stage": "narration"}),
                             mode="execute", dedupe_key=f"travel:{checkpoint}:narration")
        return {"agent": "YATRA", "production_complete": False,
                "handed_to": {"agent": "FABULA", "job_id": follow["id"]}}
    # A new video starts by freeing what earlier, finished videos left behind: their Envato clips age out of
    # retention days after upload, and nothing else revisits those folders once their own run has ended.
    stages.set_stage("yatra", stages.EXECUTING, "Clearing storage left by earlier finished videos")
    from openjarvis.one_agents import youtube_publish
    storage = youtube_publish.sweep_finished_videos()
    follow = stages.head_briefs_worker(
        "yatra", "fabula", carrying_detail="Taking narration work to FABULA",
        briefing_detail="FABULA, prepare the approved script and voice; return measured timings for the visual edit.",
        awaiting_detail="Waiting for FABULA narration",
        enqueue=lambda: enqueue_job("fabula", json.dumps(payload), mode="execute",
                                    dedupe_key=f"travel:{job['id']}:prepare"))
    return {"agent": "YATRA", "production_complete": False, "storage_cleanup": storage,
            "handed_to": {"agent": "FABULA", "job_id": follow["id"]}}


def _yatra_preproduction_timing() -> tuple[float, float, float]:
    """Shared finite provider budget, poll interval and HTTP timeout for preparation.

    Preserve valid configured values; malformed/non-finite values use defaults.
    Bounds keep this operation finite even with an accidental excessive setting.
    They do not alter other LAO operations or any production completion gates.
    """
    def bounded(name: str, default: float, lower: float, upper: float) -> float:
        try:
            value = float(os.environ.get(name, str(default)))
        except ValueError:
            value = default
        if not math.isfinite(value) or value < lower:
            value = default
        return min(value, upper)

    return (
        bounded("ONE_YATRA_MAX_WAIT_SECONDS", 5400.0, 1.0, 86400.0),
        bounded("ONE_LAO_POLL_SECONDS", 30.0, 0.0, 300.0),
        bounded("LAO_TOOL_TIMEOUT_SECONDS", 30.0, 1.0, 300.0),
    )


def _run_yatra_prepare(job: dict[str, Any], owner: str = "fabula") -> dict[str, Any]:
    """Run Sonia Travel Vlogs preproduction in LAO and return its receipt to HELIOS."""
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool
    payload = _json_task(job)
    provider_wait, poll_seconds, tool_timeout = _yatra_preproduction_timing()
    if str(payload.get("brand") or "") != "sonia_travel_vlogs":
        raise RuntimeError("YATRA refuses work outside sonia_travel_vlogs")
    trend_brief = str(payload.get("trendBrief") or payload.get("angle") or "").strip()
    if not trend_brief or trend_brief == str(job.get("task") or "").strip():
        raise RuntimeError("YATRA requires HELIOS's non-empty Sanjeevani-grounded TrendBrief")

    # LAO's Windows worker currently routes prompt text through a legacy
    # code-page boundary. Keep the canonical, Unicode research brief in ONE's
    # artifact/memory record, but hand LAO a portable prompt representation so
    # a malformed publisher byte or typographic glyph cannot abort production
    # before the browser even opens.
    lao_trend_brief = unicodedata.normalize("NFKD", trend_brief).encode(
        "ascii", "ignore"
    ).decode("ascii")
    lao_trend_brief = re.sub(r"[^\x09\x0A\x0D\x20-\x7E]", "", lao_trend_brief).strip()
    if not lao_trend_brief:
        raise RuntimeError("YATRA TrendBrief contains no LAO-safe prompt text")

    stages.worker_confirms_receipt(owner, "Received HELIOS's travel TrendBrief")
    # ChatGPT runs in the robots' Chrome, which the robots never launch themselves; bring it up if it is down
    # (both were closed on 2026-10-08). Best effort: if it cannot start, LAO's own step says why.
    stages.set_stage(owner, stages.EXECUTING, "Checking the robot Chrome windows are open")
    _yatra_run_tool(_YATRA_TOOLS / "yatra-acquisition" / "robot_chrome.py", [], minutes=2)
    tool = LaoOrchestratorTool()
    process_name = "Sonia YATRA - Preproduction"
    resume_id = job_recovery.resume_target(job)
    if resume_id:
        lao_job_id = resume_id
    else:
        language = sonia_language_profile(payload)
        started = tool.execute(
            action="start", mode="publish", process_name=process_name, timeout=tool_timeout,
            scope="production", confirm_publish=True,
            input_args={
                "trendBrief": lao_trend_brief,
                "channelName": "Sonia Travel Vlogs",
                "channelHandle": "@sonicsonia",
                "targetLanguage": language["targetLanguage"],
                "expectedSceneCount": _YATRA_EXPECTED_SCENES,
                # Empty keeps the package's Devanagari rule (Hinglish); English replaces it outright, since the
                # two rules contradict each other.
                **({"scriptRule": language["scriptRule"]} if language["scriptRule"] else {}),
                "enablePaidDownload": True,
            },
        )
        if not started.success:
            raise RuntimeError(f"LAO refused YATRA production: {started.content}")
        lao_job_id = str(((started.metadata or {}).get("job") or {}).get("id") or "")
        if not lao_job_id:
            raise RuntimeError("LAO started YATRA without returning a job id")
        job_recovery.attach(_connect, job["id"], lao_job_id)

    terminal = {"Successful", "Failed", "Stopped", "Cancelled", "Faulted"}
    deadline = time.time() + provider_wait
    status = "Pending"
    last: dict[str, Any] = {}
    while time.time() < deadline:
        stages.set_stage(owner, stages.EXECUTING,
                         f"Building Sonia Travel Vlogs package · LAO {status}",
                         lao_job=lao_job_id, lao_process=process_name)
        time.sleep(poll_seconds)
        job_recovery.heartbeat(_connect, job["id"])
        probe = tool.execute(action="status", process_name=process_name,
                             scope="production", job_id=lao_job_id, include_logs=True, timeout=tool_timeout)
        if not probe.success:
            continue
        last = probe.metadata or {}
        status = str((last.get("job") or {}).get("status") or status)
        if status in terminal:
            break
    if status != "Successful":
        stages.clear_stage(owner); stages.clear_stage("helios")
        # LAO carries the actionable failure detail in the terminal job and
        # its logs. Preserve it in ONE's job error so a missing checkpoint is
        # not the only clue left after a failed preproduction run.
        job_detail = last.get("job") or {}
        detail = " | ".join(
            str(value).strip() for value in (
                job_detail.get("error"), job_detail.get("message"),
                last.get("error"),
            ) if str(value or "").strip()
        )
        logs = last.get("logs")
        if not detail and logs:
            detail = str(logs).strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"YATRA workflow ended as {status}{suffix}")

    # A script with no footage is not a deliverable, so the same run goes on to
    # fetch the stock every scene needs and to film the official-source demos.
    plan_file = _yatra_preproduction_file(lao_job_id)
    plan_records = json.loads(plan_file.read_text(encoding="utf-8")) or [{}]
    plan_record = plan_records[0]
    # Stamp the video's language on the plan itself: every later stage (voice, SEO, subtitles) reads this file or a
    # copy of it, so the language travels with the video rather than with whichever job payload happens to carry it.
    # The cue lines are normalised here too, before any copy of the plan exists.
    normalized = normalize_script_cues(plan_record.get("full_script") or "")
    normalized_map = _normalize_yatra_json_block(plan_record.get("opening_map_spec"))
    if (plan_record.get("language") != sonia_language_profile(payload)["key"]
            or normalized != (plan_record.get("full_script") or "")
            or normalized_map != plan_record.get("opening_map_spec")):
        plan_record["language"] = sonia_language_profile(payload)["key"]
        plan_record["full_script"] = normalized
        plan_record["opening_map_spec"] = normalized_map
        plan_file.write_text(json.dumps(plan_records, ensure_ascii=False, indent=2), encoding="utf-8")
    contract = _validate_yatra_contract(plan_record, _YATRA_EXPECTED_SCENES)
    video_title = str(plan_record.get("video_title") or "").strip()
    # Keep each LAO production checkpoint in a clean, retry-stable folder.
    # A title-only path made a fresh revision silently inherit stale 4K or
    # duplicate downloads from the prior cut; the LAO job id scopes retries to
    # the same folder while giving a genuinely new run its own assets.
    asset_folder = f"{_yatra_slug(video_title or trend_brief)}-{lao_job_id[:8]}"
    if _yatra_editorial_hold(plan_record):
        stages.clear_stage(owner)
        return {"agent": owner.upper(), "stage": "editorial_hold", "production_complete": False,
                "lao_job": lao_job_id, "asset_folder": asset_folder, "contract": contract,
                "reason": "Saved ChatGPT draft has final_verdict: REWRITE; repair this checkpoint before Sonia voice credits"}
    _require_active_job(job, "commission FABULA narration")
    follow = enqueue_job("fabula", json.dumps({**payload, "stage": "narration",
                         "preproduction_job": lao_job_id}), mode="execute",
                         dedupe_key=f"travel:{lao_job_id}:narration")
    stages.clear_stage(owner)
    return {"agent": owner.upper(), "stage": "preproduction", "production_complete": False,
            "lao_job": lao_job_id, "asset_folder": asset_folder,
            "contract": contract,
            "handed_to": {"agent": "FABULA", "job_id": follow["id"]}}


def _run_yatra_visuals(job: dict[str, Any]) -> dict[str, Any]:
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool
    payload = _json_task(job)
    plan_file, plan_record, asset_folder, lao_job_id = _travel_checkpoint(payload)
    video_title = str(plan_record["video_title"])
    tool = LaoOrchestratorTool()
    receipt = _YATRA_ASSET_ROOT / asset_folder / "narration" / "fabula-receipt.json"
    if not receipt.is_file():
        raise RuntimeError("YATRA needs FABULA's narration receipt before acquiring timed visuals")
    envelope = json.loads(receipt.read_text(encoding="utf-8"))
    if envelope.get("checkpoint") != lao_job_id:
        raise RuntimeError("FABULA narration receipt belongs to a different production")
    narration = envelope["narration"]
    last = {"checkpoint": lao_job_id}
    stages.set_stage("yatra", stages.EXECUTING,
                     "Rendering the opening geography map from YATRA's visual brief")
    opening_map = _yatra_render_opening_map(plan_file, asset_folder)
    if not opening_map.get("ok"):
        raise RuntimeError(f"YATRA opening map failed before acquisition: {opening_map}")
    # Narration comes first because it is what decides how much footage to buy.
    # The scene plan's timecodes are a guess at pace made before the voice
    # existed, and Sonia's clone reads slower than the guess, so buying against
    # the guess leaves every scene short.
    if not narration.get("ok"):
        raise RuntimeError(f"YATRA narration checkpoint is not ready: {narration.get('detail')}")
    stages.set_stage("yatra", stages.EXECUTING,
                     "Acquiring stock footage for every approved scene")
    asset_root = _YATRA_ASSET_ROOT / asset_folder
    # Route the scenes before buying for them. acquire_scenes sizes each scene's
    # purchase from visual-routes.json (a stock scene is ~75% footage in the
    # composer), and without it guesses from the plan's footage beats; the
    # routes used to be written only during the cut, after acquisition, so a
    # first run bought 35 clips where the cut needed 47 (Vietnam, 2026-10-06).
    local_plan = asset_root / "production-plan.json"
    if not local_plan.exists() and Path(plan_file).is_file():
        asset_root.mkdir(parents=True, exist_ok=True)
        local_plan.write_bytes(Path(plan_file).read_bytes())
    # Official-page recordings come from this video's own plan. Until 2026-10-08 they needed a hand-written recipe
    # per destination, so every video outside Malaysia, Thailand and Timor-Leste filmed nothing. plan_captures
    # keeps only government sites and the brand's own domain, films them read-only, and maps them to the scenes
    # with obs beats. A failure here costs the recordings, never the video.
    stages.set_stage("yatra", stages.EXECUTING, "Choosing the official pages to film for this video")
    obs_plan = _yatra_run_tool(_YATRA_TOOLS / "yatra-capture" / "plan_captures.py", [str(asset_root)], minutes=5)
    routes = _yatra_run_tool(_YATRA_EDIT_TOOLS / "route_visuals.py", [str(asset_root)], minutes=10)
    if not routes.get("ok"):
        raise RuntimeError(f"YATRA could not route the scenes before acquisition: {routes.get('detail')}")
    # The acquisition manifest owns scene coverage. A raw global file-count
    # shortcut used to declare the footage complete at 36 files even when
    # durable scene slots were still empty (H-1B, 2026-10-18: 38/46 files but
    # seven scenes incomplete), allowing OBS/editing to start prematurely.
    # acquire_scenes is resumable and hashes every accepted file, so calling it
    # on every visual resume preserves accepted downloads and fills only the
    # missing slots. Its all_covered result is the only footage completion gate.
    from openjarvis.one_agents import resource_lanes
    stages.set_stage("yatra", stages.EXECUTING,
                     "Waiting for YATRA's own Envato session")
    with resource_lanes.claim(
        "browser:yatra-envato",
        heartbeat=lambda: job_recovery.heartbeat(_connect, str(job["id"])),
        cancelled=lambda: not _job_is_active(str(job["id"])),
    ):
        stages.set_stage("yatra", stages.EXECUTING,
                         "Acquiring stock footage for every approved scene")
        footage = _yatra_acquire_complete_footage(
            plan_file, asset_folder, str(narration.get("manifest") or "")
        )
        if not footage.get("ok") or not footage.get("all_covered"):
            raise RuntimeError("YATRA could not acquire the complete unique-shot 1080p plan; "
                               "refusing to cut with repeated or missing footage\n"
                               f"acquire_scenes said:\n{footage.get('detail', '')}")
        stages.set_stage("yatra", stages.EXECUTING,
                         "Acquiring a quiet licensed Envato ambient music bed")
        music = _yatra_acquire_music(tool, plan_record, asset_folder)
        if not music.get("ok"):
            raise RuntimeError(f"YATRA ambient music acquisition failed: {music}")
    stages.set_stage("yatra", stages.EXECUTING,
                     "Recording official-source browser demos")
    captures = _yatra_record_captures({**payload, 'assetFolder': asset_folder}, video_title or asset_folder)
    if not captures.get("ok"):
        # Official-page demos are optional evidence inserts. route_visuals
        # selects OBS only for recordings that actually exist and otherwise
        # supplies the scene's information card, so an unavailable OBS
        # websocket must cost the demos, not the already acquired video.
        # Keep the failed result intact for the production receipt while
        # making the deliberate degradation explicit.
        captures = {**captures, "skipped": True, "optional_failure": True}
    stages.set_stage("yatra", stages.EXECUTING,
                     "Drawing the cards, cutting the picture to the voice, checking the result")
    cut = _yatra_cut_video(plan_file, asset_folder)
    if not cut.get("ok"):
        # A cut that failed (or failed QC) is not a deliverable. Handing it on
        # sent ARES to build SEO for a master that did not exist (2026-10-06).
        step = cut.get("failed_at") or "cut"
        detail = str((cut.get(step) or {}).get("detail") or "")[-1500:]
        earlier = cut.get("director_render_motion_v3") or cut.get("director_render_motion_v2")
        if earlier:
            # Preserve the primary renderer error when the fallback also fails.
            detail = f"{earlier.get('engine')} failed first:\n{str(earlier.get('detail') or '')[-1500:]}\n--- then:\n{detail}"
        raise RuntimeError(f"YATRA cut failed at {step}; nothing was handed to HELIOS/LYRA.\n{detail}")
    stages.set_stage("yatra", stages.CARRYING_TO_HEAD,
                     "Taking the verified master and production receipt back to HELIOS")
    _require_active_job(job, "deliver the verified master to HELIOS")
    report = enqueue_job("helios", json.dumps({
        "brand": "sonia_travel_vlogs", "worker": "yatra",
        "title": video_title, "format": "travel_video_production",
        "published": False, "output": f"LAO job {lao_job_id}",
        "lao_job": lao_job_id, "lao_receipt": last,
        "asset_folder": asset_folder, "opening_map": opening_map,
        "footage": footage, "captures": captures, "obs_plan": (obs_plan.get("detail") or "")[-600:],
        "narration": narration, "music": music, "cut": cut,
        "origin_job": payload.get("origin_job"),
    }), mode="report", tier="fast")
    stages.set_stage("yatra", stages.DELIVERING, "Delivered YATRA artifacts to HELIOS")
    time.sleep(1); stages.clear_stage("yatra")
    return {"agent": "YATRA", "mode": "preproduction", "published": False,
            "lao_job": lao_job_id, "asset_folder": asset_folder,
            "opening_map": opening_map, "footage": footage,
            "captures": captures, "narration": narration,
            "music": music,
            "cut": cut,
            "handed_to": {"agent": "IRIS", "job_id": report["id"]}}


# The capability check asks whether an agent holds *any* capability, not
# whether it holds one particular one.
#
# The first version required tool:invoke from everybody. That was wrong and
# would have refused PEITHO on its first run: PEITHO does memory work, holds
# memory:read and memory:write deliberately, and needs no tools at all. It
# would have been refused for the wrong reason - not "this agent may not do
# that" but "I checked the wrong thing" - which is the worse of the two,
# because from outside the two look identical.
#
# _govern cannot know which capability a handler will reach for before it
# runs, so it asks the only question it can honestly answer here: is this
# agent capable of anything at all. That still refuses PIXEL, which is dormant
# and declares nothing. Per-capability enforcement belongs at the point of
# use, and is not pretended at from this distance.
KNOWN_CAPABILITIES = (
    "file:read", "file:write", "memory:read", "memory:write",
    "tool:invoke", "network:fetch", "code:execute", "channel:send",
    "schedule:create", "system:admin",
)

# Controls that do not belong on this path, tagged rather than left to look
# like an oversight. NOT_APPLICABLE is not PASS, and the gate checker prints
# it as its own outcome for the same reason the ledger keeps unpriced apart
# from zero: an absence and a clean result are different facts.
NOT_APPLICABLE: dict[str, str] = {
    "release_gate": (
        "certifies a product for release after a security and privacy review. "
        "A KDP manuscript is not reviewed by WARDEN or AEGIS and never enters "
        "the app lifecycle, so there is nothing here for the gate to certify."
    ),
    "event_taxonomy": (
        "validates events against _contracts/events/taxonomy.yaml. This "
        "runtime publishes no events at all - there is no bus - so validation "
        "would have nothing to read. Adding one is a separate decision."
    ),
    "product_registry": (
        "holds products with a lifecycle, cost and financials. Books are not "
        "registered as products and the KDP path has no product_id. Whether "
        "they should be is a modelling question, not a control that is missing."
    ),
}


def _govern(job: dict[str, Any]) -> dict[str, Any] | None:
    """Run every applicable control before the work happens.

    Returns None to proceed, or a result dict that ends the job without the
    handler ever running. Nothing here raises: a control that can crash the
    worker is a new way to lose a job, and these exist to govern work rather
    than to endanger it.

    The order is deliberate. Idempotency first, because the cheapest thing to
    get right is not doing paid work twice. Then capability, which is a flat
    refusal. Then budget, which is the only one that can say "not now" rather
    than "not you".
    """
    agent_id = job.get("agent_id", "")
    job_id = job.get("id", "")

    attempt_key = f"job:{job_id}"
    # A checkpoint recovery is a new execution attempt of the same durable
    # task, not a repeat of its paid work.  The queue owns the attempt counter;
    # the external reference proves the handler can reattach/resume.  Login
    # recovery remains the one checkpoint flow whose durable state is stored
    # outside external_job.
    resume_count = int(job.get("resume_count") or 0)
    if resume_count > 0 and (agent_id == "imprimatur"
                             or bool(job_recovery.resume_target(job))):
        attempt_key += f":resume:{resume_count}"
    repeat = floors_bridge.claim_once(attempt_key, event_type="job.execute")
    if repeat is False:
        return {"governed": "refused",
                "reason": "this job id has already been executed; repeating it "
                          "would repeat whatever it paid for"}

    answers = [floors_bridge.may(agent_id, c) for c in KNOWN_CAPABILITIES]
    if any(a is None for a in answers):
        pass                       # registry cannot answer; dispatch already allowed
    elif not any(answers):
        return {"governed": "refused",
                "reason": f"{agent_id} holds no capability at all in its own "
                          f"capabilities.yaml, which denies by default. An agent "
                          f"that declares nothing can do nothing - which is what "
                          f"dormant means, and it is a declaration rather than an "
                          f"oversight."}

    verdict = floors_bridge.budget_verdict(agent_id, str(job.get("floor_id") or ""), job=job)
    if verdict is not None and not verdict.allowed:
        return {"governed": "refused", "reason": verdict.explain()}

    floors_bridge.audit(agent_id=agent_id, floor_id=str(job.get("floor_id") or "1"),
                        job_id=job_id, correlation_id=job_id,
                        action=job.get("mode") or "execute",
                        approval_level="A0", status="started")
    return None


def execute_job(job: dict[str, Any]) -> dict[str, Any]:
    refusal = _govern(job)
    if refusal is not None:
        return refusal

    # A floor head watching its own floor is the same action whichever head is
    # doing it, so it routes here rather than being copy-pasted into fourteen
    # handlers -- most of which are still _local_plan stubs with nothing to
    # copy it into. Deliberately placed AFTER _govern: a head that holds no
    # capability cannot watch either, which is the honest answer rather than a
    # quiet exemption for our own machinery.
    if str(job.get("mode") or "").strip().lower() == "watch":
        head_id = str(job["agent_id"])
        stages.set_stage(head_id, stages.EXECUTING, "Checking this floor for failed or stuck work")
        try:
            if head_id == "helios":
                # HELIOS's bounded repair runner is intentionally lazy-loaded
                # by floor_watch. Reload it for each pass so a committed
                # fallback fix is not stranded in the long-lived worker's
                # module cache until an unrelated process restart.
                from openjarvis.one_agents import helios_self_heal
                importlib.reload(floor_watch)
                importlib.reload(helios_self_heal)
            return floor_watch.watch_floor(_connect, head_id)
        finally:
            stages.clear_stage(head_id)

    publishing_payload = _json_task(job)
    correlation_id = str(publishing_payload.get("mission_id") or
                         publishing_payload.get("origin_job") or job.get("id", ""))
    handlers = {
        "helios": _run_helios,
        "zeus": _run_zeus,
        "athena": _run_athena,
        "jobhunt": _run_daedalus,
        "titan": _run_titan,
        "beta": _run_beta,
        "apollo": _run_apollo,
        "hermes": _run_hermes,
        "biblos": _run_biblos,
        "scribe": _run_scribe,
        "mercury": _run_mercury,
        "imprimatur": _run_imprimatur,
        "peitho": _run_peitho,
        "leda": _run_leda,
        "metron": _run_metron,
        "ia": _run_iris,
        "muse": _run_muse,
        "kairos": _run_kairos,
        "herald": _run_herald,
        "chandan": _run_chandan,
        "planexium": _run_planexium,
        "yatra": _run_yatra,
        "fabula": _run_fabula,
        "echo": _run_echo,
        "vista": _run_vista,
        "lyra": _run_lyra,
        "ares": _run_ares,
        "alfa": _run_alfa,
        "poseidon": _run_poseidon,
        "hephaistos": _run_hephaistos,
        "argus": _run_argus,
    }
    handler = handlers.get(job["agent_id"], _local_plan)
    try:
        result = handler(job)
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised unchanged
        from openjarvis.tools.kdp_browser_publisher import AmazonChallenge, validate_packet, state_path, write_state
        if job.get("agent_id") == "imprimatur" and isinstance(exc, AmazonChallenge):
            payload = _json_task(job)
            packet = validate_packet(payload["run_dir"])
            prior = json.loads(state_path(packet).read_text(encoding="utf-8"))
            prior = prior.get("resume_state", prior)
            write_state(packet, "AWAITING_LOGIN", resume_state=prior,
                        resume_phase=payload.get("phase", "prepare"), job_id=job["id"],
                        scribe_job_id=payload.get("scribe_job_id"), reason=str(exc))
            stages.scribe_waits_for_kdp(payload["run_dir"], packet.title,
                                        payload.get("scribe_job_id", ""))
            _publishing_event(
                job, agent="IMPRIMATUR", event_type="login_required", stage="awaiting_login",
                summary="KDP login required; existing book and publishing phase preserved",
                details={"reason": str(exc)}, status="waiting",
            )
            return {"_await_login": True, "status": "awaiting_login",
                    "run_dir": payload["run_dir"], "phase": payload.get("phase", "prepare"),
                    "reason": str(exc)}
        if job.get("agent_id") == "hermes":
            _publishing_event(
                job, agent="HERMES", event_type="research_failed",
                stage="execution_error", summary="Research stopped with an execution error",
                details={"error": f"{type(exc).__name__}: {exc}"[:1200]}, status="blocked",
            )
        floors_bridge.audit(agent_id=job.get("agent_id", ""),
                            floor_id=str(job.get("floor_id") or "1"),
                            job_id=job.get("id", ""), correlation_id=correlation_id,
                            action=job.get("mode") or "execute",
                            approval_level="A0", status="failed",
                            result=type(exc).__name__)
        raise
    floors_bridge.audit(agent_id=job.get("agent_id", ""),
                        floor_id=str(job.get("floor_id") or "1"),
                        job_id=job.get("id", ""), correlation_id=correlation_id,
                        action=job.get("mode") or "execute",
                        approval_level="A0", status="succeeded",
                        cost=result.get("cost_usd") if isinstance(result, dict) else None)
    return result


def _job_watchdog_seconds(job: dict[str, Any] | None = None) -> float:
    """Outer, additive safety-net timeout for a *whole* job run.

    Some operations legitimately block for hours. SCRIBE sits on
    LAO's KDP factory until the book exists. The default 45-minute net would
    mark a perfectly healthy book run as failed partway through, so that agent
    gets a window sized to its own LAO wait plus margin. Scoped production
    operations below likewise outlive their internal waits; others keep the short net.

    This does NOT replace, shorten, or otherwise touch any existing
    per-call timeout inside individual tools/agents (e.g. image/video
    generation calls keep their own existing timeouts exactly as-is).
    It exists only so that if a job hangs somewhere with no internal
    timeout of its own (e.g. a stuck browser-automation wait), the
    job-queue row still gets moved out of 'running' instead of staying
    stuck forever. Configurable via ONE_JOB_WATCHDOG_SECONDS; defaults
    to 45 minutes, which is generous enough for the slowest known IA
    image+video+merge pipeline run.
    """
    try:
        default = max(60.0, float(os.environ.get("ONE_JOB_WATCHDOG_SECONDS", "2700")))
    except ValueError:
        default = 2700.0

    if job and job.get("agent_id") == "fabula":
        payload = _json_task(job)
        # Match _run_fabula's preparation dispatch, not narration/checkpoint work.
        if payload.get("brand") == "sonia_travel_vlogs" and not payload.get("preproduction_job"):
            provider_wait, poll_seconds, tool_timeout = _yatra_preproduction_timing()
            # 120s robot preflight plus 480s validation/handoff margin; start
            # and the final status probe allow seven and nine HTTP calls
            # (login, five scope lookups, job and logs/artifacts). Intermediate
            # probes consume the provider budget, rather than adding to it.
            budget = provider_wait + poll_seconds + 16 * tool_timeout + 600.0
            return max(default if math.isfinite(default) else 2700.0, budget)

    if job and job.get("agent_id") == "echo":
        payload = _json_task(job)
        if (payload.get("brand") == "sonia_travel_vlogs"
                and payload.get("stage") == "community_poll"):
            # A poll can make three attempts at a four-option set. Each option can try six sequential photo jobs,
            # and every photo job has its own bounded 10-minute wait. The outer net must outlive that legitimate
            # 12-hour worst case; on 2026-10-24 the generic 45-minute net abandoned a poll while it was still working.
            return max(default, 13 * 3600.0)
    if job and job.get("agent_id") == "planexium":
        return max(default, 16 * 3600.0)
    if job and job.get('agent_id') == 'yatra':
        # Sequential full-video acquisition has its own bounded per-clip waits.
        # Outer watchdog must outlive 12h acquisition + capture/edit stages.
        return max(default, 16 * 3600.0)
    if job and job.get("agent_id") == "lyra":
        payload = _json_task(job)
        if (payload.get("brand") == "sonia_travel_vlogs"
                and payload.get("stage") == "seo"):
            # LYRA generates three thumbnail variants sequentially. Each has a
            # bounded 780s LAO wait, but every status request can itself take
            # up to 30s and the localization/upload gate still runs afterward.
            # The generic 45-minute net can therefore abandon healthy work
            # before its own bounded steps finish (Philippines, 2026-10-25).
            return max(default, 2 * 3600.0)
    if job and job.get("agent_id") == "chandan":
        # One ChatGPT chat makes 75 frames (its own 6 h provider limit), then narration and render. On 2026-10-22
        # the 45-minute net marked the Virat run failed at 75 minutes; the work finished anyway and handed to ARES.
        return max(default, 8 * 3600.0)
    if job and job.get("agent_id") == "scribe":
        try:
            lao_wait = float(os.environ.get("ONE_LAO_MAX_WAIT_SECONDS", "10800"))
        except ValueError:
            lao_wait = 10800.0
        return max(default, lao_wait + 600.0)   # LAO's own wait plus 10 min
    return default


# Job ids the watchdog has given up on, which is the only way to tell an
# abandoned thread from a job that is simply still working: a thread named
# "job-<id>" looks identical either way. Reading threading.enumerate() alone
# counted healthy jobs as abandoned, which made the periodic log line claim a
# leak whenever anything was running at all (seen 2026-10-14 against a HERMES
# research job 13 minutes into a 19-minute run), and - worse - let two healthy
# jobs plus one real abandonment reach the limit below and take the worker
# process down with them.
_ABANDONED_JOB_IDS: set[str] = set()


def abandoned_job_threads() -> list["threading.Thread"]:
    """Every job-execution thread still alive past its own watchdog timeout.

    Keyed on the "job-<id>" name run_worker() already gives each thread, and
    narrowed to the ids the watchdog actually abandoned, so a job that is
    merely slow is not counted as a leak. Python has no supported way to
    forcibly terminate a thread from the outside, so this only makes the leak
    visible; it cannot reclaim the memory those threads are holding. See
    run_worker()'s watchdog branch for where this is logged.
    """
    import threading
    return [t for t in threading.enumerate()
            if t.name.startswith("job-") and t.is_alive()
            and t.name[len("job-"):] in _ABANDONED_JOB_IDS]


def _finish_active_job(job: dict[str, Any], outcome: dict[str, Any]) -> None:
    """Process a job thread's outcome once it has finished on its own
    (i.e. NOT abandoned to the watchdog -- see _abandon_active_job for
    that branch). Split out of run_worker 2026-09-19 so multiple jobs'
    completions can each be processed independently once the worker loop
    stopped blocking on a single thread.join() per iteration -- see
    run_worker's own docstring for why that blocking was there and why it
    had to go."""
    # cancel_job/watchdog may release the queue row while Python code that
    # cannot be force-killed is still unwinding. That stale thread no longer
    # owns the result and must not overwrite failed/cancelled with completed.
    if not _job_is_active(str(job.get("id") or "")):
        return
    if "error" in outcome:
        trace = str(outcome.get("traceback") or "").strip()
        agent_id = str(job.get("agent_id") or "").lower()
        if agent_id in {"hermes", "biblos", "scribe", "imprimatur", "mercury", "leda", "metron", "peitho"}:
            _publishing_event(
                job, agent=agent_id.upper(), event_type="execution_failed",
                stage="worker", summary=f"{agent_id.upper()} execution failed",
                details={"error": str(outcome.get("error") or "")[:1000]},
                status="failed",
            )
        fail_job(job["id"], RuntimeError(
            f"{outcome['error']}\n\n{trace}" if trace else str(outcome["error"])
        ))
        return
    result = outcome.get("result", {})
    # The gate is asked for, not asserted.
    #
    # _await_human_upload is the handler saying "I have reached the
    # point where a person uploads this by hand". Whether that needs a
    # person is not the handler's call - it is declared in the agent's
    # permissions.yaml and resolved through the floors registry, where
    # publish_to_store is red for SCRIBE. A handler that asserts its
    # own gate is the same shape as an agent asserting its own
    # privileges, and it fails the same way: silently, on the day
    # somebody edits it.
    #
    # None means the registry could not answer - tree absent, index
    # stale - and None is not permission. Hold, and let a person look.
    if result.pop("_await_login", False):
        mark_awaiting_login(job["id"], result)
    elif result.pop("_blocked", False):
        mark_blocked(job["id"], result)
    elif result.pop("_await_growth_review", False):
        mark_awaiting_growth_review(job["id"], result)
    elif result.pop("_await_human_upload", False):
        gated = floors_bridge.needs_approval(
            job.get("agent_id", ""), "publish_to_store")
        if gated is False:
            finish_job(job["id"], result)
        else:
            mark_awaiting_upload(job["id"], result)
    else:
        finish_job(job["id"], result)


def _abandon_active_job(job: dict[str, Any]) -> None:
    """A job thread is still alive past its own watchdog deadline. Log it,
    fail the queue row, and -- past a small threshold of these piling up --
    exit the whole process so the memory they hold is actually reclaimed
    (sys.exit raises SystemExit, which propagates straight out of this
    call and out of run_worker's loop uncaught -- there is no return from
    that branch, by design). Split out of run_worker 2026-09-19, same
    reason as _finish_active_job -- see run_worker's docstring."""
    # We cannot forcibly kill a Python thread, so it keeps running
    # in the background (and will simply be ignored when/if it
    # eventually finishes), but the queue row itself is freed up
    # immediately so the dashboard stops showing a permanently
    # frozen RUNNING card and the worker loop can keep picking up
    # other queued jobs.
    #
    # What was invisible until now: that abandoned thread does not
    # free the memory it was holding (API response bytes, image/
    # video buffers, whatever the stuck step had in scope) - it just
    # sits there, alive, forever, because nothing ever joins it.
    # Confirmed live 2026-09-12: this worker process's RSS grew to
    # 3.27 GB over ~2 hours with no other explanation found in this
    # file's module-level state. This does not free that memory -
    # a thread genuinely cannot be force-killed from the outside in
    # Python - but it makes every abandonment loud in the log with a
    # running total, so the leak is a number someone can watch
    # instead of a silent multi-GB surprise discovered in Task
    # Manager. abandoned_job_threads() reads threading.enumerate()
    # directly rather than keeping a separate list, so the count can
    # never drift from reality the way a hand-maintained counter
    # could.
    _ABANDONED_JOB_IDS.add(str(job["id"]))
    still_abandoned = abandoned_job_threads()
    watchdog_seconds = _job_watchdog_seconds(job)
    print(
        f"[one-agents] job {job['id']} ({job.get('agent_id')}) exceeded its "
        f"watchdog and was abandoned running in the background - "
        f"{len(still_abandoned)} such thread(s) now alive. Each one holds "
        f"memory that will not be freed until it finishes on its own; a "
        f"climbing count here is the leading indicator of the RSS growth "
        f"that used to go unnoticed until it reached multiple GB.",
        flush=True,
    )
    fail_job(
        job["id"],
        TimeoutError(
            f"Job exceeded watchdog timeout of {watchdog_seconds:.0f}s "
            "and was marked failed so it would not stay stuck forever. "
            "The underlying step may still finish in the background; "
            "re-run the task if needed."
        ),
    )
    if job.get("agent_id") == "hermes":
        _publishing_event(
            job, agent="HERMES", event_type="research_timeout",
            stage="watchdog", summary="Research stopped by the job watchdog",
            details={"timeout_seconds": watchdog_seconds,
                     "background_result_policy": "discarded"}, status="failed",
        )

    # Observability alone (the log line above) does not stop the
    # leak - it only lets a human notice it. The one thing that
    # DOES reclaim the memory an abandoned thread holds is ending
    # the process: every thread here is daemon=True, so the
    # interpreter does not wait for them on exit - they, and
    # whatever they were holding, are gone the moment this process
    # is. So past a small threshold, exit deliberately rather than
    # let the count climb toward another 3.27 GB. This is safe only
    # because something outside this process restarts it when it's
    # gone - see start-one.ps1's dedup guard, and the scheduled task
    # that calls it periodically (ONE-AutoRestart) so a bounce here
    # is a few minutes of no new jobs claimed, not a dead worker.
    max_abandoned = int(os.environ.get("ONE_WORKER_MAX_ABANDONED_THREADS", "3"))
    if len(still_abandoned) >= max_abandoned:
        print(
            f"[one-agents] {len(still_abandoned)} abandoned job thread(s) reached "
            f"the limit ({max_abandoned}) - exiting deliberately so the memory "
            f"they hold is actually reclaimed, and a fresh worker can be started. "
            f"This process depends on something else (start-one.ps1 / the "
            f"ONE-AutoRestart scheduled task) noticing it is gone and restarting "
            f"it; if that is not in place, the worker stays down until someone "
            f"runs start-one.ps1 by hand.",
            flush=True,
        )
        import sys
        sys.exit(1)


def run_worker(poll_seconds: float = 2.0) -> None:
    """Claim and run queued jobs.

    Concurrency fix (2026-09-19): this used to claim ONE job, spawn its
    thread, then immediately worker_thread.join(timeout=watchdog) -- which
    BLOCKS this entire loop, including the next claim_job() call, until
    that one job either finishes or hits its (up to multi-hour, for
    SCRIBE/MUSE-style LAO waits) watchdog. Confirmed live 2026-09-18/19:
    while a MUSE job was mid-reel, a second, unrelated, few-second HERMES
    research job sat "queued" the entire time -- the whole 25-agent company
    could only ever have ONE agent genuinely executing at once, no matter
    how many floors looked busy in the 3D building (which only reflects
    whatever WAS actually claimed, so it was reporting the truth -- the
    truth was just "everything else is waiting in a single global line").
    That is also why two floors "running" at once only ever showed one
    speech bubble: only one was ever really running.

    Fixed by tracking multiple active job threads (bounded by
    ONE_WORKER_MAX_CONCURRENT_JOBS, default 6) instead of blocking on one.
    Each loop iteration reaps any finished/expired threads first (freeing a
    slot), then claims new jobs up to the concurrency limit. claim_job()'s
    own BEGIN IMMEDIATE + conditional UPDATE (see its docstring) already
    made concurrent claims race-safe before this change -- multiple threads
    calling it around the same moment was already fine, this function
    simply never let that happen. Every job thread's own completion
    handling (_finish_active_job) and watchdog-abandonment handling
    (_abandon_active_job) is unchanged in substance, just called per-thread
    instead of inline after a single join().
    """
    import threading

    # IMPRIMATUR's ordinary 30-minute retry uses a lightweight daemon timer,
    # but a Windows restart/power loss destroys that timer. The durable state
    # file is the recovery source: reconstruct one poll job per pending title
    # before normal queue claiming starts.
    try:
        output_root = Path.home() / "Documents" / "LAO" / "kdp-book-factory" / "output"
        with _connect() as db:
            active_imprimatur = [
                json.loads(row["task"])
                for row in db.execute(
                    "SELECT task FROM jobs WHERE agent_id = 'imprimatur' "
                    "AND status IN ('queued', 'running')"
                ).fetchall()
                if row["task"].lstrip().startswith("{")
            ]
        active_dirs = {str(item.get("run_dir") or "") for item in active_imprimatur}
        resumed_polls = 0
        for state_file in output_root.glob("*/kdp_publish_state.json"):
            state = json.loads(state_file.read_text(encoding="utf-8"))
            run_dir = str(state_file.parent)
            if state.get("stage") != "AWAITING_ASIN" or run_dir in active_dirs:
                continue
            scribe_job_id = str(state.get("scribe_job_id") or "")
            if not scribe_job_id:
                continue
            enqueue_job("imprimatur", json.dumps({
                "phase": "poll",
                "run_dir": run_dir,
                "scribe_job_id": scribe_job_id,
                "approval_id": str(state.get("approval_id") or ""),
                "poll_attempt": int(state.get("poll_attempt") or 0),
                "recovered_after_restart": True,
            }), mode="execute", tier="fast")
            resumed_polls += 1
        if resumed_polls:
            print(f"[one-agents] resumed {resumed_polls} pending KDP ASIN poll(s)", flush=True)
    except Exception as exc:  # noqa: BLE001 - recovery must never stop the worker
        print(f"[one-agents] KDP poll recovery skipped: {exc}", flush=True)

    # A worker that dies mid-poll leaves its job in 'running' forever, because
    # claim_job() only ever selects 'queued'. That is how every MUSE run and
    # most SCRIBE runs were lost: the LAO job carried on and finished into a
    # folder nothing collected. Sweep those before taking new work - a job with
    # a recorded LAO id goes back to the queue and its handler re-attaches to
    # the same external job, and one without a recorded id is failed rather
    # than risking a duplicate multi-hour run.
    try:
        recovered = job_recovery.sweep(_connect)
        for entry in recovered["resumed"] + recovered["failed"]:
            stages.clear_stage(entry["agent_id"])
        line = job_recovery.describe(recovered)
        if line:
            print(f"[one-agents] restart recovery -- {line}", flush=True)
    except Exception as exc:  # noqa: BLE001 - recovery must never stop the worker
        print(f"[one-agents] restart recovery skipped: {exc}", flush=True)
    _reconcile_publishing_projection()

    try:
        max_concurrent = max(1, int(os.environ.get("ONE_WORKER_MAX_CONCURRENT_JOBS", "6")))
    except ValueError:
        max_concurrent = 6

    active: dict[str, dict[str, Any]] = {}  # job_id -> {thread, job, outcome, deadline}
    last_schedule_check = 0.0
    last_leak_check = 0.0
    last_recovery_check = 0.0
    while True:
        if time.time() - last_recovery_check >= 60:
            # Startup can skip a freshly orphaned row. Revisit after its lease
            # expires; protect local threads and heartbeat all live owners,
            # including long local renders that do not have a LAO poll loop.
            for owned_id in active:
                job_recovery.heartbeat(_connect, owned_id)
            try:
                recovered = job_recovery.sweep(_connect, active_ids=active)
                for entry in recovered["resumed"] + recovered["failed"]:
                    stages.clear_stage(entry["agent_id"])
                line = job_recovery.describe(recovered)
                if line:
                    print(f"[one-agents] periodic recovery -- {line}", flush=True)
            except Exception as exc:
                print(f"[one-agents] periodic recovery skipped: {type(exc).__name__}", flush=True)
            last_recovery_check = time.time()
        if time.time() - last_schedule_check >= 30:
            try:
                _resume_kdp_login_jobs()
            except Exception as exc:
                print(f"[one-agents] KDP login probe deferred: {type(exc).__name__}", flush=True)
            _enqueue_due_recurring_jobs()
            last_schedule_check = time.time()
        if time.time() - last_leak_check >= 300:
            # Periodic, not just on the moment a new thread gets abandoned -
            # the count only ever goes up between restarts (nothing removes
            # a finished-late thread from threading.enumerate() until
            # Python's own bookkeeping does), so this is the signal that
            # would have shown the 3.27 GB growth building well before Task
            # Manager did. Quiet when there is nothing to report.
            stuck = abandoned_job_threads()
            if stuck:
                print(f"[one-agents] {len(stuck)} abandoned job thread(s) still alive: "
                      f"{', '.join(t.name for t in stuck)}", flush=True)
            last_leak_check = time.time()

        # Reap anything finished or expired BEFORE claiming more, so a slot
        # a job just vacated is available to the claim pass below in the
        # same iteration.
        for job_id in list(active.keys()):
            entry = active[job_id]
            thread: threading.Thread = entry["thread"]
            if not thread.is_alive():
                thread.join()  # already finished; this just reaps it, no wait
                _finish_active_job(entry["job"], entry["outcome"])
                del active[job_id]
            elif time.time() >= entry["deadline"]:
                _abandon_active_job(entry["job"])  # raises SystemExit past the threshold
                del active[job_id]

        # Claim new work up to the concurrency limit.
        while len(active) < max_concurrent:
            job = claim_job()
            if not job:
                break

            outcome: dict[str, Any] = {}

            def _make_target(job: dict[str, Any], outcome: dict[str, Any]):
                def _target() -> None:
                    try:
                        outcome["result"] = execute_job(job)
                    except Exception as exc:  # noqa: BLE001 - surfaced via outcome
                        outcome["error"] = exc
                        import traceback
                        outcome["traceback"] = traceback.format_exc()
                return _target

            worker_thread = threading.Thread(
                target=_make_target(job, outcome), name=f"job-{job['id']}", daemon=True
            )
            worker_thread.start()
            active[job["id"]] = {
                "thread": worker_thread, "job": job, "outcome": outcome,
                "deadline": time.time() + _job_watchdog_seconds(job),
            }

        time.sleep(poll_seconds)
