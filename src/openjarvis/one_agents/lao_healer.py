"""Self-healing for the LAO robot-worker infrastructure SCRIBE depends on.

SCRIBE blocks on a multi-hour LAO job. Until 2026-08-16, three well-
understood infrastructure failures around that job each required a human
to notice, diagnose, and fix by hand -- every single time they happened:

1. The robot-worker process gets restarted mid-job (a periodic,
   externally-triggered restart -- see robot-worker-watchdog.ps1, which
   fires whenever the currently-running agent.py process has exited for
   any reason) and orphans whatever job it was mid-way through: LAO's own
   job record is stuck "Running" forever, and once that job is finally
   stopped, the robot itself gets stuck reporting status="Busy" with
   current_job_id=None, refusing to pick up any new job until restarted.
2. A killed/stopped job can leave its Claude Code CLI child process
   (claude.exe --add-dir <run_dir>) still alive, holding a file lock on
   the run folder that blocks cleanup ("Device or resource busy" /
   "used by another process").
3. workflow_engine.py gets edited (a new or changed action) but the
   already-running robot-worker process still has the old version loaded
   in memory -- Python doesn't hot-reload a running process's imports --
   so the next job fails immediately with "Unknown workflow action: X".

All three were diagnosed and fixed by hand, repeatedly, in one evening.
`heal()` recognizes the same signatures and fixes them deterministically.
Deliberately scoped to ONLY these known, already-proven-safe fixes -- an
earlier draft of this module also escalated unrecognized failures to a
Claude Code CLI pass with `--permission-mode bypassPermissions` so it
could autonomously run repair commands, which is real unattended system-
administration power and was rejected before it ever shipped. An
unrecognized failure now does no action at all beyond logging every
detail needed to add a new pattern here later -- see `recent_events()`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from openjarvis.core.paths import get_data_dir

LAO_BASE_URL = os.environ.get("LAO_BASE_URL", "http://127.0.0.1:18000/api/v1")
LAO_EMAIL = os.environ.get("LAO_EMAIL", "admin@example.com")
LAO_PASSWORD = os.environ.get("LAO_PASSWORD", "ChangeMe123!")

# The actual robot-worker directory this whole project's LAO robots run
# from. Restarting means: kill the production agent.py (parent+child) pair
# -- excludes any --config match so this never touches the separate Studio
# robot -- and let robot-worker-watchdog.ps1 (which polls every 15s) notice
# it's gone and spawn a fresh one with whatever is currently on disk.
ROBOT_WORKER_DIR = os.environ.get(
    "LAO_ROBOT_WORKER_DIR",
    r"C:\Users\pc\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\local-agent-mode-sessions"
    r"\cb3dc5b9-a76c-45ff-bbcf-b330fe30c84a\21738b93-8e02-4c20-a83c-0abb35d85c72"
    r"\local_374e1c90-a56c-4744-840b-8f0118a3547a\outputs\lao-platform\robot-worker",
)

# Was os.environ.get("ONE_HOME", ...) - "ONE_HOME" is set nowhere in this
# suite (the real variable is OPENJARVIS_HOME, set by start-one.ps1), so this
# always fell through to the hardcoded ~/.openjarvis fallback regardless of
# how the process was launched. get_data_dir() is the shared resolver every
# other module in this tree uses (OPENJARVIS_HOME > XDG_DATA_HOME > the same
# ~/.openjarvis default, but only when neither is set) - this file just never
# got migrated to it.
_LOG_PATH = get_data_dir() / "lao_healer_log.jsonl"


def _log_event(event: dict[str, Any]) -> None:
    """Append-only, best-effort. A logging failure must never break the
    healing attempt or the caller's own error handling."""
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {"at": time.time(), **event}
        with _LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except Exception:  # noqa: BLE001
        pass


def recent_events(limit: int = 20) -> list[dict[str, Any]]:
    """Every healing attempt this module has made or logged, most recent
    first -- matched-and-fixed as well as unrecognized-and-untouched, so
    "what has the healer actually done" is always answerable without
    digging through code or job history."""
    if not _LOG_PATH.exists():
        return []
    try:
        lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events = []
    for line in reversed(lines[-limit * 2:]):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(events) >= limit:
            break
    return events


def _ps(command: str, timeout: int = 40) -> str:
    """Runs a PowerShell command and returns its stdout, best-effort."""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True, text=True, timeout=timeout,
    )
    return (result.stdout or "").strip()


def _lao_token() -> str:
    response = httpx.post(
        f"{LAO_BASE_URL}/auth/login",
        json={"email": LAO_EMAIL, "password": LAO_PASSWORD},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _lao_get(path: str, token: str) -> Any:
    response = httpx.get(f"{LAO_BASE_URL}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=15)
    response.raise_for_status()
    return response.json()


def _robot_stuck_busy() -> bool:
    """True if any LAO robot reports Busy with no job actually assigned --
    the signature that leaves the robot refusing all new work forever."""
    try:
        token = _lao_token()
        robots = _lao_get("/robots", token)
        return any(r.get("status") == "Busy" and not r.get("current_job_id") for r in robots)
    except Exception:  # noqa: BLE001 - a failed health check just means "can't confirm", not "stuck"
        return False


def restart_robot_worker() -> bool:
    """Kills the production agent.py (parent+child) pair and waits for
    robot-worker-watchdog.ps1 to respawn it with whatever's on disk now.
    Returns True once a fresh pair is confirmed running."""
    _ps(
        "Get-CimInstance Win32_Process -Filter \"name = 'python.exe'\" | "
        "Where-Object { $_.CommandLine -match 'agent.py' -and $_.CommandLine -notmatch '--config' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        time.sleep(3)
        out = _ps(
            "(Get-CimInstance Win32_Process -Filter \"name = 'python.exe'\" | "
            "Where-Object { $_.CommandLine -match 'agent.py' -and $_.CommandLine -notmatch '--config' }).Count"
        )
        if out.strip().isdigit() and int(out.strip()) >= 2:
            return True
    return False


def kill_locking_claude_process(run_dir: str) -> bool:
    """Kills any Claude Code CLI subprocess still holding a file lock on a
    stopped/killed run's folder (the --add-dir target names the exact
    folder, so this can never touch an unrelated, still-legitimate run)."""
    if not run_dir:
        return False
    escaped = run_dir.replace("'", "''")
    out = _ps(
        f"Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -match [Regex]::Escape('{escaped}') }} "
        "| Select-Object -ExpandProperty ProcessId"
    )
    pids = [p for p in out.split() if p.isdigit()]
    if not pids:
        return False
    _ps("Stop-Process -Id " + ",".join(pids) + " -Force -ErrorAction SilentlyContinue")
    return True


def cleanup_run_folder(run_dir: str, attempts: int = 3) -> bool:
    path = Path(run_dir)
    if not path.exists():
        return True
    for _ in range(attempts):
        try:
            shutil.rmtree(path)
            return True
        except OSError:
            time.sleep(2)
    return False


def heal(error_text: str, run_dir: str = "") -> dict[str, Any]:
    """Looks at a LAO/SCRIBE failure, fixes it if it matches one of the
    three known infrastructure signatures above, and always logs what it
    found -- matched or not -- via _log_event/recent_events().

    Returns {"healed": bool, "actions": [...], "diagnosis": str}. "healed"
    means the caller's situation should now be different enough to be
    worth retrying -- it does NOT guarantee the retry will succeed (a
    genuinely broken run stays broken; this only fixes the infrastructure
    around it). An unrecognized failure returns healed=False and takes no
    action -- see the module docstring for why that's deliberate."""
    actions: list[str] = []
    lowered = error_text.lower()

    if "unknown workflow action" in lowered:
        if restart_robot_worker():
            actions.append("restarted_robot_worker_stale_code")
            result = {"healed": True, "actions": actions, "diagnosis": (
                "workflow_engine.py was edited after the robot-worker process last started, "
                "so it was running stale code and rejected an action it doesn't recognize yet. "
                "Restarted the robot-worker; it will load the current code on the next job."
            )}
            _log_event({"error": error_text, "run_dir": run_dir, **result})
            return result

    healed_busy = False
    if _robot_stuck_busy():
        if restart_robot_worker():
            actions.append("restarted_robot_worker_stuck_busy")
            healed_busy = True

    lock_signal = any(s in lowered for s in ("device or resource busy", "used by another process", "cannot access the file"))
    if lock_signal and run_dir:
        if kill_locking_claude_process(run_dir):
            actions.append("killed_locking_claude_process")
        cleanup_run_folder(run_dir)
        actions.append("cleaned_run_folder")

    if actions:
        result = {
            "healed": True,
            "actions": actions,
            "diagnosis": f"Recognized a known infrastructure failure signature and applied: {', '.join(actions)}.",
        }
    elif healed_busy:
        result = {"healed": True, "actions": actions, "diagnosis": "Robot was stuck Busy with no job assigned; restarted it."}
    else:
        result = {
            "healed": False,
            "actions": [],
            "diagnosis": (
                "No known infrastructure pattern matched (not a stuck-busy robot, stale-code "
                "rejection, or file-lock signature). Logged for review -- no action taken."
            ),
        }

    _log_event({"error": error_text, "run_dir": run_dir, **result})
    return result
