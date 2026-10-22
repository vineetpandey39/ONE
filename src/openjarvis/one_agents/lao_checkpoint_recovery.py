"""Bounded LAO engine deployment and durable failed-preproduction recovery.

Never creates a fresh process or replays paid narration. Unknown retry outcomes
remain pending for reconciliation rather than issuing a second POST.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

ENGINE_REPO = Path(r"C:\Users\pc\Documents\LAO\chatgpt-stream-repair")
WORKER_ROOT = Path(r"C:\Users\pc\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\local-agent-mode-sessions\cb3dc5b9-a76c-45ff-bbcf-b330fe30c84a\21738b93-8e02-4c20-a83c-0abb35d85c72\local_374e1c90-a56c-4744-840b-8f0118a3547a\outputs\lao-platform\robot-worker")


def client():
    from openjarvis.tools.lao_orchestrator import _LaoClient, DEFAULT_LAO_BASE_URL
    result = _LaoClient(os.environ.get("LAO_BASE_URL", DEFAULT_LAO_BASE_URL),
                        os.environ.get("LAO_EMAIL", "admin@example.com"),
                        os.environ.get("LAO_PASSWORD", "ChangeMe123!"), 30)
    result.login()
    return result


def checkpoint_of(job):
    checkpoint = (job.get("output_result") or {}).get("__resume_checkpoint__")
    if not isinstance(checkpoint, dict):
        raise RuntimeError("LAO recovery requires an existing saved checkpoint; fresh start forbidden")
    if not isinstance(checkpoint.get("step_index"), int) or checkpoint["step_index"] < 1:
        raise RuntimeError("LAO checkpoint has no safe completed step")
    variables = checkpoint.get("vars") or {}
    if not variables.get("yatra_script_response") or not variables.get("yatra_packaging_response"):
        raise RuntimeError("Saved YATRA script/packaging missing; refuse regeneration")
    return checkpoint


def evidence_for(external_job):
    job = client().get(f"/jobs/{external_job}")
    checkpoint = checkpoint_of(job)
    # Never expose credential variables or complete input_args to a model.
    return {"lao_error": str(job.get("error_message") or "")[:4000],
            "lao_status": job.get("status"),
            "resume_step": checkpoint["step_index"],
            "saved_script_present": True,
            "conversation_url": (checkpoint.get("browser_context") or {}).get("conversation_url", "")}


def activate_engine(*, revision: str = ""):
    """Deploy a committed engine only onto a known ancestor, atomically.

    Agent bootstrap is installed/reloaded by safe maintenance once. Subsequent
    jobs import the new engine at the job boundary, without global restarts.
    """
    source = ENGINE_REPO / "workflow_engine.py"
    target = WORKER_ROOT / "workflow_engine.py"
    bootstrap = (WORKER_ROOT / "agent.py").read_text(encoding="utf-8")
    if "importlib.reload(engine_module).WorkflowEngine" not in bootstrap:
        raise RuntimeError("LAO job-boundary loader not deployed; safe maintenance required")
    if revision:
        resolved = subprocess.run(
            ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"], cwd=ENGINE_REPO,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ENGINE_REPO,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", head, resolved], cwd=ENGINE_REPO,
            capture_output=True,
        )
        if ancestor.returncode:
            raise RuntimeError("Reviewed engine repair is not based on the current repository HEAD")
        expected = subprocess.run(
            ["git", "show", f"{resolved}:workflow_engine.py"], cwd=ENGINE_REPO,
            capture_output=True, check=True,
        ).stdout
        source_label = f"{resolved}:workflow_engine.py"
    else:
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                                cwd=ENGINE_REPO, capture_output=True, text=True, check=True)
        if status.stdout.strip():
            raise RuntimeError("LAO engine has uncommitted changes; deployment refused")
        expected = source.read_bytes()
        source_label = str(source)
    compile(expected, source_label, "exec")
    current = target.read_bytes()
    if current == expected:
        return hashlib.sha256(expected).hexdigest()
    revisions = subprocess.run(["git", "log", "--all", "--format=%H", "--", "workflow_engine.py"],
                               cwd=ENGINE_REPO, capture_output=True, text=True, check=True).stdout.splitlines()
    known = any(subprocess.run(["git", "show", f"{rev}:workflow_engine.py"],
                              cwd=ENGINE_REPO, capture_output=True, check=True).stdout.replace(b"\r\n", b"\n")
                == current.replace(b"\r\n", b"\n") for rev in revisions)
    if not known:
        raise RuntimeError("Live LAO engine diverged from reviewed history; refuse overwrite")
    backup = target.with_name("workflow_engine.backup-" + hashlib.sha256(current).hexdigest()[:16] + ".py")
    if not backup.exists():
        backup.write_bytes(current)
    fd, temporary = tempfile.mkstemp(prefix="engine-deploy-", suffix=".py", dir=WORKER_ROOT)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return hashlib.sha256(target.read_bytes()).hexdigest()


def resume_failed(connect, previous, *, reviewed_conversation_url="", resume_user_stopped=False):
    """Retry the existing LAO checkpoint once and attach ONE to its successor."""
    from openjarvis.one_agents.floor_watch import _enqueue_collection
    payload = json.loads(previous.get("task") or "{}")
    if payload.get("stage") == "narration":
        raise RuntimeError("This recovery path cannot regenerate narration")
    external = str(previous.get("external_job") or "")
    if not external:
        raise RuntimeError("No external checkpoint to resume")
    api = client()
    parent = api.get(f"/jobs/{external}")
    checkpoint = checkpoint_of(parent)
    if reviewed_conversation_url and not re.fullmatch(r"https://chatgpt\.com/c/[A-Za-z0-9_-]{8,}", reviewed_conversation_url):
        raise RuntimeError("Reviewed recovery URL must identify a ChatGPT conversation")
    root = Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis")) / "lao_recovery"
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(external.encode()).hexdigest()
    receipt = root / (key + ".json")
    lock = root / (key + ".lock")
    if not receipt.exists():
        allowed_terminal = {"Failed", "Stopped"} if resume_user_stopped else {"Failed"}
        if parent.get("status") not in allowed_terminal:
            raise RuntimeError("External job is not failed; refuse duplicate retry")
        active = [j for j in api.list_jobs("production")
                  if j.get("process_id") == parent.get("process_id")
                  and j.get("status") in {"Pending", "Assigned", "Running"}]
        if active:
            raise RuntimeError("LAO production already active; recovery deferred")
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except FileExistsError:
            raise RuntimeError("Earlier LAO retry outcome needs reconciliation; no duplicate POST")
        if reviewed_conversation_url:
            # Legacy checkpoints predate browser provenance. A human-reviewed
            # exact conversation may enrich it, never change saved vars/step.
            enriched = {**checkpoint, "browser_context": {
                **(checkpoint.get("browser_context") or {}),
                "conversation_url": reviewed_conversation_url}}
            inputs = {**(parent.get("input_args") or {}), "__resume_checkpoint__": enriched}
            successor = api.post("/jobs", {"process_id": parent["process_id"], "input_args": inputs})
        else:
            successor = api.post(f"/jobs/{external}/retry", {})
        successor_id = successor.get("id")
        if not successor_id or successor_id == external:
            raise RuntimeError("LAO retry returned no distinct successor; reconciliation required")
        receipt.write_text(json.dumps({"parent": external, "successor": successor_id}), encoding="utf-8")
    successor_id = json.loads(receipt.read_text(encoding="utf-8"))["successor"]
    with connect() as db:
        existing = db.execute("SELECT id FROM jobs WHERE external_job=? AND id!=? LIMIT 1",
                              (successor_id, previous["id"])).fetchone()
    if existing:
        return f"saved LAO successor already attached to {existing['id']}"
    return _enqueue_collection(connect, previous["id"], successor_id)
