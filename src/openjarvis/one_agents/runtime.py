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

from openjarvis.one_agents import memory, stages


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
    "ia": {"name": "IRIS", "role": "Media and content production/distribution operator across ImagineIndia and future brands", "floor_id": "4", "floor_name": "Media & Content (ImagineIndia)", "division": "media"},
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
    mode = mode.strip().lower()
    if mode not in {"plan", "execute", "publish"}:
        raise ValueError("Mode must be plan, execute, or publish")
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
    stages.set_stage("hermes", stages.CARRYING_TO_WORKER,
                     f"Taking the brief to SCRIBE: {angle[:60]}")
    time.sleep(float(os.environ.get("ONE_HANDOFF_SECONDS", "6")))
    stages.set_stage("hermes", stages.BRIEFING,
                     f"SCRIBE, build this one: {angle[:110]}")
    time.sleep(float(os.environ.get("ONE_BRIEFING_SECONDS", "8")))

    worker = enqueue_job(
        "scribe",
        json.dumps({"brief_path": str(output_path), "kdp_mode": kdp_mode,
                    "region": region, "angle": angle, "origin_job": job["id"]}),
        mode="execute",
        tier="fast",
    )

    # HERMES is now blocked on the worker — back at its desk, not idle.
    stages.set_stage("hermes", stages.AWAITING_WORKER,
                     "Waiting on SCRIBE to produce the manuscript",
                     worker_job=worker["id"])

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


def _run_scribe(job: dict[str, Any]) -> dict[str, Any]:
    """Floor 5 worker - runs LAO's KDP factory and waits for the book.

    This is the only agent that blocks on an external multi-hour job, so it
    polls LAO rather than fire-and-forgetting: the floor's whole point is that
    the worker is genuinely busy for as long as the book takes.
    """
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool

    try:
        brief = json.loads(str(job.get("task") or "{}"))
    except json.JSONDecodeError:
        brief = {}
    kdp_mode = brief.get("kdp_mode") or "auto"
    region = brief.get("region") or "global"
    angle = str(brief.get("angle") or "").strip()

    stages.set_stage("scribe", stages.RECEIVING,
                     f"Got it — {angle[:110]}" if angle
                     else "Taking the brief from HERMES")
    time.sleep(float(os.environ.get("ONE_BRIEFING_SECONDS", "8")))

    tool = LaoOrchestratorTool()
    process_name = os.environ.get("LAO_KDP_PROCESS", KDP_PROCESS_NAME)

    # dryRun stays True: it still produces the full manuscript + images, and
    # KDP upload is a manual human gate that must never be automated.
    stages.set_stage("scribe", stages.EXECUTING,
                     f"Starting the book: {angle[:110]}" if angle
                     else "Starting LAO KDP Book Factory")
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

    started = tool.execute(
        action="start", mode="dry_run", process_name=process_name,
        scope="production",
        input_args=input_args,
    )
    if not started.success:
        stages.clear_stage("scribe")
        stages.clear_stage("hermes")
        raise RuntimeError(f"LAO refused the KDP run: {started.content}")
    try:
        start_payload = json.loads(started.content)
    except json.JSONDecodeError:
        start_payload = {"raw": started.content}
    lao_job_id = ((start_payload.get("job") or {}).get("id")) or ""

    # --- wait for the book ------------------------------------------------
    poll_seconds = float(os.environ.get("ONE_LAO_POLL_SECONDS", "30"))
    max_wait = float(os.environ.get("ONE_LAO_MAX_WAIT_SECONDS", "10800"))  # 3h
    deadline = time.time() + max_wait
    terminal = {"Successful", "Failed", "Stopped", "Cancelled", "Faulted"}
    status = "Pending"
    last: dict[str, Any] = {}

    while time.time() < deadline:
        time.sleep(poll_seconds)
        probe = tool.execute(action="status", process_name=process_name,
                             scope="production", job_id=lao_job_id)
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
        stages.clear_stage("scribe")
        stages.clear_stage("hermes")
        raise RuntimeError(
            f"LAO KDP job did not finish within {max_wait/3600:.1f}h (last status: {status})"
        )

    if status != "Successful":
        stages.clear_stage("scribe")
        stages.clear_stage("hermes")
        raise RuntimeError(f"LAO KDP job ended as {status}")

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
            stages.clear_stage("scribe")
            stages.clear_stage("hermes")
            raise

    # --- walk the finished book back to the floor head --------------------
    stages.set_stage("scribe", stages.CARRYING_TO_HEAD, f"Delivering: {title}")
    time.sleep(float(os.environ.get("ONE_HANDOFF_SECONDS", "6")))
    stages.set_stage("scribe", stages.DELIVERING,
                     f"It's done — “{title}” is finished.")
    time.sleep(float(os.environ.get("ONE_BRIEFING_SECONDS", "8")))

    # Both of them mark the moment. HERMES has been blocked on this since the
    # briefing, so it drops AWAITING_WORKER and celebrates alongside SCRIBE.
    celebration = f"“{title}” shipped! 🎉"
    stages.set_stage("scribe", stages.CELEBRATING, celebration)
    stages.set_stage("hermes", stages.CELEBRATING, celebration)
    time.sleep(float(os.environ.get("ONE_CELEBRATE_SECONDS", "9")))

    memory.remember(
        agent="SCRIBE", floor_id="5", floor_name="Book Publishing (KDP)",
        kind="Production Run",
        body=(f"Ran LAO's KDP Book Factory to completion.\n\n"
              f"- LAO job: `{lao_job_id}` — {status}\n"
              f"- Output folder: `{run_dir}`\n"
              f"- Title: {title}\n\n"
              "Handed the finished book to HERMES."),
        task=f"{kdp_mode} / {region}",
        tags=["kdp", "publishing", "production"],
    )

    enqueue_job(
        "hermes",
        json.dumps({"run_dir": run_dir, "title": title, "lao_job": lao_job_id}),
        mode="report", tier="fast",
    )
    stages.clear_stage("scribe")

    return {
        "agent": "SCRIBE",
        "mode": job.get("mode"),
        "lao_job": lao_job_id,
        "lao_status": status,
        "run_dir": run_dir,
        "title": title,
        "delivered_to": "HERMES",
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
    """Floor 4 - Media & Content (ImagineIndia). Pending LAO integration.

    The old body of this function (as _run_ia) ran the real IAAgent
    image -> Leonardo video -> ffmpeg merge pipeline directly. Retired for
    now, same reasoning as _run_hephaistos above.
    """
    return _local_plan(job)


def execute_job(job: dict[str, Any]) -> dict[str, Any]:
    handlers = {
        "zeus": _run_zeus,
        "athena": _run_athena,
        "jobhunt": _run_daedalus,
        "titan": _run_titan,
        "beta": _run_beta,
        "apollo": _run_apollo,
        "hermes": _run_hermes,
        "scribe": _run_scribe,
        "ia": _run_iris,
        "ares": _run_ares,
        "alfa": _run_alfa,
        "poseidon": _run_poseidon,
        "hephaistos": _run_hephaistos,
        "argus": _run_argus,
    }
    handler = handlers.get(job["agent_id"], _local_plan)
    return handler(job)


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
            finish_job(job["id"], outcome.get("result", {}))
