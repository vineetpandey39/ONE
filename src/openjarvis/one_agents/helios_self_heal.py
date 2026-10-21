"""Bounded self-healing for Floor 12 (YouTube Studio).

HELIOS is allowed to repair its own implementation, but it is not allowed to
turn a production retry into a second production.  This module therefore keeps
the two decisions separate:

* resume only checkpoint-safe workers (YATRA visuals, LYRA, VISTA and ECHO);
* edit code only in a clean, allow-listed Git repository, run the repository's
  Floor 12 tests, then create a local commit (never push).

Codex is primary, followed by Claude Code. Qwen Code is then run against the
installed local Ollama Qwen model (not the unauthenticated Qwen cloud CLI
default), followed by native Ollama tool calls if Qwen Code emits pseudo-calls.
NVIDIA Nemotron is the final remote fallback, with its key resolved from LAO.
A model failure is a diagnostic failure, not permission to bypass the gates.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


Connect = Callable[[], sqlite3.Connection]
# These workers own durable checkpoints and can safely receive a new queue row
# after a verified repair. PLANEXIUM's ProductionContext resumes the unfinished
# mission and verifies each accepted artifact instead of starting a second film.
SAFE_RETRY_AGENTS = {"lyra", "vista", "echo", "planexium"}
FLOOR12_AGENTS = {"helios", "fabula", "yatra", "lyra", "vista", "echo", "planexium", "chandan"}
REPO_ROOT = Path(__file__).resolve().parents[3]
VISTA_REPO = Path(r"C:\Users\pc\Documents\LAO\vista")
YATRA_CAPTURE_REPO = Path(r"C:\Users\pc\Documents\LAO\yatra-capture")
ALLOWED_REPOS = (REPO_ROOT, VISTA_REPO, YATRA_CAPTURE_REPO)
from openjarvis.one_agents.lao_checkpoint_recovery import ENGINE_REPO
ALLOWED_REPOS = (*ALLOWED_REPOS, ENGINE_REPO)
PENDING_PREFIX = "pending self-heal: "
REPAIR_CIRCUIT_MAX_FAILURES = 2
# These files are the independent checker/maker and self-heal control plane.
# A production failure may be repaired by that control plane, but a model CLI
# must never rewrite the rules that supervise or authorize its own repair.
# Human-reviewed commits can still change them; this boundary applies only to
# autonomous HELIOS patches and is deliberately unrelated to the restart gate.
PROTECTED_CONTROL_PLANE_PATHS = {
    "src/openjarvis/one_agents/lao_checkpoint_recovery.py",
    "src/openjarvis/one_agents/floor_watch.py",
    "src/openjarvis/one_agents/helios_self_heal.py",
}


def _audit_attempt(payload: dict[str, Any]) -> None:
    """Persist the reason each CLI advanced or failed without storing prompts."""
    try:
        path = Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis")) / "helios_self_heal_log.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": _now(), **payload}, ensure_ascii=True) + "\n")
    except OSError:
        pass


def _attempt_reason(attempts: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for attempt in attempts:
        name = str(attempt.get("cli") or "cli")
        if attempt.get("error"):
            detail = str(attempt["error"])
        else:
            detail = f"exit {attempt.get('returncode')}"
            tail = " ".join(str(attempt.get("output") or "").split())[-240:]
            if tail:
                detail += f": {tail}"
        parts.append(f"{name} {detail}")
    return " | ".join(parts)[:1200]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repair_signature(evidence: dict[str, Any]) -> str:
    """Identify one stable failure without persisting its potentially sensitive evidence."""
    material = "\n".join((
        str(evidence.get("agent") or "").casefold().strip(),
        str(evidence.get("job_id") or "").strip(),
        str(evidence.get("error") or evidence.get("summary") or "").casefold().strip(),
    ))
    return hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()


def _repair_circuit_path(evidence: dict[str, Any]) -> Path:
    home = Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))
    key = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"{evidence.get('job_id') or 'unknown'}:{_repair_signature(evidence)}",
    )
    return home / "helios_repair_circuits" / f"{key}.json"


def _load_repair_circuit(evidence: dict[str, Any]) -> dict[str, Any]:
    path = _repair_circuit_path(evidence)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if saved.get("signature") != _repair_signature(evidence):
        return {}
    return saved


def _circuit_limit() -> int:
    try:
        return max(1, int(os.environ.get(
            "ONE_HELIOS_REPAIR_MAX_FAILED_ROUNDS",
            str(REPAIR_CIRCUIT_MAX_FAILURES),
        )))
    except ValueError:
        return REPAIR_CIRCUIT_MAX_FAILURES


def _repair_circuit_is_open(evidence: dict[str, Any]) -> bool:
    return int(_load_repair_circuit(evidence).get("failed_rounds") or 0) >= _circuit_limit()


def _record_repair_failure(evidence: dict[str, Any], reason: str) -> dict[str, Any]:
    """Atomically count a full unsuccessful model round; never store prompts or outputs."""
    path = _repair_circuit_path(evidence)
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = _load_repair_circuit(evidence)
    failed_rounds = int(saved.get("failed_rounds") or 0) + 1
    reason_kind = str(reason or "repair round failed").split(":", 1)[0][:160]
    record = {
        "job_id": str(evidence.get("job_id") or ""),
        "signature": _repair_signature(evidence),
        "failed_rounds": failed_rounds,
        "limit": _circuit_limit(),
        "reason": reason_kind,
        "updated_at": _now(),
        "status": "open" if failed_rounds >= _circuit_limit() else "retryable",
    }
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    _audit_attempt({
        "job_id": evidence.get("job_id"),
        "event": "repair_circuit_updated",
        "failed_rounds": failed_rounds,
        "limit": _circuit_limit(),
        "status": record["status"],
    })
    return record


def _clear_repair_circuit(evidence: dict[str, Any]) -> None:
    path = _repair_circuit_path(evidence)
    try:
        path.unlink()
    except FileNotFoundError:
        return
    _audit_attempt({"job_id": evidence.get("job_id"), "event": "repair_circuit_closed"})


def _which_cli(name: str) -> str | None:
    """Resolve CLIs even when ONE was started by a task with a short PATH."""
    found = shutil.which(name)
    if found:
        return found
    if name == "qwen":
        owner = os.environ.get("ONE_OWNER_PROFILE") or os.environ.get("USERPROFILE", "")
        appdata = os.environ.get("APPDATA", "")
        candidates = [Path(appdata) / "npm" / "qwen.cmd"] if appdata else []
        if owner:
            candidates.append(Path(owner) / "AppData" / "Roaming" / "npm" / "qwen.cmd")
        return next((str(path) for path in candidates if path.is_file()), None)
    if name != "codex":
        return None
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_app_data:
        return None
    root = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
    candidates = list(root.glob("*/*codex*.exe")) + list(root.glob("*/codex.exe"))
    candidates = [item for item in candidates if item.is_file()]
    if not candidates:
        return None
    return str(max(candidates, key=lambda item: item.stat().st_mtime))


def _repo_is_vault_locked(repo: Path) -> bool:
    """Honor VISTA's scoped safeguard without blocking any other repository."""
    if repo.resolve() != VISTA_REPO.resolve():
        return False
    git_dir = repo / ".git"
    return ((git_dir / "vista-lock-manifest.json").is_file()
            and not (git_dir / "vista-unlocked.json").is_file())


def _active_vista_job() -> str:
    """Return an active VISTA id; a live production must never be unlocked under it."""
    try:
        from openjarvis.one_agents import runtime
        with closing(runtime._connect()) as db:
            row = db.execute(
                "SELECT id FROM jobs WHERE agent_id = 'vista' "
                "AND status IN ('queued','running','awaiting_upload') "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return str(row["id"]) if row else ""
    except Exception:
        # Failure to prove the lane idle is a denial, not permission.
        return "unknown"


def _vista_lock_script(name: str) -> subprocess.CompletedProcess[str]:
    """Run VISTA's own vault workflow without putting the credential in argv/logs."""
    python = os.environ.get("ONE_HELIOS_PYTHON", sys.executable)
    lock_dir = VISTA_REPO / ".vista-lock"
    if name == "unlock.py":
        # The child resolves the encrypted vault value and feeds it directly to
        # the official password comparison. It is never copied into ONE's
        # process, environment, command line, receipt or audit trail.
        command = [
            python, "-c",
            "import getpass,runpy; from common import vault_password; "
            "getpass.getpass=lambda prompt='': vault_password(); "
            "runpy.run_path('unlock.py', run_name='__main__')",
        ]
    else:
        command = [python, name]
    return subprocess.run(
        command, cwd=lock_dir, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )


def _unlock_vista_for_verified_promotion(evidence: dict[str, Any]) -> dict[str, Any]:
    """Momentarily unlock only an idle VISTA after a patch has passed tests."""
    active = _active_vista_job()
    if active:
        return {"ok": False, "reason": f"VISTA production lane is not idle ({active})"}
    done = _vista_lock_script("unlock.py")
    ok = done.returncode == 0 and not _repo_is_vault_locked(VISTA_REPO)
    _audit_attempt({
        "job_id": evidence.get("job_id"), "event": "vista_vault_unlock",
        "ok": ok, "returncode": done.returncode,
    })
    return {"ok": ok, "reason": "" if ok else "official VISTA vault unlock failed"}


def _relock_vista_after_promotion(evidence: dict[str, Any]) -> dict[str, Any]:
    """Always restore VISTA's manifest, tag, pre-commit hook and read-only files."""
    done = _vista_lock_script("lock.py")
    ok = done.returncode == 0 and _repo_is_vault_locked(VISTA_REPO)
    _audit_attempt({
        "job_id": evidence.get("job_id"), "event": "vista_vault_relock",
        "ok": ok, "returncode": done.returncode,
    })
    return {"ok": ok, "reason": "" if ok else "official VISTA relock failed"}


def _row(connect: Connect, job_id: str) -> dict[str, Any] | None:
    with closing(connect()) as db:
        item = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(item) if item else None


def _active_for_agent(connect: Connect, agent_id: str, excluding: str) -> str:
    with closing(connect()) as db:
        row = db.execute(
            "SELECT id FROM jobs WHERE agent_id = ? AND id != ? "
            "AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
            (agent_id, excluding),
        ).fetchone()
    return str(row["id"]) if row else ""


def _queue_copy(connect: Connect, previous: dict[str, Any], *, task: str | None = None) -> str:
    agent = str(previous.get("agent_id") or "").lower()
    new_id = f"{agent}-{uuid.uuid4().hex[:12]}"
    with closing(connect()) as db, db:
        db.execute(
            "INSERT INTO jobs (id, agent_id, task, mode, status, created_at, updated_at, "
            "tier, external_job, external_kind) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)",
            (new_id, agent, task if task is not None else previous.get("task") or "",
             previous.get("mode") or "execute", _now(), _now(), previous.get("tier") or "fast",
             previous.get("external_job") or "", previous.get("external_kind") or ""),
        )
    return new_id


def _downstream_for(connect: Connect, origin_job: str) -> str:
    """Return a child that proves this head already commissioned its worker."""
    with closing(connect()) as db:
        rows = db.execute(
            "SELECT id, task FROM jobs WHERE agent_id IN ('fabula','yatra','vista','lyra','echo') "
            "AND status IN ('queued','running','completed','awaiting_upload') "
            "ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    for row in rows:
        try:
            payload = json.loads(str(row["task"] or "{}"))
        except (TypeError, ValueError):
            continue
        if str(payload.get("origin_job") or "") == origin_job:
            return str(row["id"])
    return ""


def resume_checkpoint(connect: Connect, job_id: str) -> str:
    """Queue one checkpoint-safe retry of a failed Floor 12 job."""
    previous = _row(connect, job_id)
    if not previous or previous.get("status") != "failed":
        return ""
    agent = str(previous.get("agent_id") or "").lower()
    if agent not in FLOOR12_AGENTS:
        return ""
    active = _active_for_agent(connect, agent, job_id)
    if active:
        return f"resume deferred; {agent} already has active job {active}"

    if agent == "yatra":
        try:
            payload = json.loads(str(previous.get("task") or "{}"))
        except (TypeError, ValueError):
            return ""
        if payload.get("stage") != "visuals":
            return ""  # never repeat discovery/script/paid voice work
        from openjarvis.one_agents import runtime
        queued = runtime.resume_yatra_visual_job(job_id)
        return f"queued checkpoint-safe YATRA visual resume {queued['id']}"

    if agent == "helios":
        child = _downstream_for(connect, job_id)
        if child:
            return f"HELIOS retry not needed; downstream checkpoint {child} already exists"
        new_id = _queue_copy(connect, previous)
        return f"queued HELIOS resume {new_id} before any duplicate worker handoff"

    if agent == "fabula":
        # FABULA owns two materially different stages.  A preproduction
        # contract failure happens before narration and can safely reattach to
        # the same successful LAO checkpoint.  Treating that like a failed
        # paid narration left complete ChatGPT drafts stranded even when the
        # parser had just been repaired.
        try:
            payload = json.loads(str(previous.get("task") or "{}"))
        except (TypeError, ValueError):
            payload = {}
        error = str(previous.get("error") or "").casefold()
        before_voice = (
            payload.get("stage") != "narration"
            and bool(previous.get("external_job"))
            and ("narration was not started" in error or "no voice credits were spent" in error)
        )
        if before_voice:
            new_id = _queue_copy(connect, previous)
            return f"queued FABULA preproduction checkpoint resume {new_id} (no voice was spent)"

        # A finished receipt means voice credits were already spent and the
        # only missing action is the YATRA handoff. Never call FABULA again.
        try:
            yatra_active = _active_for_agent(connect, "yatra", job_id)
            if yatra_active:
                return f"FABULA receipt handoff deferred; YATRA already has active job {yatra_active}"
            from openjarvis.one_agents import runtime
            _, _, folder, checkpoint = runtime._travel_checkpoint(payload)
            receipt = runtime._YATRA_ASSET_ROOT / folder / "narration" / "fabula-receipt.json"
            envelope = json.loads(receipt.read_text(encoding="utf-8"))
            narration = envelope.get("narration") or {}
            if (str(envelope.get("checkpoint") or "") != checkpoint
                    or narration.get("ok") is not True):
                return ""
            task = json.dumps({**payload, "stage": "visuals", "narration_job": job_id,
                               "narration_receipt": str(receipt)})
            synthetic = {**previous, "agent_id": "yatra", "mode": "execute"}
            new_id = _queue_copy(connect, synthetic, task=task)
            return f"reused paid FABULA receipt and queued YATRA visual checkpoint {new_id}"
        except Exception:  # no complete receipt means no safe paid retry
            return ""

    if agent not in SAFE_RETRY_AGENTS:
        return ""  # HELIOS discovery and FABULA voice are not blind-retry safe

    new_id = _queue_copy(connect, previous)
    return f"queued checkpoint retry {new_id}"


def _git(repo: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _repo_for(evidence: dict[str, Any]) -> Path | None:
    def values(value: Any) -> list[str]:
        if isinstance(value, dict):
            return [part for item in value.values() for part in values(item)]
        if isinstance(value, (list, tuple, set)):
            return [part for item in value for part in values(item)]
        return [str(value)]

    # Do not search json.dumps(): JSON doubles Windows backslashes, so a real
    # `C:\path` could never match its repository path and every worker failure
    # silently fell back to ONE-Suite.
    text = "\n".join(values(evidence)).casefold().replace("/", "\\")
    if (str(evidence.get("agent") or "").casefold() == "fabula"
            and evidence.get("external_job")
            and any(message in str(evidence.get("lao_error") or "").casefold()
                    for message in ("chatgpt", "composer", "conversation", "streaming"))):
        return ENGINE_REPO
    # The contract validator lives in ONE, but it dynamically loads the OBS
    # parser from yatra-capture.  Its traceback therefore ends in runtime.py
    # and used to send every model into the wrong repository with no parser or
    # saved plan to inspect.
    if (str(evidence.get("agent") or "").casefold() == "fabula"
            and "obs capture plan" in text
            and YATRA_CAPTURE_REPO.is_dir()):
        return YATRA_CAPTURE_REPO
    # A traceback normally starts in ONE's runtime wrapper and ends in the
    # worker repository that actually raised.  Returning the first match made
    # every VISTA failure look like an ONE-Suite failure.  The final/deepest
    # matching repository owns the repair.
    matches = [repo for repo in ALLOWED_REPOS
               if repo.is_dir() and str(repo).casefold() in text]
    if matches:
        return max(matches, key=lambda repo: text.rfind(str(repo).casefold()))
    # Runtime/queue failures belong to ONE-Suite even when the traceback was
    # shortened before it reached the watcher.
    return REPO_ROOT if REPO_ROOT.is_dir() else None


def _cli_commands(prompt: str, repo: Path) -> list[tuple[str, list[str]]]:
    commands: list[tuple[str, list[str]]] = []
    claude = _which_cli("claude")
    if claude:
        # allowedTools is variadic in current Claude Code. When the prompt sat
        # after it, Claude parsed the traceback as another tool rule and then
        # reported that --print had no prompt. Put the positional prompt first.
        commands.append(("claude", [claude, prompt, "--print", "--permission-mode", "acceptEdits",
                                     "--allowedTools", "Read,Glob,Grep,Edit,Write,Bash"]))
    codex = _which_cli("codex")
    if codex:
        # Current Codex makes --approve-for-me and an explicit --sandbox
        # mutually exclusive; approve-for-me already selects workspace-write.
        # The owner's global config may select a ChatGPT app model that the
        # CLI account does not expose. Pin HELIOS to a model in the installed
        # Codex CLI catalog so one stale desktop preference cannot disable
        # this fallback for every autonomous repair.
        codex_model = os.environ.get("ONE_HELIOS_CODEX_MODEL", "gpt-5.6-sol").strip() or "gpt-5.6-sol"
        commands.insert(0, ("codex", [codex, "exec", "--model", codex_model,
                                    "-c", 'model_reasoning_effort="high"',
                                    "--ephemeral", "--approve-for-me",
                                    "--cd", str(repo), prompt]))
    # Use the same direct Ollama model as Sanjeevani. Qwen Code added a second
    # Docker hop around that identical model, inherited unrelated desktop
    # credentials, and doubled the timeout without adding another fallback.
    local_model = os.environ.get("ONE_HELIOS_LOCAL_MODEL", "qwen3.5:9b").strip()
    if local_model:
        # This path needs no Qwen Code executable or cloud credential.
        commands.append(("qwen-local-tools", ["ollama-native", "-m", local_model, "-p", prompt]))
    # Direct OpenAI-compatible tool calling avoids depending on Qwen Code's
    # executable/profile for the final paid fallback. Credentials are resolved
    # only when this last-resort command actually runs.
    nemotron_model = os.environ.get("NEMOTRON_MODEL", "").strip()
    if nemotron_model:
        commands.append(("nemotron-native-tools", ["nvidia-native", "-m", nemotron_model, "-p", prompt]))
    return commands


def _qwen_settings(model: str, *, include_nemotron: bool = False) -> dict[str, Any]:
    """Build a disposable Qwen Code provider config; never persist credentials."""
    ollama = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    # Qwen's --sandbox runs inside Docker, where loopback points at the
    # container rather than the Windows host's Ollama service.
    ollama = ollama.replace("127.0.0.1", "host.docker.internal").replace("localhost", "host.docker.internal")
    ollama_base = ollama if ollama.endswith("/v1") else ollama + "/v1"
    providers: list[dict[str, Any]] = [{
        "id": os.environ.get("ONE_HELIOS_LOCAL_MODEL", "qwen3.5:9b").strip() or "qwen3.5:9b",
        "name": "Local Ollama Qwen",
        # Ollama exposes OpenAI Chat Completions (including native tool_calls).
        # Pin the wire protocol: Qwen Code's newer Responses route is not
        # implemented by Ollama, and a plain-text pseudo-tool reply can look
        # successful while no tool ever ran.
        "wireApi": "chat-completions",
        "baseUrl": ollama_base,
        "envKey": "OLLAMA_API_KEY",
        "generationConfig": {
            "timeout": 900000,
            "streamIdleTimeoutMs": 900000,
            "maxRetries": 0,
            "contextWindowSize": 32768,
            "samplingParams": {"temperature": 0.1, "max_tokens": 8192},
        },
    }]
    # The key is inherited only for the paid fallback attempt; it is never
    # written to the disposable Qwen configuration or logged.
    nemotron = os.environ.get("NEMOTRON_MODEL", "").strip()
    if include_nemotron and nemotron:
        providers.append({
            "id": nemotron,
            "name": "NVIDIA Nemotron fallback",
            "wireApi": "chat-completions",
            "baseUrl": os.environ.get("NVIDIA_HOST", "https://integrate.api.nvidia.com").rstrip("/") + "/v1",
            "envKey": "NVIDIA_API_KEY",
            "generationConfig": {
                "timeout": 900000,
                "streamIdleTimeoutMs": 900000,
                "maxRetries": 0,
                "contextWindowSize": 32768,
                "samplingParams": {"temperature": 0.1, "max_tokens": 8192},
            },
        })
    return {
        "security": {"auth": {"selectedType": "openai"}},
        "model": {"name": model},
        "modelProviders": {"openai": providers},
        # Ollama accepts a non-empty key on its local OpenAI-compatible route.
        "env": {"OLLAMA_API_KEY": "ollama"},
    }


def _resolve_nemotron_key() -> str:
    """Fetch NVIDIA credentials from LAO's production vault, in memory only."""
    from openjarvis.one_agents.runtime import _resolve_lao_secret

    return _resolve_lao_secret("nvidiaApiKey").strip()


def _qwen_tool_path(repo: Path, raw_path: Any) -> Path:
    """Resolve a Qwen file-tool path to an existing, allow-listed Python file."""
    relative = str(raw_path or "").replace("\\", "/")
    candidate = Path(relative)
    if not relative or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("path must be a safe repository-relative path")
    normalized = candidate.as_posix()
    if not normalized.endswith(".py") or not _allowed_patch_path(repo, normalized):
        raise ValueError("path is outside HELIOS's Python source/test allowlist")
    resolved = (repo / candidate).resolve()
    if not resolved.is_relative_to(repo.resolve()) or not resolved.is_file():
        raise ValueError("path must resolve to an existing file inside the repository")
    return resolved


def _qwen_tool_directory(repo: Path, raw_path: Any) -> Path:
    relative = str(raw_path or "").replace("\\", "/")
    candidate = Path(relative)
    if not relative or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("directory must be a safe repository-relative path")
    resolved = (repo / candidate).resolve()
    if not resolved.is_relative_to(repo.resolve()) or not resolved.is_dir():
        raise ValueError("directory must exist inside the repository")
    if not any((candidate / "__allowlist_probe__.py").as_posix().startswith(prefix)
               for prefix in ("src/openjarvis/one_agents/", "tests/one_agents/")):
        if repo.resolve() != ALLOWED_REPOS[1].resolve():
            raise ValueError("directory is outside HELIOS's source/test allowlist")
    return resolved


def _run_qwen_native_tools(command: list[str], *, repo: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    """Run local Qwen with Ollama-native tools; no shell or arbitrary commands."""
    model = command[command.index("-m") + 1]
    prompt = command[command.index("-p") + 1]
    base_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    url = base_url + "/api/chat"
    tools = [
        {"type": "function", "function": {"name": "list_files", "description": "List Python source/test files in an allow-listed folder.",
         "parameters": {"type": "object", "properties": {"relative_dir": {"type": "string"}}, "required": ["relative_dir"]}}},
        {"type": "function", "function": {"name": "read_file", "description": "Read one allow-listed Python source/test file.",
         "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
        {"type": "function", "function": {"name": "write_file", "description": "Replace the contents of one existing allow-listed Python file.",
         "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    ]
    system = (
        "You are HELIOS's local code-repair model. Diagnose the supplied failure. "
        "Use list_files/read_file/write_file tools to inspect and make the smallest fix. "
        "You may edit only existing allow-listed Python source/test files. Never claim an edit unless "
        "write_file was called. Do not run commands, access credentials, or touch production data. "
        "After edits, summarize the change; the host will run tests and decide whether to commit."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    output: list[str] = []
    write_count = 0
    deadline = time.monotonic() + timeout
    for _ in range(16):
        remaining = max(1, int(deadline - time.monotonic()))
        body = json.dumps({"model": model, "messages": messages, "tools": tools,
                           "stream": False, "options": {"temperature": 0.1, "num_ctx": 32768}}).encode()
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=remaining) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return subprocess.CompletedProcess(command, 1, "", f"Local Ollama Qwen request failed: {type(exc).__name__}")
        message = result.get("message") or {}
        messages.append(message)
        content = str(message.get("content") or "")
        if content:
            output.append(content)
        calls = message.get("tool_calls") or []
        if not calls:
            return subprocess.CompletedProcess(command, 0 if write_count else 1,
                                               "\n".join(output),
                                               "" if write_count else "Qwen returned no native tool calls or edits")
        for call in calls:
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            args = function.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            try:
                if name == "list_files":
                    folder = _qwen_tool_directory(repo, args.get("relative_dir"))
                    listed = sorted(item.relative_to(repo).as_posix() for item in folder.rglob("*.py")
                                    if item.is_file() and _allowed_patch_path(repo, item.relative_to(repo).as_posix()))[:100]
                    tool_result = "\n".join(listed)
                elif name in {"read_file", "write_file"}:
                    path = _qwen_tool_path(repo, args.get("path"))
                    if name == "read_file":
                        tool_result = path.read_text(encoding="utf-8")[:120000]
                    else:
                        new_content = str(args.get("content") or "")
                        if len(new_content) > 500000:
                            raise ValueError("file content exceeds repair limit")
                        path.write_text(new_content, encoding="utf-8")
                        write_count += 1
                        tool_result = f"Wrote {path.relative_to(repo).as_posix()}"
                else:
                    raise ValueError("tool not allow-listed")
            except (OSError, ValueError) as exc:
                tool_result = f"Tool rejected: {exc}"
            messages.append({"role": "tool", "tool_name": name, "content": tool_result})
    return subprocess.CompletedProcess(command, 1 if not write_count else 0,
                                       "\n".join(output), "Qwen exceeded native tool-call limit")


def _run_nemotron_native_tools(command: list[str], *, repo: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    """Last-resort NVIDIA chat-completions tool runner; key stays in memory."""
    model = command[command.index("-m") + 1]
    prompt = command[command.index("-p") + 1]
    host = os.environ.get("NVIDIA_HOST", "https://integrate.api.nvidia.com").rstrip("/")
    url = (host if host.endswith("/v1") else host + "/v1") + "/chat/completions"
    key = _resolve_nemotron_key()
    tools = [
        {"type": "function", "function": {"name": "list_files", "description": "List Python source/test files in an allow-listed folder.",
         "parameters": {"type": "object", "properties": {"relative_dir": {"type": "string"}}, "required": ["relative_dir"]}}},
        {"type": "function", "function": {"name": "read_file", "description": "Read one allow-listed Python source/test file.",
         "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
        {"type": "function", "function": {"name": "write_file", "description": "Replace the contents of one existing allow-listed Python file.",
         "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                        "required": ["path", "content"]}}},
    ]
    system = (
        "You are HELIOS's bounded code-repair model. Diagnose the supplied failure and use only "
        "list_files/read_file/write_file tools for the smallest fix. Never run commands, access "
        "credentials, or edit files outside the host-enforced allowlist. Never claim an edit unless "
        "write_file was called; the host will run tests and decide whether to commit."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    output: list[str] = []
    write_count = 0
    deadline = time.monotonic() + timeout
    for _ in range(16):
        remaining = max(1, int(deadline - time.monotonic()))
        body = json.dumps({
            "model": model,
            "messages": messages,
            "tools": tools,
            # Nemotron can otherwise return a prose diagnosis without touching
            # the repository. Require a real host-enforced tool call until one
            # allow-listed write has happened; only then may it summarize.
            "tool_choice": "required" if write_count == 0 else "auto",
            "stream": False,
            "temperature": 0.1,
            "max_tokens": 2048,
        }).encode()
        request = urllib.request.Request(url, data=body, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=remaining) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return subprocess.CompletedProcess(command, 1, "", f"Nemotron request failed: {type(exc).__name__}")
        choices = result.get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        raw_content = message.get("content")
        calls = message.get("tool_calls") or _nemotron_content_tool_calls(raw_content)
        if calls and not message.get("tool_calls"):
            # Some Nemotron turns serialize a tool request into content even
            # though the same endpoint normally returns OpenAI tool_calls.
            # Normalize it before adding the assistant turn so the following
            # role=tool message has a valid matching call id.
            message = {**message, "content": None, "tool_calls": calls}
        messages.append(message)
        content = str(raw_content or "")
        if content:
            output.append(content)
        if not calls:
            return subprocess.CompletedProcess(command, 0 if write_count else 1,
                                               "\n".join(output),
                                               "" if write_count else "Nemotron returned no native tool calls or edits")
        for call in calls:
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            args = function.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            try:
                if name == "list_files":
                    folder = _qwen_tool_directory(repo, args.get("relative_dir"))
                    listed = sorted(item.relative_to(repo).as_posix() for item in folder.rglob("*.py")
                                    if item.is_file() and _allowed_patch_path(repo, item.relative_to(repo).as_posix()))[:100]
                    tool_result = "\n".join(listed)
                elif name in {"read_file", "write_file"}:
                    path = _qwen_tool_path(repo, args.get("path"))
                    if name == "read_file":
                        tool_result = path.read_text(encoding="utf-8")[:120000]
                    else:
                        new_content = str(args.get("content") or "")
                        if len(new_content) > 500000:
                            raise ValueError("file content exceeds repair limit")
                        path.write_text(new_content, encoding="utf-8")
                        write_count += 1
                        tool_result = f"Wrote {path.relative_to(repo).as_posix()}"
                else:
                    raise ValueError("tool not allow-listed")
            except (OSError, ValueError) as exc:
                tool_result = f"Tool rejected: {exc}"
            messages.append({"role": "tool", "tool_call_id": str(call.get("id") or uuid.uuid4().hex),
                             "content": tool_result})
    return subprocess.CompletedProcess(command, 1 if not write_count else 0,
                                       "\n".join(output), "Nemotron exceeded native tool-call limit")


def _nemotron_content_tool_calls(content: Any) -> list[dict[str, Any]]:
    """Normalize Nemotron's occasional content-encoded function requests."""
    found: list[dict[str, Any]] = []

    def collect(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                collect(item)
            return
        if not isinstance(value, dict):
            return
        if isinstance(value.get("function"), dict):
            function = value["function"]
            name = str(function.get("name") or "")
            args = function.get("arguments") or function.get("parameters") or {}
        else:
            name = str(value.get("name") or "")
            args = value.get("arguments") or value.get("parameters") or {}
        if name:
            found.append({
                "id": str(value.get("id") or f"call-{uuid.uuid4().hex}"),
                "type": "function",
                "function": {"name": name, "arguments": args},
            })

    if isinstance(content, (dict, list)):
        collect(content)
        return found
    text = str(content or "")
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        collect(value)
        if found:
            break
    return found


def _run_cli(name: str, command: list[str], *, repo: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    """Run Qwen Code with a disposable isolated profile; other CLIs inherit env."""
    if name == "qwen-local-tools":
        return _run_qwen_native_tools(command, repo=repo, timeout=timeout)
    if name == "nemotron-native-tools":
        return _run_nemotron_native_tools(command, repo=repo, timeout=timeout)
    if name == "codex":
        env = os.environ.copy()
        # ONE isolates HOME for caches; Codex subscription authentication
        # belongs to the Windows owner, not that empty runtime profile.
        owner = env.get("ONE_OWNER_PROFILE") or env.get("USERPROFILE", "")
        if not env.get("CODEX_HOME") and owner:
            env["CODEX_HOME"] = str(Path(owner) / ".codex")
        # This route uses the owner's subscription, never an inherited API key.
        env.pop("OPENAI_API_KEY", None)
        return subprocess.run(command, cwd=repo, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if name not in {"qwen-local", "nemotron"}:
        return subprocess.run(command, cwd=repo, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    model = command[command.index("-m") + 1]
    with tempfile.TemporaryDirectory(prefix="helios-qwen-") as profile:
        profile_path = Path(profile)
        qwen_dir = profile_path / ".qwen"
        qwen_dir.mkdir()
        env = os.environ.copy()
        if name == "qwen-local":
            # This route is deliberately private/local. Qwen Code launches a
            # Docker child and forwards inherited variables, so leaving a
            # desktop cloud key in the environment both leaks it into the
            # child command line and can silently route away from Ollama.
            for key in (
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NVIDIA_API_KEY",
                "GEMINI_API_KEY", "GOOGLE_API_KEY", "DASHSCOPE_API_KEY",
            ):
                env.pop(key, None)
            env["OLLAMA_API_KEY"] = "ollama"
        if name == "nemotron":
            # The secret enters only this child process, never settings.json,
            # audit events, or the long-lived worker environment.
            env["NVIDIA_API_KEY"] = _resolve_nemotron_key()
        (qwen_dir / "settings.json").write_text(
            json.dumps(_qwen_settings(model, include_nemotron=name == "nemotron"),
                       ensure_ascii=True), encoding="utf-8"
        )
        # Node's os.homedir() on Windows uses USERPROFILE. Redirect Qwen
        # config/session writes to the disposable profile, not the user's.
        env["USERPROFILE"] = str(profile_path)
        env["HOME"] = str(profile_path)
        return subprocess.run(command, cwd=repo, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)


def _allowed_patch_path(repo: Path, path: str) -> bool:
    """Keep a CLI repair inside the selected Floor 12 codebase."""
    normalized = path.replace("\\", "/")
    lowered = normalized.casefold()
    if any(token in lowered for token in ("credential", "secret", "vault", ".env")):
        return False
    if repo.resolve() == REPO_ROOT.resolve():
        if normalized in PROTECTED_CONTROL_PLANE_PATHS:
            return False
        return normalized.startswith(("src/openjarvis/one_agents/", "tests/one_agents/"))
    if repo.resolve() in {VISTA_REPO.resolve(), YATRA_CAPTURE_REPO.resolve()}:
        return normalized.endswith(".py") and not normalized.startswith(("runs/", "direction-history/"))
    if repo.resolve() == ENGINE_REPO.resolve():
        return normalized == "workflow_engine.py" or ("/" not in normalized and normalized.startswith("test_") and normalized.endswith(".py"))
    return False


def _repair_test_command(repo: Path) -> list[str]:
    python = os.environ.get("ONE_HELIOS_PYTHON", sys.executable)
    if repo.resolve() == ENGINE_REPO.resolve():
        return [python, "-m", "unittest", "discover", "-v"]
    if repo.resolve() == REPO_ROOT.resolve():
        return [python, "-m", "pytest", "tests/one_agents", "-q", "--maxfail=1"]
    if repo.resolve() == YATRA_CAPTURE_REPO.resolve():
        return [python, "-m", "unittest", "-v", "test_plan_captures.py"]
    return [python, "-m", "pytest", "-q", "--maxfail=1"]


def _untracked_paths(repo: Path) -> set[str]:
    """Return untracked paths without treating existing operator tools as dirt.

    Production checkouts may contain local diagnostic scripts. They must not be
    swept into a repair commit, but their mere presence must not disable every
    future self-heal. New files created by a repair attempt are tracked
    separately and remain subject to the normal path boundary.
    """
    result = _git(repo, "ls-files", "--others", "--exclude-standard")
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines()
            if line.strip()} if result.returncode == 0 else set()


def _discard_attempt(repo: Path, names: list[str], original_untracked: set[str]) -> None:
    tracked = [name for name in names if name not in original_untracked and
               _git(repo, "ls-files", "--error-unmatch", "--", name).returncode == 0]
    if tracked:
        _git(repo, "restore", "--worktree", "--", *tracked)
    for name in names:
        if name in original_untracked:
            continue
        path = (repo / name).resolve()
        try:
            path.relative_to(repo.resolve())
        except ValueError:
            continue
        if path.is_file() and _git(repo, "ls-files", "--error-unmatch", "--", name).returncode:
            path.unlink()


@contextmanager
def _isolated_repair_workspace(source_repo: Path, evidence: dict[str, Any]):
    """Give repair models a disposable checkout, never the live agent checkout."""
    home = Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))
    root = (home / "helios_repair_worktrees").resolve()
    root.mkdir(parents=True, exist_ok=True)
    workspace = (root / f"repair-{uuid.uuid4().hex}").resolve()
    workspace.relative_to(root)
    head = _git(source_repo, "rev-parse", "HEAD")
    if head.returncode or not head.stdout.strip():
        raise RuntimeError("could not resolve source repository revision")
    revision = head.stdout.strip()
    added = _git(source_repo, "worktree", "add", "--detach", str(workspace), revision, timeout=300)
    if added.returncode:
        raise RuntimeError("could not create isolated repair worktree")
    _audit_attempt({"job_id": evidence.get("job_id"), "event": "repair_worktree_created",
                    "repo": str(source_repo), "revision": revision[:12]})
    try:
        yield workspace, revision
    finally:
        removed = _git(source_repo, "worktree", "remove", "--force", str(workspace), timeout=300)
        _git(source_repo, "worktree", "prune")
        _audit_attempt({"job_id": evidence.get("job_id"), "event": "repair_worktree_removed",
                        "ok": removed.returncode == 0})


def _promote_isolated_repair(source_repo: Path, original_revision: str,
                             repair_revision: str) -> subprocess.CompletedProcess[str]:
    """Fast-forward only when the live checkout is unchanged and tracked-clean."""
    status = _git(source_repo, "status", "--porcelain", "--untracked-files=no")
    head = _git(source_repo, "rev-parse", "HEAD")
    if (status.returncode or status.stdout.strip() or head.returncode
            or head.stdout.strip() != original_revision):
        return subprocess.CompletedProcess(
            ["git", "merge", "--ff-only", repair_revision], 1, "",
            "source repository changed while isolated repair was running",
        )
    return _git(source_repo, "merge", "--ff-only", repair_revision, timeout=300)


def _with_checkpoint_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Give a YATRA parser repair the saved plan shape, not only ONE's wrapper traceback."""
    enriched = dict(evidence)
    if (str(enriched.get("agent") or "").casefold() != "fabula"
            or not enriched.get("external_job")):
        return enriched
    try:
        from openjarvis.one_agents.lao_checkpoint_recovery import evidence_for
        enriched.update(evidence_for(str(enriched["external_job"])))
    except Exception as exc:
        enriched["lao_evidence_error"] = type(exc).__name__
    try:
        from openjarvis.one_agents import runtime
        plan = runtime._yatra_preproduction_file(str(enriched["external_job"]))
        record = json.loads(plan.read_text(encoding="utf-8"))[0]
        enriched["checkpoint_file"] = str(plan)
        enriched["browser_capture_plan_excerpt"] = str(
            record.get("browser_capture_plan") or ""
        )[:6000]
    except Exception as exc:  # evidence enrichment must never hide the failure
        enriched["checkpoint_evidence_error"] = f"{type(exc).__name__}: {exc}"
    return enriched


def repair_with_cli(evidence: dict[str, Any], *, timeout: int = 900) -> dict[str, Any]:
    """Ask the first available model CLI to make one bounded local repair.

    Refuses tracked or staged concurrent edits so human/agent work can never be
    swept into HELIOS's commit. Existing untracked diagnostic files are
    ignored but remembered; any new file produced by the repair is verified
    and committed only when it is inside the allow-listed boundary.
    """
    if os.environ.get("ONE_HELIOS_AUTO_REPAIR", "true").lower() not in {"1", "true", "yes", "on"}:
        return {"ok": False, "reason": "HELIOS auto repair disabled"}
    evidence = _with_checkpoint_evidence(evidence)
    repo = _repo_for(evidence)
    if repo is None:
        return {"ok": False, "reason": "failure is outside HELIOS's allow-listed repositories"}
    status = _git(repo, "status", "--porcelain", "--untracked-files=no")
    if status.returncode or status.stdout.strip():
        _audit_attempt({"job_id": evidence.get("job_id"), "event": "repository_not_clean",
                        "repo": str(repo), "returncode": status.returncode,
                        "status": str(getattr(status, "stdout", ""))[-1200:],
                        "stderr": str(getattr(status, "stderr", ""))[-1200:]})
        return {"ok": False, "reason": "repository is not clean; protected concurrent changes"}
    prompt = (
        "You are HELIOS's bounded Floor 12 repair worker. Diagnose the supplied latest failed job, "
        "make the smallest durable code fix in this repository, and add/update focused tests. "
        "Do not run production, browsers, uploads, downloads, voice generation, credential commands, "
        "network publishing, git commit, git push, reset, checkout, clean, or delete. Preserve API and "
        "checkpoint compatibility. If evidence is insufficient, make no changes and say so.\n\n"
        f"Failure evidence:\n{json.dumps(evidence, ensure_ascii=True)[:16000]}"
    )
    if not _cli_commands(prompt, repo):
        return {"ok": False, "reason": "no model CLI produced a verified patch: no providers available",
                "attempts": []}
    attempts: list[dict[str, Any]] = []
    try:
        with _isolated_repair_workspace(repo, evidence) as (workspace, original_revision):
            original_untracked = _untracked_paths(workspace)
            for name, command in _cli_commands(prompt, workspace):
                from openjarvis.one_agents import stages
                stages.set_stage("helios", stages.EXECUTING,
                                 f"Diagnosing {str(evidence.get('agent') or 'Floor 12').upper()} failure with {name} CLI")
                try:
                    cli_timeout = timeout
                    if name in {"qwen-local", "qwen-local-tools"}:
                        cli_timeout = min(timeout, max(60, int(os.environ.get("ONE_HELIOS_LOCAL_TIMEOUT_SECONDS", "300"))))
                    done = _run_cli(name, command, repo=workspace, timeout=cli_timeout)
                    attempts.append({"cli": name, "returncode": done.returncode,
                                     "output": (done.stdout or done.stderr or "")[-1200:]})
                except Exception as exc:  # noqa: BLE001 - fallback is the point
                    attempts.append({"cli": name, "error": f"{type(exc).__name__}: {exc}"})
                    _audit_attempt({"job_id": evidence.get("job_id"), **attempts[-1]})
                    continue
                _audit_attempt({"job_id": evidence.get("job_id"), **attempts[-1]})
                if done.returncode != 0:
                    continue
                tracked_names = set(_git(workspace, "diff", "--name-only").stdout.splitlines())
                new_untracked = _untracked_paths(workspace) - original_untracked
                names = sorted(path.replace("\\", "/") for path in tracked_names | new_untracked if path)
                if not names:
                    continue

                if not all(_allowed_patch_path(repo, path) for path in names):
                    _discard_attempt(workspace, names, original_untracked)
                    attempts[-1]["repair_check"] = "patch escaped HELIOS's file boundary"
                    _audit_attempt({"job_id": evidence.get("job_id"), **attempts[-1]})
                    continue

                stages.set_stage("helios", stages.EXECUTING, f"Testing {name} repair before retry")
                test_env = os.environ.copy()
                if repo.resolve() == REPO_ROOT.resolve():
                    test_env["PYTHONPATH"] = str(workspace / "src")
                check = subprocess.run(
                    _repair_test_command(repo), cwd=workspace, env=test_env,
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=1200,
                )
                if check.returncode:
                    _discard_attempt(workspace, names, original_untracked)
                    attempts[-1]["repair_check"] = "Floor 12 regression tests failed"
                    attempts[-1]["test_output"] = (check.stdout + check.stderr)[-1200:]
                    _audit_attempt({"job_id": evidence.get("job_id"), **attempts[-1]})
                    continue

                _git(workspace, "add", "--", *names)
                stages.set_stage("helios", stages.EXECUTING, "Committing the isolated verified Floor 12 repair")
                commit = _git(workspace, "commit", "-m", "HELIOS self-heal Floor 12 failure")
                if commit.returncode:
                    return {"ok": False, "reason": "verified isolated patch could not be committed",
                            "commit_error": commit.stderr[-1200:], "attempts": attempts}
                revision = _git(workspace, "rev-parse", "HEAD").stdout.strip()
                vista_unlocked = False
                relock: dict[str, Any] = {"ok": True}
                if repo.resolve() == VISTA_REPO.resolve() and _repo_is_vault_locked(repo):
                    unlocked = _unlock_vista_for_verified_promotion(evidence)
                    if not unlocked.get("ok"):
                        return {"ok": False, "reason": unlocked["reason"],
                                "attempts": attempts}
                    vista_unlocked = True
                try:
                    promoted = _promote_isolated_repair(repo, original_revision, revision)
                finally:
                    if vista_unlocked:
                        relock = _relock_vista_after_promotion(evidence)
                if not relock.get("ok"):
                    return {"ok": False, "reason": relock["reason"],
                            "attempts": attempts}
                if promoted.returncode:
                    return {"ok": False, "reason": "verified repair promotion refused",
                            "promotion_error": promoted.stderr[-1200:], "attempts": attempts}
                return {"ok": True, "cli": name, "commit": revision[:12],
                        "files": names, "isolated": True, "attempts": attempts}
    except RuntimeError as exc:
        return {"ok": False, "reason": f"isolated repair workspace unavailable: {exc}",
                "attempts": attempts}

    return {"ok": False, "reason": "no model CLI produced a verified patch: " + _attempt_reason(attempts),
            "attempts": attempts}


def heal_failure(connect: Connect, finding: Any) -> str:
    """Repair first; resume only after HELIOS produced a verified commit."""
    evidence = {"agent": finding.agent_id, "job_id": finding.job_id,
                "summary": finding.summary, **dict(finding.evidence or {})}
    evidence = _with_checkpoint_evidence(evidence)
    if _repair_circuit_is_open(evidence):
        saved = _load_repair_circuit(evidence)
        return (
            f"{PENDING_PREFIX}repair circuit open after "
            f"{saved.get('failed_rounds', _circuit_limit())} failed verified-repair rounds; "
            "no model providers invoked"
        )
    # A tested commit awaiting safe activation is still a valid repair. Do not
    # ask another model to invent another patch merely to retry deployment.
    receipt_dir = Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis")) / "helios_verified_repairs"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / (str(uuid.uuid5(uuid.NAMESPACE_URL, str(finding.job_id))) + ".json")
    repair = None
    repo = _repo_for(evidence)
    if receipt_path.exists() and repo:
        saved = json.loads(receipt_path.read_text(encoding="utf-8"))
        if saved.get("commit") == _git(repo, "rev-parse", "--short", "HEAD").stdout.strip():
            repair = saved
    if repair is None:
        repair = repair_with_cli(evidence)
        if repair.get("ok"):
            receipt_path.write_text(json.dumps(repair), encoding="utf-8")
    if not repair.get("ok"):
        circuit = _record_repair_failure(
            evidence, str(repair.get("reason") or "no verified repair"),
        )
        # A retry without a diagnosis and verified repair is not self-healing;
        # it merely repeats the same failure.  The watcher recognizes this
        # prefix as retryable/pending and deliberately does not ledger the
        # failed job as handled, so the next pass can try again.
        suffix = (
            f"; repair circuit {circuit['status']} "
            f"({circuit['failed_rounds']}/{circuit['limit']} failed rounds)"
        )
        return f"{PENDING_PREFIX}{repair.get('reason') or 'no verified repair'}{suffix}"
    _clear_repair_circuit(evidence)
    if _repo_for(evidence) == ENGINE_REPO:
        try:
            from openjarvis.one_agents.lao_checkpoint_recovery import activate_engine, resume_failed
            activate_engine()
            action = resume_failed(connect, _row(connect, finding.job_id),
                                   reviewed_conversation_url=repair.get("reviewed_conversation_url", ""))
        except Exception as exc:
            return f"{PENDING_PREFIX}verified engine repair; deployment/resume pending: {exc}"
    else:
        action = resume_checkpoint(connect, finding.job_id)
    prefix = f"{repair['cli']} repaired and committed {repair['commit']}"
    return f"{prefix}; {action}" if action else prefix
