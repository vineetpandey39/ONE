"""Supervisor: probe each subsystem, report health, hint remediation.

Mechanism #3 (first half). Today's health signals are scattered across a
PowerShell watchdog, the robot re-auth loop, and ad-hoc try/excepts. This
gathers cheap, non-blocking probes into one place the cockpit (and canaries) can
read, so "is ONE actually healthy?" has a single honest answer.

Every probe is defensive: it never raises, never blocks for more than a moment,
and returns a uniform ``Probe`` dict. ``remediation`` names the known fix so the
same knowledge that lived in our heads is now in the system.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

_TIMEOUT = 3.0


def _probe(name: str, ok: bool, detail: str, *, severity: str = "warn", remediation: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "detail": detail,
        "severity": "ok" if ok else severity,
        "remediation": remediation if not ok else "",
    }


def _home() -> Path:
    return Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))


def check_stt(backend: Any = None) -> dict[str, Any]:
    """Is a speech backend actually usable? When the live backend is passed in,
    call its real ``health()`` — an env key being present is NOT proof the
    client initialised (a real failure: the Deepgram client was built before
    the vault key was injected, so the key was in os.environ but the client was
    dead). Falls back to a presence check only when no backend is available."""
    if backend is not None:
        try:
            if backend.health():
                return _probe("stt", True, f"{getattr(backend, 'backend_id', 'speech')} backend live.")
            return _probe(
                "stt", False,
                f"{getattr(backend, 'backend_id', 'speech')} backend built but NOT usable "
                f"(client failed to initialise — likely no API key at build time).",
                severity="crit",
                remediation="Restart ONE so credentials inject before the backend is built (see serve.py inject_credentials).",
            )
        except Exception as exc:  # noqa: BLE001
            return _probe("stt", False, f"speech backend health() raised: {exc}", severity="crit",
                          remediation="Restart ONE; check the speech backend init.")
    if os.environ.get("DEEPGRAM_API_KEY", "").strip():
        return _probe("stt", True, "Deepgram key present (backend not passed for live check).")
    try:
        import faster_whisper  # noqa: F401
        return _probe("stt", True, "faster-whisper available (local fallback).")
    except Exception:
        return _probe(
            "stt", False, "No usable speech backend.",
            severity="crit",
            remediation="Set DEEPGRAM_API_KEY in the vault, or install faster-whisper (uv sync --extra speech).",
        )


def check_model() -> dict[str, Any]:
    """Can we reach the local router model host (Ollama)?"""
    host = (
        os.environ.get("OLLAMA_HOST")
        or os.environ.get("ONE_OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).rstrip("/")
    try:
        import httpx

        r = httpx.get(f"{host}/api/tags", timeout=_TIMEOUT, verify=False)
        if r.status_code == 200:
            n = len(r.json().get("models", []))
            return _probe("model", True, f"Ollama up at {host} ({n} model(s)).")
        return _probe("model", False, f"Ollama returned {r.status_code} at {host}.", severity="crit",
                      remediation="Start Ollama (ollama serve) or fix OLLAMA_HOST.")
    except Exception as exc:  # noqa: BLE001
        return _probe("model", False, f"Ollama unreachable at {host}: {exc}", severity="crit",
                      remediation="Start Ollama (ollama serve). The Ghost Agent (cloud) can still answer if a cloud key is set.")


def check_queue() -> dict[str, Any]:
    """Agent job queue reachable, and flag jobs stuck 'running' for a long time."""
    p = _home() / "agent_queue.db"
    if not p.exists():
        return _probe("queue", True, "No agent_queue.db yet (nothing has run) — not an error.")
    try:
        c = sqlite3.connect(p, timeout=_TIMEOUT)
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT status, updated_at FROM jobs").fetchall()
        c.close()
        running = [r for r in rows if r["status"] == "running"]
        queued = [r for r in rows if r["status"] == "queued"]
        # A job "running" for >30 min with nothing advancing is likely stuck.
        stuck = 0
        now = time.time()
        for r in running:
            try:
                from datetime import datetime
                ts = datetime.fromisoformat(r["updated_at"]).timestamp()
                if now - ts > 1800:
                    stuck += 1
            except Exception:
                pass
        if stuck:
            return _probe("queue", False, f"{stuck} job(s) stuck 'running' >30 min.", severity="warn",
                          remediation="Check the worker; a stuck job usually means the worker died mid-run.")
        return _probe("queue", True, f"Queue OK ({len(queued)} queued, {len(running)} running).")
    except Exception as exc:  # noqa: BLE001
        return _probe("queue", False, f"Queue DB error: {exc}", severity="warn",
                      remediation="agent_queue.db may be locked or corrupt.")


def check_disk() -> dict[str, Any]:
    """Free space on ONE's data drive — low disk silently breaks media/models."""
    try:
        total, used, free = shutil.disk_usage(_home())
        gb = free / (1024 ** 3)
        if gb < 2:
            return _probe("disk", False, f"Only {gb:.1f} GB free.", severity="crit",
                          remediation="Free space — media generation and model loads need headroom.")
        if gb < 8:
            return _probe("disk", False, f"{gb:.1f} GB free (getting low).", severity="warn",
                          remediation="Consider freeing space before large media runs.")
        return _probe("disk", True, f"{gb:.0f} GB free.")
    except Exception as exc:  # noqa: BLE001
        return _probe("disk", True, f"Disk check skipped: {exc}")


def check_ghost_agent(app: Any = None) -> dict[str, Any]:
    """Is the cloud Ghost Agent actually wired? If cloud_escalation_model is
    None, ONE silently falls back to the weak local model for anything the fast
    path doesn't handle — the real cause of off-topic replies. Only meaningful
    when the live app is passed."""
    if app is None:
        return _probe("ghost_agent", True, "not checked (no app context).")
    model = getattr(getattr(app, "state", None), "cloud_escalation_model", None)
    if model:
        return _probe("ghost_agent", True, f"cloud escalation active ({model}).")
    return _probe(
        "ghost_agent", False,
        "Cloud Ghost Agent NOT wired — falling back to the local model for everything.",
        severity="crit",
        remediation="Ensure ANTHROPIC_API_KEY (or OPENAI_API_KEY) is injected from the vault before startup, then restart.",
    )


def system_health(app: Any = None) -> dict[str, Any]:
    """Run every probe and roll up an overall status. Never raises.
    Pass the live FastAPI ``app`` for honest STT + Ghost Agent checks."""
    backend = getattr(getattr(app, "state", None), "speech_backend", None) if app is not None else None
    probes = []
    try:
        probes.append(check_stt(backend))
    except Exception as exc:  # noqa: BLE001
        probes.append(_probe("stt", False, f"probe crashed: {exc}"))
    try:
        probes.append(check_ghost_agent(app))
    except Exception as exc:  # noqa: BLE001
        probes.append(_probe("ghost_agent", False, f"probe crashed: {exc}"))
    for fn in (check_model, check_queue, check_disk):
        try:
            probes.append(fn())
        except Exception as exc:  # noqa: BLE001
            probes.append(_probe(fn.__name__.replace("check_", ""), False, f"probe crashed: {exc}"))
    has_crit = any(p["severity"] == "crit" for p in probes)
    has_warn = any(not p["ok"] for p in probes)
    status = "critical" if has_crit else ("degraded" if has_warn else "healthy")
    return {
        "status": status,
        "healthy": status == "healthy",
        "checked_at": time.time(),
        "probes": probes,
    }
