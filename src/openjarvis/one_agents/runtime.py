"""Durable, local-first runtime for ONE's named agents."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from openjarvis.one_agents import floors_bridge, job_recovery, memory, stages


AGENTS: dict[str, dict[str, str]] = {
    "zeus": {"name": "ZEUS", "role": "Cross-division orchestration, escalation, and resource-allocation operator", "floor_id": "11", "floor_name": "ONE-JARVIS Executive Command", "division": "executive"},
    "athena": {"name": "ATHENA", "role": "Opportunity discovery, research, and scoring operator", "floor_id": "10", "floor_name": "Venture & Opportunity Lab", "division": "venture_lab"},
    "jobhunt": {"name": "DAEDALUS", "role": "Micro-SaaS and AI product build/QA operator", "floor_id": "9", "floor_name": "Micro-SaaS & AI Product Factory", "division": "micro_saas"},
    "titan": {"name": "TITAN", "role": "Apps, websites, and games build/ship operator", "floor_id": "8", "floor_name": "Apps / Websites / Games", "division": "apps_web_games"},
    "beta": {"name": "BETA", "role": "Browser extensions, plugins, and utility-tools delivery operator", "floor_id": "7", "floor_name": "Digital Utilities", "division": "digital_utilities"},
    "apollo": {"name": "APOLLO", "role": "Courses, templates, and digital-product operator", "floor_id": "6", "floor_name": "Digital Products & Education", "division": "digital_products"},
    "hermes": {"name": "HERMES", "role": "KDP fiction/non-fiction research and publishing operator", "floor_id": "5", "floor_name": "Book Publishing (KDP)", "division": "publishing", "seat": "head"},
    # First worker agent under a floor head — sits at an open desk on Floor 5
    # and is the one that actually drives LAO's KDP factory to completion.
    "scribe": {"name": "SCRIBE", "role": "KDP manuscript production worker", "floor_id": "5", "floor_name": "Book Publishing (KDP)", "division": "publishing", "seat": "worker", "reports_to": "hermes"},
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
    "kairos": {"name": "KAIROS", "role": "aibyvineet channel content production worker", "floor_id": "4", "floor_name": "Media & Content", "division": "media", "seat": "worker", "reports_to": "ia"},
    "ares": {"name": "ARES", "role": "SEO, social, and cross-floor distribution operator", "floor_id": "3", "floor_name": "Growth & Distribution", "division": "growth"},
    "alfa": {"name": "ALFA", "role": "Pricing, funnels, and revenue-attribution operator", "floor_id": "2", "floor_name": "Commerce & Monetization", "division": "commerce"},
    "poseidon": {"name": "POSEIDON", "role": "Finance, HR, Admin, and Legal/Compliance operator", "floor_id": "1", "floor_name": "Corporate Services", "division": "corporate"},
    "hephaistos": {"name": "HEPHAISTOS", "role": "ONE runtime, workflow-engine, and LAO-bridge operator", "floor_id": "B1", "floor_name": "Platform Engineering", "division": "platform"},
    "argus": {"name": "ARGUS", "role": "Health, audit, kill-switch, and rate-limit operator", "floor_id": "B2", "floor_name": "Security & SRE", "division": "security"},
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


def _enqueue_due_recurring_jobs() -> None:
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

    if os.environ.get("JOBHUNT_AUTOSCOUT", "true").lower() not in {"1", "true", "yes", "on"}:
        return
    jobhunt_interval = max(3600, int(os.environ.get("JOBHUNT_SCAN_INTERVAL_SECONDS", "86400")))
    with _connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO agent_schedules (agent_id, interval_seconds, next_run_epoch) VALUES ('jobhunt', ?, 0)",
            (jobhunt_interval,),
        )
        schedule = db.execute("SELECT * FROM agent_schedules WHERE agent_id = 'jobhunt'").fetchone()
        if not schedule or not schedule["enabled"] or schedule["next_run_epoch"] > now_epoch:
            return
        job_id = f"jobhunt-{uuid.uuid4().hex[:12]}"
        db.execute(
            "INSERT INTO jobs (id, agent_id, task, mode, status, created_at, updated_at) VALUES (?, 'jobhunt', ?, 'execute', 'queued', ?, ?)",
            (job_id, "[scheduled] Prepare QA/Product job-search opportunities from local alert inbox", now, now),
        )
        db.execute(
            "UPDATE agent_schedules SET interval_seconds = ?, next_run_epoch = ? WHERE agent_id = 'jobhunt'",
            (jobhunt_interval, now_epoch + jobhunt_interval),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def enqueue_job(agent_id: str, task: str, mode: str = "plan", tier: str = "fast") -> dict[str, Any]:
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
    job_id = f"{agent_id}-{uuid.uuid4().hex[:12]}"
    now = _now()
    with _connect() as db:
        db.execute(
            "INSERT INTO jobs (id, agent_id, task, mode, tier, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)",
            (job_id, agent_id, task[:4000], mode, tier, now, now),
        )
    return get_job(job_id) or {}


def get_job(job_id: str) -> dict[str, Any] | None:
    with _connect() as db:
        return _row(db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


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


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    with _connect() as db:
        rows = db.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 100)),)
        ).fetchall()
    return [dict(row) for row in rows]


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


def claim_job() -> dict[str, Any] | None:
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            return None
        now = _now()
        changed = db.execute(
            "UPDATE jobs SET status = 'running', progress = 5, updated_at = ? WHERE id = ? AND status = 'queued'",
            (now, row["id"]),
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


def confirm_scribe_upload(job_id: str) -> dict[str, Any]:
    """Dashboard 'mark uploaded' action -- the Chairman confirms they actually
    submitted the book on kdp.amazon.com by hand. Explicit call, 2026-08-26:
    "jab book upload ho jayegi to SCRIBE ko message bhi dena hai ki wo book
    handover kar sakta hai PEITHO ko tabhi database mn bhi update hoga" --
    only this action enqueues PEITHO's job and finishes SCRIBE's; nothing
    else does. Starting PEITHO before this (post-publish marketing) would
    have nothing real to work from, since the book isn't actually live yet.
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

    celebration = f"“{title}” is live! 🎉" if title else "It's live! 🎉"
    stages.set_stage("scribe", stages.CELEBRATING, celebration)
    stages.set_stage("peitho", stages.CELEBRATING, celebration)
    time.sleep(float(os.environ.get("ONE_CELEBRATE_SECONDS", "9")))
    stages.clear_stage("scribe")

    peitho_job = enqueue_job(
        "peitho",
        json.dumps({
            "run_dir": run_dir, "title": title, "lao_job": lao_job_id,
            "kdp_packet_path": kdp_packet_path,
        }),
        mode="execute", tier="fast",
    )

    result["uploaded_confirmed_at"] = _now()
    result["handed_to"] = {"agent": "PEITHO", "job_id": peitho_job["id"]}
    with _connect() as db:
        db.execute(
            "UPDATE jobs SET status = 'completed', progress = 100, result = ?, updated_at = ? WHERE id = ?",
            (json.dumps(result, ensure_ascii=True), _now(), job_id),
        )

    memory.remember(
        agent="SCRIBE", floor_id="5", floor_name="Book Publishing (KDP)",
        kind="Upload Confirmed",
        body=f"Chairman confirmed “{title}” is live on Amazon KDP. Handed off to PEITHO.",
        task=title, tags=["kdp", "publishing", "uploaded"],
    )

    return {"scribe_job": get_job(job_id), "peitho_job": peitho_job}


def fail_job(job_id: str, error: Exception) -> None:
    with _connect() as db:
        db.execute(
            "UPDATE jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
            (str(error)[:2000], _now(), job_id),
        )
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

    If this is a SCRIBE job with a LAO job attached (recorded in
    agent_stages.json while `_run_scribe` polls), also asks LAO to stop that
    job -- otherwise the underlying multi-hour pipeline just keeps running
    unattended even after the dashboard says it's dead. Best-effort: a LAO
    API failure here still lets the local job get marked cancelled.
    """
    job = get_job(job_id)
    if not job:
        raise ValueError(f"Unknown job: {job_id}")
    if job["status"] not in {"queued", "running"}:
        raise ValueError(f"Job {job_id} is already {job['status']}, nothing to cancel")

    lao_job_id = ""
    if job["agent_id"] == "scribe":
        scribe_stage = stages.get_stages().get("scribe") or {}
        if scribe_stage.get("worker_job") == job_id or not scribe_stage.get("worker_job"):
            lao_job_id = str(scribe_stage.get("lao_job") or "")

    if lao_job_id:
        try:
            from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool

            process_name = os.environ.get("LAO_KDP_PROCESS", KDP_PROCESS_NAME)
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
    if job["agent_id"] == "scribe":
        stages.clear_stage("hermes")

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
            "- Use deterministic/local steps first, then cloud providers only where configured.\n"
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


def _run_zeus(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 11 - ONE-JARVIS Executive Command. Pending LAO integration."""
    return _local_plan(job)


def _run_athena(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 10 - Venture & Opportunity Lab. Pending LAO integration."""
    return _local_plan(job)


def _run_daedalus(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 9 - Micro-SaaS & AI Product Factory. Pending LAO integration."""
    return _local_plan(job)


def _run_apollo(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 6 - Digital Products & Education. Pending LAO integration."""
    return _local_plan(job)


KDP_PROCESS_NAME = "KDP Book Factory - Full Manuscript Draft"
# Confirmed live against LAO's own /processes list (2026-08-14), not guessed --
# LAO matches on the exact display name, so a near-miss silently fails to start.
IA_PROCESS_NAME = "ImagineIndia Reel - Twice Daily Production"


def _claude_research(prompt: str, max_tokens: int = 1400) -> tuple[str, str]:
    """Ask Claude directly. Returns (text, failure_note); never raises.

    Deliberately separate from the local Ollama planner: the 8B local model
    invents plausible-sounding infrastructure that doesn't exist, which is
    exactly the wrong failure mode for research that feeds a real book run.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return "", "ANTHROPIC_API_KEY is not in ONE's credential vault"
    try:
        import anthropic
    except ImportError as exc:  # optional dep — surface it, never swallow
        return "", f"anthropic package unavailable: {exc}"
    model = os.environ.get("ONE_RESEARCH_MODEL", "claude-haiku-4-5")
    try:
        # verify=False: the same Avast SSL-interception workaround already used
        # for Deepgram, web_search and instagram_insights on this machine — a
        # bare client fails here with a generic "Connection error".
        client = anthropic.Anthropic(
            api_key=api_key,
            http_client=httpx.Client(verify=False, timeout=90.0),
        )
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in message.content
            if getattr(block, "type", None) == "text"
        ).strip()
        return (text, "") if text else ("", f"{model} returned no text")
    except Exception as exc:  # noqa: BLE001 - reported, not hidden
        return "", f"Claude call failed ({model}): {exc}"


def _marker(text: str, key: str, default: str = "") -> str:
    match = re.search(rf"^{key}:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    return match.group(1).strip() if match else default


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

    if mode == "report":
        return _hermes_report(job)

    # The detail is what the building shows in the speech bubble beside HERMES'
    # face, so it carries the Chairman's actual words — not a generic label.
    stages.set_stage("hermes", stages.RESEARCHING,
                     task.strip()[:180] or "Choosing the next KDP title")

    # Read its own history first. Without this the floor happily re-commissions
    # a title it already published — the vault is what makes it memory.
    already = memory.prior_titles("5", "Book Publishing (KDP)")
    avoid = (
        "\n\nAlready commissioned by this floor — do not repeat or closely "
        "overlap these:\n" + "\n".join(f"- {t}" for t in already[:15])
        if already else ""
    )

    brief, note = _claude_research(
        "You are HERMES, head of Book Publishing at a digital holding company, "
        "commissioning the next Amazon KDP title.\n\n"
        f"Request: {task}\n\n"
        "Decide what to commission and why. Ground it in what actually sells on "
        "KDP: real reader demand, a specific reachable audience, and a gap a new "
        "title can genuinely fill. Do not invent internal teams, tools, boards or "
        "databases — the only production system is an automated drafting pipeline.\n\n"
        "Reply in exactly this shape:\n"
        "MODE: fiction | nonfiction\n"
        "REGION: <primary market, e.g. global or india>\n"
        "ANGLE: <one line — the specific hook this book leads with>\n"
        "BRIEF:\n"
        "<8-14 lines: target reader, why now, competing titles, what makes this "
        "one different, and the honest commercial risk>"
        + avoid
    )

    if not brief:
        # Never silently downgrade to the weaker model without saying so.
        stages.clear_stage("hermes")
        fallback = _local_plan(job)
        fallback["research_engine"] = "local planner"
        fallback["claude_unavailable"] = note
        return fallback

    kdp_mode = _marker(brief, "MODE", "auto").lower()
    if kdp_mode not in {"fiction", "nonfiction"}:
        kdp_mode = "auto"
    region = _marker(brief, "REGION", "global").lower()
    angle = _marker(brief, "ANGLE")

    output_dir = _home() / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job['id']}.md"
    output_path.write_text(
        f"# HERMES — KDP Commissioning Brief\n\n"
        f"Request: {task}\n\nResearched by: {os.environ.get('ONE_RESEARCH_MODEL', 'claude-haiku-4-5')}\n\n"
        f"{brief}\n",
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
        "research_engine": os.environ.get("ONE_RESEARCH_MODEL", "claude-haiku-4-5"),
        "kdp_mode": kdp_mode,
        "region": region,
        "angle": angle,
        "content": brief,
        "output": str(output_path),
        "vault_note": remembered.get("path"),
        "prior_titles_considered": len(already),
    }

    # Commissioning the book is the DEFAULT. Telling a floor head to do its job
    # shouldn't require remembering which verb the router happens to map to
    # "execute" — any dispatch that reaches HERMES runs the whole pipeline.
    # Research-only is the explicit exception, asked for in plain words.
    research_only = bool(re.search(r"\b(plan|draft|prepare|research)\b", task.lower()))
    if research_only:
        stages.clear_stage("hermes")
        result["handed_to"] = None
        result["note"] = (
            "Research only — nothing handed to SCRIBE, because the request asked "
            "to plan/draft/research. Say it without those words (e.g. 'HERMES, "
            "get the next book done') to commission it for real."
        )
        return result

    # --- the handoff ------------------------------------------------------
    # HERMES leaves its desk and walks the brief across the floor. These two
    # stages are short by nature; the building animates the walk between them.
    # head_briefs_worker (stages.py) owns the CARRYING_TO_WORKER/BRIEFING/
    # RECEIVING/AWAITING_WORKER choreography -- see its docstring for why
    # this can't just be a bare set_stage/sleep/enqueue sequence per floor.
    worker = stages.head_briefs_worker(
        "hermes", "scribe",
        carrying_detail=f"Taking the brief to SCRIBE: {angle[:60]}",
        briefing_detail=f"SCRIBE, build this one: {angle[:110]}",
        awaiting_detail="Waiting on SCRIBE to produce the manuscript",
        enqueue=lambda: enqueue_job(
            "scribe",
            json.dumps({"brief_path": str(output_path), "kdp_mode": kdp_mode,
                        "region": region, "angle": angle, "origin_job": job["id"]}),
            mode="execute",
            tier="fast",
        ),
    )

    result["handed_to"] = {"agent": "SCRIBE", "job_id": worker["id"]}
    result["note"] = (
        "Brief handed to SCRIBE, who will run LAO's KDP Book Factory to "
        "completion and hand the finished book back. Uploading to Amazon KDP "
        "remains a manual human step."
    )
    return result


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
            "Phase 1 only (text scripts). Actual video generation + Instagram "
            "auto-post (Phase 2) and YouTube Shorts upload (Phase 3) are "
            "separate builds, not implemented yet -- see the PEITHO plan doc."
        ),
        task=f"book delivered: {title}",
        tags=["kdp", "publishing", "marketing", "reel-scripts"],
    )

    stages.clear_stage("peitho")

    return {
        "agent": "PEITHO",
        "mode": job.get("mode"),
        "title": title,
        "run_dir": run_dir,
        "kdp_packet_path": kdp_packet_path,
        "reel_scripts": reel_scripts,
        "content": f"Wrote {generated_count}/4 reel hook scripts for “{title}”.",
        "vault_note": remembered.get("path"),
        "note": "Phase 1 (text scripts) done. Video generation/posting is Phase 2/3, not built yet.",
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


def _generate_peitho_reel_scripts(run_dir: str, title: str) -> dict[str, Any]:
    """Four short-form video hook scripts, cut from the finished book's own
    outline -- one Claude call per angle, not one call for all four.

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

    angles: list[dict[str, Any]] = []
    for i, entry_point in enumerate(_PEITHO_ANGLE_ENTRY_POINTS, start=1):
        prompt = (
            f"You are PEITHO, writing a short-form video (Instagram Reel / "
            f"YouTube Short) hook script to sell the finished book \"{title}\", "
            f"genre {genre}, tropes {tropes}.\n\n"
            f"Premise: {premise}\n\nFull chapter outline:\n{outline_text}\n\n"
            f"For THIS script: {entry_point}\n\n"
            "Ground every beat in specific named characters/events from the "
            "outline above -- never generic teaser language. The whole point "
            "is a viewer feels they NEED to know what happens next and only "
            "the book tells them. Never reveal how the story actually ends.\n\n"
            "Reply in exactly this shape:\n"
            "HOOK:\n<one line, the first 1-2 seconds on screen -- a pattern-"
            "interrupt, not a scene-setter>\n"
            "BEATS:\n<4-6 short lines, one beat per line, building tension in "
            "order>\n"
            "CLIFFHANGER:\n<one line, the cut -- ends mid-tension, not "
            "resolved>\n"
            "CAPTION:\n<1-2 sentence social caption>\n"
            "HASHTAGS:\n<7 hashtags, one per line, no # repeated across "
            "generic filler like #book #reading -- specific to this story's "
            "genre/tropes>\n"
            "CTA:\n<one line telling the viewer how to find the book>"
        )
        content, note = _claude_research(prompt, max_tokens=700)
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
    packet, note = _claude_research(
        "You are SCRIBE, producing the exact fields a human will paste into "
        "Amazon KDP's Kindle eBook setup wizard for a finished manuscript. "
        "There is no KDP API -- this packet is what gets typed in by hand.\n\n"
        f"Title: {title}\nMode: {kdp_mode}\nRegion: {region}\nAngle: {angle}\n\n"
        "Ground every field in what actually sells on KDP right now, not "
        "generic advice. Reply in exactly this shape:\n"
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
        "ROYALTY_PLAN: 70 | 35\n"
    )
    if not packet:
        return {"generated": False, "note": note, "path": ""}

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
    return {"generated": True, "content": packet, "path": str(packet_path)}


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
        input_args["topicOverride"] = angle

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
                    lao_job=lao_job_id)
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
                lao_job=lao_job_id)
            if status in terminal:
                break
        else:
            raise RuntimeError(
                f"LAO KDP job did not finish within {max_wait/3600:.1f}h (last status: {status})"
            )

        if status != "Successful":
            raise RuntimeError(f"LAO KDP job ended as {status}")

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

    # KDP has no upload/metadata API (confirmed 2026-08-26) and the real
    # submit stays a manual human step -- see _generate_kdp_packet's
    # docstring for why. This is SCRIBE's actual deliverable for that step:
    # every field a human needs, pre-written, ready to paste.
    kdp_packet = _generate_kdp_packet(title, kdp_mode, region, angle, run_dir)

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

    # --- hold here; do NOT hand off to PEITHO yet --------------------------
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
    stages.set_stage(
        "scribe", stages.AWAITING_UPLOAD,
        f"“{title}” is ready — KDP packet done. Upload it, then mark it uploaded.",
    )
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
        "kdp_packet": kdp_packet,
        "requires_human": "Amazon KDP upload -- mark it uploaded from the dashboard to hand off to PEITHO",
        "_await_human_upload": True,
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


def _run_ares(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 3 - Growth & Distribution. Pending LAO integration."""
    return _local_plan(job)


def _run_alfa(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 2 - Commerce & Monetization. Pending LAO integration."""
    return _local_plan(job)


def _run_poseidon(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 1 - Corporate Services. Pending LAO integration."""
    return _local_plan(job)


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

    if mode == "report":
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
    brand, question = floors_bridge.route_media(task, job)
    if question:
        return {"agent": "IRIS", "mode": mode, "content": question,
                "handed_to": None,
                "note": "Nothing dispatched - the brand was unclear."}
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

    brief, note = _claude_research(
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
        "Reply in exactly this shape:\n"
        "PRIORITY: <one line — what this run should optimise for>\n"
        "REGION: <the zone you'd prefer if it were free, or 'rotation'>\n"
        "ANGLE: <one line — the editorial through-line to aim for>\n"
        "BRIEF:\n"
        "<6-12 lines: who the audience is, why run now, what would make this "
        "one perform, and the honest risk that it underperforms>"
        + avoid
    )

    if not brief:
        stages.clear_stage("ia")
        fallback = _local_plan(job)
        fallback["research_engine"] = "local planner"
        fallback["claude_unavailable"] = note
        return fallback

    # "location" here is IRIS's editorial priority, NOT the place to shoot --
    # the manifest rotation owns that. Named `priority` so nothing downstream
    # mistakes it for a location the pipeline would honour.
    priority = _marker(brief, "PRIORITY")
    region = _marker(brief, "REGION", "rotation").lower()
    angle = _marker(brief, "ANGLE")

    output_dir = _home() / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job['id']}.md"
    output_path.write_text(
        f"# IRIS — ImagineIndia Reel Brief\n\n"
        f"Request: {task}\n\nResearched by: {os.environ.get('ONE_RESEARCH_MODEL', 'claude-haiku-4-5')}\n\n"
        f"{brief}\n",
        encoding="utf-8",
    )

    remembered = memory.remember(
        agent="IRIS", floor_id="4", floor_name="Media & Content (ImagineIndia)",
        kind="Reel Brief", body=brief, task=task,
        tags=["imagineindia", "media", "reel"],
    )

    result: dict[str, Any] = {
        "agent": "IRIS",
        "mode": mode,
        "research_engine": os.environ.get("ONE_RESEARCH_MODEL", "claude-haiku-4-5"),
        "priority": priority,
        "region": region,
        "angle": angle,
        "content": brief,
        "output": str(output_path),
        "vault_note": remembered.get("path"),
        "prior_reels_considered": len(already),
    }

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

    # --- the handoff ------------------------------------------------------
    # head_briefs_worker (stages.py) owns the CARRYING_TO_WORKER/BRIEFING/
    # RECEIVING/AWAITING_WORKER choreography -- see its docstring for why
    # this can't just be a bare set_stage/sleep/enqueue sequence per floor.
    worker = stages.head_briefs_worker(
        "ia", "muse",
        carrying_detail=f"Taking the brief to MUSE: {(priority or angle)[:60]}",
        briefing_detail=f"MUSE, run the next reel: {(priority or angle)[:110]}",
        awaiting_detail="Waiting on MUSE to produce the reel",
        enqueue=lambda: enqueue_job(
            "muse",
            json.dumps({"brief_path": str(output_path), "priority": priority,
                        "region": region, "angle": angle, "origin_job": job["id"]}),
            mode="execute",
            tier="fast",
        ),
    )

    result["handed_to"] = {"agent": "MUSE", "job_id": worker["id"]}
    result["note"] = (
        "Brief handed to MUSE, who will run LAO's ImagineIndia reel pipeline "
        "to completion and hand the finished reel back."
    )
    return result


def _iris_report(job: dict[str, Any]) -> dict[str, Any]:
    """Third leg: MUSE has delivered, IRIS reports the result upward."""
    stages.set_stage("ia", stages.REPORTING, "Reporting the finished reel")
    try:
        payload = json.loads(str(job.get("task") or "{}"))
    except json.JSONDecodeError:
        payload = {}

    run_dir = payload.get("run_dir") or "(not reported by LAO)"
    title = payload.get("title") or "(details in the run folder)"
    published = bool(payload.get("published"))

    message = (
        f"Sir, the reel is finished. MUSE has handed it over.\n\n"
        f"Reel: {title}\n"
        f"Location: {run_dir}\n\n"
        + ("It has been published to Instagram by the pipeline."
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
        kind="Delivery Report",
        body=f"{message}\n\nANGLE: {title}\n",
        tags=["imagineindia", "media", "reel", "delivered"],
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


def _iris_report_brand(job: dict[str, Any], brand: dict[str, Any]) -> dict[str, Any]:
    """Third leg for a Floor 4 brand that is not ImagineIndia.

    Same shape as _iris_report, but every brand-specific detail comes from the
    brand record instead of being hardcoded: the vault folder, the tags, and
    the wording. Keeping this separate leaves the ImagineIndia report exactly
    as it was rather than making one function serve two voices badly.
    """
    stages.set_stage("ia", stages.REPORTING,
                     f"Reporting the finished {brand.get('display_name', brand['slug'])} post")
    try:
        payload = json.loads(str(job.get("task") or "{}"))
    except json.JSONDecodeError:
        payload = {}

    display = brand.get("display_name", brand["slug"])
    worker = str(payload.get("worker") or brand["worker_agent_id"]).upper()
    title = payload.get("title") or "(details in the plan)"
    fmt = payload.get("format") or "post"
    output = payload.get("output") or "(not reported)"
    published = bool(payload.get("published"))
    blocked = payload.get("publish_blocked_reason") or ""

    message = (
        f"Sir, the {display} {fmt} is ready. {worker} has handed it over.\n\n"
        f"Angle: {title}\n"
        f"Plan: {output}\n\n"
        + ("It has been published." if published else
           f"It is not published. {blocked}".strip())
    )

    output_dir = _home() / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job['id']}.md"
    output_path.write_text(f"# IRIS — Delivery Report ({display})\n\n{message}\n", encoding="utf-8")

    remembered = memory.remember(
        agent="IRIS", floor_id="4", floor_name=brand["vault_floor_name"],
        kind="Delivery Report",
        body=f"{message}\n\nANGLE: {title}\n",
        tags=[brand["slug"], "media", str(fmt).lower(), "delivered"],
    )

    time.sleep(2.0)
    stages.clear_stage("ia")
    return {
        "agent": "IRIS",
        "mode": "report",
        "brand": brand["slug"],
        "content": message,
        "title": title,
        "format": fmt,
        "published": published,
        "output": str(output_path),
        "vault_note": remembered.get("path"),
    }


def _run_muse(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 4 worker - runs LAO's ImagineIndia pipeline and waits for the reel.

    Same shape as _run_scribe on Floor 5: this blocks on a long external LAO
    job and polls it, so the floor genuinely shows the worker busy for as long
    as the reel actually takes.
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

    stages.worker_confirms_receipt(
        "muse",
        f"Got it — {headline[:110]}" if headline else "Taking the brief from IRIS",
    )

    tool = LaoOrchestratorTool()
    process_name = os.environ.get("LAO_IA_PROCESS", IA_PROCESS_NAME)

    stages.set_stage("muse", stages.EXECUTING,
                     f"Starting the reel: {headline[:110]}" if headline
                     else "Starting LAO ImagineIndia pipeline")

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
    # A restart while this was polling leaves the LAO id on the job row. When
    # it is there, re-attach to that run instead of starting a second one --
    # the poll loop below is the same either way.
    resume_id = job_recovery.resume_target(job)
    if resume_id:
        lao_job_id = resume_id
        stages.set_stage(
            "muse", stages.EXECUTING,
            f"Picking the reel back up — LAO job {resume_id[:8]} after a restart",
            lao_job=resume_id)
    else:
        started = tool.execute(
            action="start", mode="dry_run", process_name=process_name,
            scope="production",
            input_args={},
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
                lao_job=lao_job_id)
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
        stages.set_stage(
            "muse", stages.EXECUTING,
            (f"Shooting “{headline[:70]}” · LAO {status} · {elapsed}m" if headline
             else f"LAO job {status} · {elapsed}m"),
            lao_job=lao_job_id)
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
    reel = out.get("reel") or out.get("meta_publish") or {}
    run_dir = str(reel.get("run_dir") or reel.get("output_dir") or "")
    title = str(reel.get("title") or reel.get("location") or headline or "")
    published = bool(reel.get("published") or reel.get("permalink"))

    if not title:
        # LAO said Successful but told us nothing identifiable -- report the
        # job id rather than walking a phantom reel across the floor.
        title = f"ImagineIndia reel (LAO job {lao_job_id[:8]})"

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
        body=(f"Ran LAO's ImagineIndia reel pipeline to completion.\n\n"
              f"- LAO job: `{lao_job_id}` — {status}\n"
              f"- Output folder: `{run_dir or '(not reported)'}`\n"
              f"- Reel: {title}\n\n"
              "Handed the finished reel to IRIS."),
        task=f"{priority or 'rotation pick'} / {region}",
        tags=["imagineindia", "media", "reel", "production"],
    )

    enqueue_job(
        "ia",
        json.dumps({"run_dir": run_dir, "title": title,
                    "published": published, "lao_job": lao_job_id}),
        mode="report", tier="fast",
    )
    stages.clear_stage("muse")

    return {
        "agent": "MUSE",
        "mode": job.get("mode"),
        "lao_job": lao_job_id,
        "status": status,
        "run_dir": run_dir,
        "title": title,
        "published": published,
        "content": f"Reel finished: {title}",
        "handed_to": {"agent": "IRIS"},
    }


def _iris_dispatch_brand(job: dict[str, Any], brand: dict[str, Any]) -> dict[str, Any]:
    """Hand a non-ImagineIndia Floor 4 brand to that brand's own worker.

    Deliberately a separate path from the ImagineIndia flow in _run_iris: that
    flow is live and produces real reels, so it is left exactly as it was.

    IRIS coordinates here rather than producing. It does not run its own
    research call for this brand -- the worker does that once, which is the
    whole point of having a worker -- so a post costs one model call, not two.
    """
    task = str(job.get("task") or "")
    mode = str(job.get("mode") or "plan").strip().lower()
    worker_id = brand["worker_agent_id"]
    display = brand.get("display_name", brand["slug"])

    # stages.set_stage() keeps one record per agent_id, so a second concurrent
    # flow would overwrite this head's own worker_job pointer and make the
    # first flow invisible in the building. Decline with a reason instead.
    busy = floors_bridge.media_head_busy("ia")
    if busy:
        detail = str(busy.get("detail") or "").strip()
        return {
            "agent": "IRIS", "mode": mode, "handed_to": None,
            "content": (
                f"I'm already mid-flow on the other brand ({busy.get('stage')}"
                + (f" - {detail}" if detail else "")
                + f"). Ask me again for {display} once that one lands; running "
                "both at once would hide one of them."
            ),
            "note": "Declined to start a second Floor 4 flow.",
        }

    stages.set_stage("ia", stages.RESEARCHING,
                     task.strip()[:180] or f"Choosing the next {display} post")

    # Per-brand history, never the floor's. Reading ImagineIndia's titles here
    # would make IRIS refuse an angle this channel has never published.
    prior = memory.prior_titles("4", brand["vault_floor_name"])

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
    worker = stages.head_briefs_worker(
        "ia", worker_id,
        carrying_detail=f"Taking the {display} brief to {worker_id.upper()}",
        briefing_detail=f"{worker_id.upper()}, next {display} post: {task.strip()[:110]}",
        awaiting_detail=f"Waiting on {worker_id.upper()} to produce the {display} post",
        enqueue=lambda: enqueue_job(
            worker_id,
            json.dumps({"brand": brand["slug"], "angle": task.strip(),
                        "priority": "", "prior_angles": prior[:15],
                        "origin_job": job["id"]}),
            mode="execute",
            tier="fast",
        ),
    )

    return {
        "agent": "IRIS",
        "mode": mode,
        "brand": brand["slug"],
        "content": f"Briefed {worker_id.upper()} on the next {display} post.",
        "prior_posts_considered": len(prior),
        "handed_to": {"agent": worker_id.upper(), "job_id": worker["id"]},
        "note": (
            f"{worker_id.upper()} will produce the plan and hand it back. "
            "Nothing is published: that needs the channel registered in the "
            "vault and OLYMPUS sign-off."
        ),
    }


def _run_kairos(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 4 worker for aibyvineet. Its logic lives in one-company/floors.

    If that tree is unavailable this degrades to the local planner rather than
    failing the job, so this repository still runs on its own.
    """
    kairos = floors_bridge.load("floor_04_media", "kairos_agent")
    if kairos is None:
        return _local_plan(job)
    return kairos.run(
        job,
        kairos.Ports(
            research=_claude_research,
            remember=memory.remember,
            set_stage=stages.set_stage,
            clear_stage=stages.clear_stage,
            enqueue=enqueue_job,
            output_dir=_home() / "agent_outputs",
        ),
    )


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
        "A KDP manuscript is not reviewed by ARGUS or AEGIS and never enters "
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

    repeat = floors_bridge.claim_once(f"job:{job_id}", event_type="job.execute")
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

    handlers = {
        "zeus": _run_zeus,
        "athena": _run_athena,
        "jobhunt": _run_daedalus,
        "titan": _run_titan,
        "beta": _run_beta,
        "apollo": _run_apollo,
        "hermes": _run_hermes,
        "scribe": _run_scribe,
        "peitho": _run_peitho,
        "ia": _run_iris,
        "muse": _run_muse,
        "kairos": _run_kairos,
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
        floors_bridge.audit(agent_id=job.get("agent_id", ""),
                            floor_id=str(job.get("floor_id") or "1"),
                            job_id=job.get("id", ""), correlation_id=job.get("id", ""),
                            action=job.get("mode") or "execute",
                            approval_level="A0", status="failed",
                            result=type(exc).__name__)
        raise
    floors_bridge.audit(agent_id=job.get("agent_id", ""),
                        floor_id=str(job.get("floor_id") or "1"),
                        job_id=job.get("id", ""), correlation_id=job.get("id", ""),
                        action=job.get("mode") or "execute",
                        approval_level="A0", status="succeeded",
                        cost=result.get("cost_usd") if isinstance(result, dict) else None)
    return result


def _job_watchdog_seconds(job: dict[str, Any] | None = None) -> float:
    """Outer, additive safety-net timeout for a *whole* job run.

    SCRIBE is the one agent that legitimately blocks for hours — it sits on
    LAO's KDP factory until the book exists. The default 45-minute net would
    mark a perfectly healthy book run as failed partway through, so that agent
    gets a window sized to its own LAO wait plus margin. Every other agent
    keeps the short net.

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

    if job and job.get("agent_id") == "scribe":
        try:
            lao_wait = float(os.environ.get("ONE_LAO_MAX_WAIT_SECONDS", "10800"))
        except ValueError:
            lao_wait = 10800.0
        return max(default, lao_wait + 600.0)   # LAO's own wait plus 10 min
    return default


def run_worker(poll_seconds: float = 2.0) -> None:
    import threading

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

    last_schedule_check = 0.0
    while True:
        if time.time() - last_schedule_check >= 30:
            _enqueue_due_recurring_jobs()
            last_schedule_check = time.time()
        job = claim_job()
        if not job:
            time.sleep(poll_seconds)
            continue

        outcome: dict[str, Any] = {}

        def _target() -> None:
            try:
                outcome["result"] = execute_job(job)
            except Exception as exc:  # noqa: BLE001 - surfaced via outcome
                outcome["error"] = exc

        worker_thread = threading.Thread(
            target=_target, name=f"job-{job['id']}", daemon=True
        )
        worker_thread.start()
        worker_thread.join(timeout=_job_watchdog_seconds(job))

        if worker_thread.is_alive():
            # The job is still running past the outer watchdog window.
            # We cannot forcibly kill a Python thread, so it keeps running
            # in the background (and will simply be ignored when/if it
            # eventually finishes), but the queue row itself is freed up
            # immediately so the dashboard stops showing a permanently
            # frozen RUNNING card and the worker loop can keep picking up
            # other queued jobs.
            fail_job(
                job["id"],
                TimeoutError(
                    f"Job exceeded watchdog timeout of {_job_watchdog_seconds(job):.0f}s "
                    "and was marked failed so it would not stay stuck forever. "
                    "The underlying step may still finish in the background; "
                    "re-run the task if needed."
                ),
            )
            continue

        if "error" in outcome:
            fail_job(job["id"], outcome["error"])
        else:
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
            if result.pop("_await_human_upload", False):
                gated = floors_bridge.needs_approval(
                    job.get("agent_id", ""), "publish_to_store")
                if gated is False:
                    finish_job(job["id"], result)
                else:
                    mark_awaiting_upload(job["id"], result)
            else:
                finish_job(job["id"], result)
