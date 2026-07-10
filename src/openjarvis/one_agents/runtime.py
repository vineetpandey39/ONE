"""Durable, local-first runtime for ONE's named agents."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


AGENTS: dict[str, dict[str, str]] = {
    "titan": {"name": "TITAN", "role": "Instagram and PostForge operator"},
    "alfa": {"name": "ALFA", "role": "Recurring revenue opportunity and service lead scout"},
    "jobhunt": {"name": "JOBHUNT", "role": "Approval-gated QA/Product job search copilot"},
    "beta": {"name": "BETA", "role": "Freelance opportunity and delivery operator"},
    "hermes": {"name": "HERMES", "role": "KDP research and publishing operator"},
    "ares": {"name": "ARES", "role": "LinkedIn B2B content and leads operator"},
    "apollo": {"name": "APOLLO", "role": "X threads and growth operator"},
    "athena": {"name": "ATHENA", "role": "Research and intelligence operator"},
    "hephaistos": {"name": "HEPHAISTOS", "role": "LAO and local automation bot operator"},
    "poseidon": {"name": "POSEIDON", "role": "Revenue and payout control operator"},
    "zeus": {"name": "ZEUS", "role": "Agent orchestration and escalation operator"},
    "ia": {"name": "IA", "role": "Restoration-reel content operator"},
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
    if os.environ.get("ALFA_AUTOSCOUT", "true").lower() in {"1", "true", "yes", "on"}:
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


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    with _connect() as db:
        rows = db.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 100)),)
        ).fetchall()
    return [dict(row) for row in rows]


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


def _run_beta(job: dict[str, Any]) -> dict[str, Any]:
    """Build a durable delivery workspace for an approved paid engagement."""
    planned = _local_plan(job)
    workspace = _home() / "delivery" / job["id"]
    workspace.mkdir(parents=True, exist_ok=True)
    plan = workspace / "delivery-plan.md"
    qa = workspace / "qa-checklist.md"
    handoff = workspace / "client-handoff.md"
    plan.write_text(
        "# BETA Delivery Plan\n\n" + planned["content"] + "\n\n"
        "Status: WORKSPACE READY. This does not mean the client deliverable has been sent.\n",
        encoding="utf-8",
    )
    qa.write_text(
        "# QA Checklist\n\n- [ ] Scope matches the approved proposal\n- [ ] Real inputs tested\n"
        "- [ ] Edge cases tested\n- [ ] Credentials removed from deliverables\n"
        "- [ ] Client instructions written\n- [ ] Vineet approved final delivery\n",
        encoding="utf-8",
    )
    handoff.write_text(
        "# Client Handoff Draft\n\n## Delivered items\n- Add final files/links\n\n"
        "## How to use\n- Add instructions\n\n## Support\n- Confirm revision window and optional monthly care plan\n",
        encoding="utf-8",
    )
    return {
        "agent": "BETA",
        "mode": "delivery-workspace",
        "workspace": str(workspace),
        "plan": str(plan),
        "qa_checklist": str(qa),
        "handoff": str(handoff),
    }


def _run_hephaistos(job: dict[str, Any]) -> dict[str, Any]:
    """Route ONE voice/text commands into LAO's deterministic bot runtime."""
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool

    task = str(job.get("task") or "")
    text = task.lower()
    mode = str(job.get("mode") or "plan").lower()

    action = "start"
    include_logs = False
    publish_negated = bool(
        any(
            phrase in text
            for phrase in (
                "publish mat",
                "post mat",
                "publish nahi",
                "publish nahin",
                "post nahi",
                "post nahin",
                "publish na",
                "post na",
                "without publish",
                "without posting",
                "do not publish",
                "do not post",
                "don't publish",
                "dont publish",
                "don't post",
                "dont post",
            )
        )
    )
    dry_requested = publish_negated or any(
        word in text for word in ("dry", "dry run", "test", "preview", "without publish", "publish mat")
    )
    publish_requested = (mode == "publish") or any(
        phrase in text for phrase in ("publish", "post kar", "post karo", "shoot", "live run", "go live")
    )

    if any(word in text for word in ("status", "progress", "result", "kya chal", "logs", "log bata")):
        action = "status"
        include_logs = "log" in text
    elif any(word in text for word in ("stop", "cancel", "rok", "band karo")):
        action = "stop"
    elif any(word in text for word in ("list process", "process list", "processes")):
        action = "list_processes"

    run_mode = "publish" if (publish_requested and not publish_negated) else "dry_run"

    # "start" is the only real, side-effecting action here — unlike TITAN/IA,
    # which stay side-effect-free in job mode "plan", this used to start a
    # live LAO job (in dry_run flavor) regardless of mode, so ambiguous
    # phrasing dispatched with mode="plan" silently ran a real LAO job every
    # time instead of just describing intent. Gated the same way TITAN/IA
    # already are: only take the real action on execute/publish.
    if action == "start" and mode not in {"execute", "publish"}:
        return {
            "agent": "HEPHAISTOS",
            "mode": "lao-operator-plan",
            "command": task,
            "content": (
                f"Plan only — no LAO job started. Would run the LinkedIn posting "
                f"process in '{run_mode}' mode. Say 'execute' to run it as a dry "
                f"run, or 'publish' to actually post."
            ),
        }

    result = LaoOrchestratorTool().execute(
        action=action,
        mode=run_mode,
        include_logs=include_logs,
        confirm_publish=(run_mode == "publish"),
    )
    try:
        lao_payload = json.loads(result.content)
    except json.JSONDecodeError:
        lao_payload = {"raw": result.content}
    if not result.success:
        raise RuntimeError(result.content)
    return {
        "agent": "HEPHAISTOS",
        "mode": "lao-operator",
        "command": task,
        "lao_action": action,
        "lao_mode": run_mode,
        "lao": lao_payload,
    }


def _postforge(path: str, payload: dict[str, Any], timeout: float = 300) -> dict[str, Any]:
    base = os.environ.get("POSTFORGE_URL", "https://postforge-ai-one.vercel.app").rstrip("/")
    secret = os.environ.get("POSTFORGE_API_SECRET", "").strip()
    if not secret:
        raise RuntimeError("POSTFORGE_API_SECRET is missing from one.env")
    response = httpx.post(
        base + path,
        headers={"Content-Type": "application/json", "x-postforge-secret": secret},
        json=payload,
        timeout=timeout,
    )
    text = response.text
    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(f"PostForge returned non-JSON ({response.status_code}): {text[:300]}") from exc
    if response.is_error or data.get("error"):
        raise RuntimeError(data.get("error") or f"PostForge failed with {response.status_code}")
    return data


def _run_titan(job: dict[str, Any]) -> dict[str, Any]:
    pillar = os.environ.get("TITAN_DEFAULT_PILLAR", "news")
    pillar_names = {
        "news": "AI News Breakdown",
        "tool": "AI Tool Drop",
        "income": "AI Income Update",
        "transformation": "AI Transformation",
        "automation": "AI Automation Win",
    }
    refresh = _postforge("/api/refresh", {"pillar": pillar, "pillarFull": pillar_names[pillar]})
    items = refresh.get("items") or []
    if not items:
        raise RuntimeError("TITAN found no verified source")
    items.sort(key=lambda item: item.get("publishedAt") or item.get("date") or "", reverse=True)
    selected = items[0]
    generated = _postforge(
        "/api/generate",
        {"selectedItems": [selected], "pillarFull": pillar_names[pillar], "pillarId": pillar, "format": "Carousel"},
    )
    result: dict[str, Any] = {
        "agent": "TITAN",
        "mode": job["mode"],
        "source": selected,
        "hook": generated.get("hook", ""),
        "caption": generated.get("caption", ""),
    }
    if job["mode"] == "execute":
        return result

    image_urls: list[str] = []
    image_meta: list[dict[str, Any]] = []
    for index in range(6):
        images = _postforge(
            "/api/carousel-images",
            {
                "hook": generated.get("hook"),
                "cover_text": generated.get("cover_text"),
                "cover_subtext": generated.get("cover_subtext"),
                "cover_visual_prompt": generated.get("cover_visual_prompt"),
                "slides": generated.get("slides"),
                "pillarId": pillar,
                "onlyIndex": index,
            },
        )
        for image in images.get("images") or []:
            image_meta.append(image)
            if image.get("success") and image.get("imageUrl"):
                image_urls.append(image["imageUrl"])
    if len(image_urls) < 2:
        raise RuntimeError(f"TITAN created only {len(image_urls)} public image URL(s)")
    instagram = _postforge(
        "/api/instagram",
        {
            "imageUrls": image_urls,
            "caption": generated.get("caption", ""),
            "cta": generated.get("cta", ""),
            "hashtags": generated.get("hashtags", ""),
        },
    )
    result.update({"images": image_meta, "imageUrls": image_urls, "instagram": instagram})
    return result


def _run_ia(job: dict[str, Any]) -> dict[str, Any]:
    """Run the real restoration-reel pipeline end-to-end: image_generate ->
    leonardo_video_generate -> video_merge, via the deterministic
    IAAgent (not the generic Ollama planner). The agent itself
    mirrors its own progress into the managed-agent dashboard record
    (see ``agents/ia_dashboard.py``); this just bridges the ONE
    Cockpit job queue to that same run.
    """
    from pathlib import Path

    from openjarvis.agents.ia import IAAgent
    from openjarvis.tools.image_tool import ImageGenerateTool
    from openjarvis.tools.leonardo_browser_video_tool import LeonardoBrowserVideoGenerateTool
    from openjarvis.tools.leonardo_video_tool import LeonardoVideoGenerateTool
    from openjarvis.tools.video_merge_tool import VideoMergeTool
    from openjarvis.tools.video_tool import VideoGenerateTool

    # Backend preference. "browser" (Leonardo web app, subscription credits)
    # would be cheapest, but its profile directory exists as soon as the
    # login script has ever been run -- not proof a *valid* session is saved
    # -- so an expired/incomplete login silently fails every clip instead of
    # falling back. Until that profile is confirmed working again, prefer
    # "fal" (fal.ai's wan-flf2v, real start/end-frame interpolation, no
    # browser/login needed) whenever FAL_KEY is configured; "browser" is
    # opt-in via LEONARDO_VIDEO_BACKEND=browser once login is verified, and
    # "api" (pay-as-you-go REST) is the last-resort fallback either way.
    forced_backend = os.environ.get("LEONARDO_VIDEO_BACKEND")
    profile_dir = os.environ.get("LEONARDO_CHROME_PROFILE_DIR") or str(
        Path.home() / ".openjarvis" / "leonardo_browser_profile"
    )
    if forced_backend in {"browser", "fal", "api"}:
        video_backend = forced_backend
    elif os.environ.get("FAL_KEY"):
        video_backend = "fal"
    elif Path(profile_dir).exists():
        video_backend = "browser"
    else:
        video_backend = "api"

    agent = IAAgent(
        engine=None,
        model="",
        tools=[
            ImageGenerateTool(),
            LeonardoVideoGenerateTool(),
            LeonardoBrowserVideoGenerateTool(),
            VideoGenerateTool(),
            VideoMergeTool(),
        ],
        video_backend=video_backend,
    )
    result = agent.run(job["task"])
    final_path = result.metadata.get("final_path")
    if not final_path:
        # The agent never raises on internal step failures -- it returns an
        # AgentResult with the failure described in .content/.metadata so the
        # dashboard bridge can log it. Surface that here as a real exception
        # so the cockpit job queue marks this run "failed" instead of
        # "completed" with a buried error.
        raise RuntimeError(result.content)
    return {
        "agent": "IA",
        "mode": job["mode"],
        "content": result.content,
        "run_dir": result.metadata.get("run_dir"),
        "final_path": final_path,
        "location": result.metadata.get("location"),
    }


def execute_job(job: dict[str, Any]) -> dict[str, Any]:
    if job["agent_id"] == "titan" and job["mode"] in {"execute", "publish"}:
        return _run_titan(job)
    if job["agent_id"] == "ia" and job["mode"] in {"execute", "publish"}:
        return _run_ia(job)
    if job["agent_id"] == "alfa":
        from openjarvis.one_agents.alfa import run_alfa_scan

        return run_alfa_scan()
    if job["agent_id"] == "jobhunt":
        from openjarvis.one_agents.jobhunt import run_jobhunt_scan

        return run_jobhunt_scan()
    if job["agent_id"] == "beta":
        return _run_beta(job)
    if job["agent_id"] == "hephaistos":
        return _run_hephaistos(job)
    return _local_plan(job)


def _job_watchdog_seconds() -> float:
    """Outer, additive safety-net timeout for a *whole* job run.

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
        return max(60.0, float(os.environ.get("ONE_JOB_WATCHDOG_SECONDS", "2700")))
    except ValueError:
        return 2700.0


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
        worker_thread.join(timeout=_job_watchdog_seconds())

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
                    f"Job exceeded watchdog timeout of {_job_watchdog_seconds():.0f}s "
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
