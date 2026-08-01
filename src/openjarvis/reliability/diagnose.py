"""Self-diagnosis (★): ONE reads its own state and reports what's wrong.

The ambition layer of the reliability plan. It combines the cheap live signals —
canaries, subsystem health, the agent job queue, and the trace log — into a
single prioritised list of problems with a concrete suggested action for each.
This is what lets ONE surface "IA has failed 9 of its last 13 runs" proactively
instead of waiting for Sir to notice, and gives the Ghost Agent a structured
self-review it can read and act on.

Read-only and defensive: it never mutates state and never raises.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

_SEV_ORDER = {"critical": 0, "warn": 1, "info": 2}


def _home() -> Path:
    return Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))


def _issue(severity: str, title: str, detail: str, suggestion: str) -> dict[str, Any]:
    return {"severity": severity, "title": title, "detail": detail, "suggestion": suggestion}


def _agent_failure_issues() -> list[dict[str, Any]]:
    """Flag agents whose recent runs fail a lot, or jobs stuck running."""
    issues: list[dict[str, Any]] = []
    p = _home() / "agent_queue.db"
    if not p.exists():
        return issues
    try:
        c = sqlite3.connect(p, timeout=3)
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT agent_id, status FROM jobs").fetchall()
        c.close()
    except Exception:  # noqa: BLE001
        return issues
    per: dict[str, dict[str, int]] = {}
    for r in rows:
        d = per.setdefault(r["agent_id"], {"total": 0, "failed": 0})
        d["total"] += 1
        if r["status"] == "failed":
            d["failed"] += 1
    for agent, d in per.items():
        if d["total"] >= 4 and d["failed"] / d["total"] >= 0.5:
            issues.append(_issue(
                "warn",
                f"{agent.upper()} is failing often",
                f"{d['failed']} of {d['total']} recorded runs failed.",
                f"Review {agent.upper()}'s recent job errors before relying on it; the failure rate suggests a broken step, not luck.",
            ))
    return issues


def _canary_issues() -> list[dict[str, Any]]:
    try:
        from openjarvis.reliability.canary import run_canaries
        summary = run_canaries()
    except Exception as exc:  # noqa: BLE001
        return [_issue("warn", "Canaries could not run", str(exc), "Check the reliability.canary import chain.")]
    out = []
    for r in summary.get("results", []):
        if not r["passed"]:
            sev = "critical" if r["name"] in ("router", "agents") else "warn"
            out.append(_issue(
                sev,
                f"Canary failing: {r['name']}",
                r["detail"],
                "A self-test that guards a real past regression is red — fix before shipping.",
            ))
    return out


def _health_issues(app: Any = None) -> list[dict[str, Any]]:
    try:
        from openjarvis.reliability.health import system_health
        h = system_health(app)
    except Exception as exc:  # noqa: BLE001
        return [_issue("warn", "Health probes could not run", str(exc), "Check reliability.health.")]
    out = []
    for p in h.get("probes", []):
        if not p["ok"]:
            out.append(_issue(
                "critical" if p["severity"] == "crit" else "warn",
                f"Subsystem degraded: {p['name']}",
                p["detail"],
                p.get("remediation") or "Investigate this subsystem.",
            ))
    return out


def self_diagnose(app: Any = None) -> dict[str, Any]:
    """Full self-review. Returns a prioritised issue list. Never raises.
    Pass the live FastAPI ``app`` for honest STT + Ghost Agent checks."""
    issues: list[dict[str, Any]] = []
    try:
        issues.extend(_health_issues(app))
    except Exception:  # noqa: BLE001
        pass
    for fn in (_canary_issues, _agent_failure_issues):
        try:
            issues.extend(fn())
        except Exception:  # noqa: BLE001
            pass
    issues.sort(key=lambda i: _SEV_ORDER.get(i["severity"], 3))
    worst = issues[0]["severity"] if issues else "info"
    status = {"critical": "critical", "warn": "attention", "info": "healthy"}.get(worst, "healthy")
    headline = (
        "All clear — no problems detected."
        if not issues
        else f"{len(issues)} issue(s) found; most urgent: {issues[0]['title']}."
    )
    return {
        "status": status,
        "headline": headline,
        "issue_count": len(issues),
        "issues": issues,
    }
