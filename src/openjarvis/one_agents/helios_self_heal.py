"""Bounded self-healing for Floor 12 (YouTube Studio).

HELIOS is allowed to repair its own implementation, but it is not allowed to
turn a production retry into a second production.  This module therefore keeps
the two decisions separate:

* resume only checkpoint-safe workers (YATRA visuals, LYRA, VISTA and ECHO);
* edit code only in a clean, allow-listed Git repository, run the repository's
  Floor 12 tests, then create a local commit (never push).

Claude Code and Codex are tried first. Qwen Code is then run against the
installed local Ollama Qwen model (not the unauthenticated Qwen cloud CLI
default), followed by native Ollama tool calls if Qwen Code emits pseudo-calls.
NVIDIA Nemotron is the final remote fallback, with its key resolved from LAO.
A model failure is a diagnostic failure, not permission to bypass the gates.
"""

from __future__ import annotations

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
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


Connect = Callable[[], sqlite3.Connection]
SAFE_RETRY_AGENTS = {"lyra", "vista", "echo"}
FLOOR12_AGENTS = {"helios", "fabula", "yatra", "lyra", "vista", "echo", "planexium", "chandan"}
REPO_ROOT = Path(__file__).resolve().parents[3]
ALLOWED_REPOS = (REPO_ROOT, Path(r"C:\Users\pc\Documents\LAO\vista"))
PENDING_PREFIX = "pending self-heal: "
# These files are the independent checker/maker and self-heal control plane.
# A production failure may be repaired by that control plane, but a model CLI
# must never rewrite the rules that supervise or authorize its own repair.
# Human-reviewed commits can still change them; this boundary applies only to
# autonomous HELIOS patches and is deliberately unrelated to the restart gate.
PROTECTED_CONTROL_PLANE_PATHS = {
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
        # A finished receipt means voice credits were already spent and the
        # only missing action is the YATRA handoff. Never call FABULA again.
        try:
            yatra_active = _active_for_agent(connect, "yatra", job_id)
            if yatra_active:
                return f"FABULA receipt handoff deferred; YATRA already has active job {yatra_active}"
            payload = json.loads(str(previous.get("task") or "{}"))
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
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)


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
        codex_model = os.environ.get("ONE_HELIOS_CODEX_MODEL", "gpt-6-luna").strip() or "gpt-6-luna"
        commands.append(("codex", [codex, "exec", "--model", codex_model,
                                    "--ephemeral", "--approve-for-me",
                                    "--cd", str(repo), prompt]))
    qwen = _which_cli("qwen")
    # Qwen Code has no implicit local backend. _run_cli supplies an isolated
    # profile pinned to Ollama, avoiding cloud-auth prompts.
    local_model = os.environ.get("ONE_HELIOS_LOCAL_MODEL", "qwen3.5:9b").strip()
    if local_model:
        # Headless Qwen Code otherwise emits a tool-call request and exits
        # without applying it. Auto-approve only inside its disposable Docker
        # sandbox; host-side diff/path/test/commit gates remain authoritative.
        if qwen:
            commands.append(("qwen-local", [qwen, "--sandbox", "--approval-mode", "yolo",
                                              "-m", local_model, "-p", prompt]))
        # This path needs no Qwen Code executable. Keep it present even when
        # the scheduled worker has a short PATH and cannot resolve qwen.cmd.
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
        body = json.dumps({"model": model, "messages": messages, "tools": tools,
                           "stream": False, "temperature": 0.1, "max_tokens": 2048}).encode()
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
        messages.append(message)
        content = str(message.get("content") or "")
        if content:
            output.append(content)
        calls = message.get("tool_calls") or []
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


def _run_cli(name: str, command: list[str], *, repo: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    """Run Qwen Code with a disposable isolated profile; other CLIs inherit env."""
    if name == "qwen-local-tools":
        return _run_qwen_native_tools(command, repo=repo, timeout=timeout)
    if name == "nemotron-native-tools":
        return _run_nemotron_native_tools(command, repo=repo, timeout=timeout)
    if name not in {"qwen-local", "nemotron"}:
        return subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=timeout)
    model = command[command.index("-m") + 1]
    with tempfile.TemporaryDirectory(prefix="helios-qwen-") as profile:
        profile_path = Path(profile)
        qwen_dir = profile_path / ".qwen"
        qwen_dir.mkdir()
        env = os.environ.copy()
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
                              text=True, timeout=timeout)


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
    if repo.resolve() == ALLOWED_REPOS[1].resolve():
        return normalized.endswith(".py") and not normalized.startswith(("runs/", "direction-history/"))
    return False


def _repair_test_command(repo: Path) -> list[str]:
    python = os.environ.get("ONE_HELIOS_PYTHON", sys.executable)
    if repo.resolve() == REPO_ROOT.resolve():
        return [python, "-m", "pytest", "tests/one_agents", "-q", "--maxfail=1"]
    return [python, "-m", "pytest", "-q", "--maxfail=1"]


def repair_with_cli(evidence: dict[str, Any], *, timeout: int = 900) -> dict[str, Any]:
    """Ask the first available model CLI to make one bounded local repair.

    Refuses dirty repositories so unrelated human/agent work can never be
    swept into HELIOS's commit. The model may edit; HELIOS owns verification
    and the commit.
    """
    if os.environ.get("ONE_HELIOS_AUTO_REPAIR", "true").lower() not in {"1", "true", "yes", "on"}:
        return {"ok": False, "reason": "HELIOS auto repair disabled"}
    repo = _repo_for(evidence)
    if repo is None:
        return {"ok": False, "reason": "failure is outside HELIOS's allow-listed repositories"}
    status = _git(repo, "status", "--porcelain")
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
        f"Failure evidence:\n{json.dumps(evidence, ensure_ascii=True)[:7000]}"
    )
    attempts: list[dict[str, Any]] = []
    for name, command in _cli_commands(prompt, repo):
        from openjarvis.one_agents import stages
        stages.set_stage("helios", stages.EXECUTING,
                         f"Diagnosing {str(evidence.get('agent') or 'Floor 12').upper()} failure with {name} CLI")
        try:
            cli_timeout = timeout
            if name == "qwen-local-tools":
                cli_timeout = min(timeout, max(60, int(os.environ.get("ONE_HELIOS_LOCAL_TIMEOUT_SECONDS", "300"))))
            done = _run_cli(name, command, repo=repo, timeout=cli_timeout)
            attempts.append({"cli": name, "returncode": done.returncode,
                             "output": (done.stdout or done.stderr or "")[-1200:]})
        except Exception as exc:  # noqa: BLE001 - fallback is the point
            attempts.append({"cli": name, "error": f"{type(exc).__name__}: {exc}"})
            _audit_attempt({"job_id": evidence.get("job_id"), **attempts[-1]})
            continue
        _audit_attempt({"job_id": evidence.get("job_id"), **attempts[-1]})
        if done.returncode != 0:
            continue
        changed = _git(repo, "status", "--porcelain")
        if not changed.stdout.strip():
            continue

        # Block changes outside Floor 12 runtime/tests. This also prevents a
        # model from changing credentials, floor governance, or another line.
        names = _git(repo, "diff", "--name-only").stdout.splitlines()
        if not names or not all(_allowed_patch_path(repo, path) for path in names):
            _git(repo, "restore", "--worktree", "--", *names)
            attempts[-1]["repair_check"] = "patch escaped HELIOS's file boundary"
            _audit_attempt({"job_id": evidence.get("job_id"), **attempts[-1]})
            continue

        stages.set_stage("helios", stages.EXECUTING, f"Testing {name} repair before retry")
        check = subprocess.run(
            _repair_test_command(repo),
            cwd=repo, capture_output=True, text=True, timeout=1200,
        )
        if check.returncode:
            _git(repo, "restore", "--worktree", "--", *names)
            attempts[-1]["repair_check"] = "Floor 12 regression tests failed"
            attempts[-1]["test_output"] = (check.stdout + check.stderr)[-1200:]
            _audit_attempt({"job_id": evidence.get("job_id"), **attempts[-1]})
            # An unverified patch did not repair the failure; continue with a
            # clean tree so the next configured model gets its own attempt.
            continue

        _git(repo, "add", "--", *names)
        stages.set_stage("helios", stages.EXECUTING, "Committing the verified Floor 12 repair")
        commit = _git(repo, "commit", "-m", "HELIOS self-heal Floor 12 failure")
        if commit.returncode:
            return {"ok": False, "reason": "verified patch could not be committed",
                    "commit_error": commit.stderr[-1200:], "attempts": attempts}
        sha = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
        return {"ok": True, "cli": name, "commit": sha,
                "files": names, "attempts": attempts}

    return {"ok": False, "reason": "no model CLI produced a verified patch: " + _attempt_reason(attempts),
            "attempts": attempts}


def heal_failure(connect: Connect, finding: Any) -> str:
    """Repair first; resume only after HELIOS produced a verified commit."""
    evidence = {"agent": finding.agent_id, "job_id": finding.job_id,
                "summary": finding.summary, **dict(finding.evidence or {})}
    repair = repair_with_cli(evidence)
    if not repair.get("ok"):
        # A retry without a diagnosis and verified repair is not self-healing;
        # it merely repeats the same failure.  The watcher recognizes this
        # prefix as retryable/pending and deliberately does not ledger the
        # failed job as handled, so the next pass can try again.
        return f"{PENDING_PREFIX}{repair.get('reason') or 'no verified repair'}"
    action = resume_checkpoint(connect, finding.job_id)
    prefix = f"{repair['cli']} repaired and committed {repair['commit']}"
    return f"{prefix}; {action}" if action else prefix
