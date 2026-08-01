"""Canary self-tests: catch regressions before the user does.

Mechanism #3 (second half). These are synthetic end-to-end checks run on startup
and on demand (GET /v1/one/canary). Each asserts a behaviour we actually broke
and had to hand-fix, so the same regression can never ship silently again.

The flagship is ``canary_router``: it asserts the deterministic fast-path answers
a real command ("list agents") AND does NOT hijack an ordinary question ("what's
the weather"). Today's "every agent question returns a canned roster" regression
would have tripped this the instant ONE restarted.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger("openjarvis.reliability")


def _result(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def canary_router() -> dict[str, Any]:
    """The fast-path must answer explicit commands but defer real questions to
    the LLM. Guards the routing-hijack class directly."""
    try:
        from openjarvis.server.routes import _one_agent_command
    except Exception as exc:  # noqa: BLE001
        return _result("router", False, f"could not import router: {exc}")

    should_answer = _one_agent_command("list agents") or ""
    # An ordinary question must fall through (None) to the Ghost Agent/LLM.
    should_defer = _one_agent_command("what's the weather in Noida right now")

    ok_answer = bool(should_answer) and "TITAN" in should_answer.upper()
    ok_defer = should_defer is None
    if ok_answer and ok_defer:
        return _result("router", True, "fast-path answers commands and defers questions.")
    problems = []
    if not ok_answer:
        problems.append("'list agents' did not return a roster")
    if not ok_defer:
        problems.append("an ordinary question was hijacked by the fast-path (regression!)")
    return _result("router", False, "; ".join(problems))


def canary_stt() -> dict[str, Any]:
    try:
        from openjarvis.reliability.health import check_stt
        p = check_stt()
        return _result("stt", p["ok"], p["detail"])
    except Exception as exc:  # noqa: BLE001
        return _result("stt", False, f"stt canary crashed: {exc}")


def canary_model() -> dict[str, Any]:
    try:
        from openjarvis.reliability.health import check_model
        p = check_model()
        # Model being down is degraded, not a hard canary fail (cloud Ghost
        # Agent can still serve), so report but don't count it as a red failure.
        return _result("model", True, p["detail"] + ("" if p["ok"] else " [degraded, not fatal]"))
    except Exception as exc:  # noqa: BLE001
        return _result("model", False, f"model canary crashed: {exc}")


def canary_agents_registry() -> dict[str, Any]:
    """The agent roster must be loadable and non-empty (a broken import here is
    what makes agent commands silently fail)."""
    try:
        from openjarvis.one_agents.runtime import AGENTS
        if AGENTS and all("name" in v and "role" in v for v in AGENTS.values()):
            return _result("agents", True, f"{len(AGENTS)} agents registered.")
        return _result("agents", False, "AGENTS registry malformed or empty.")
    except Exception as exc:  # noqa: BLE001
        return _result("agents", False, f"could not load AGENTS: {exc}")


_CANARIES: tuple[Callable[[], dict[str, Any]], ...] = (
    canary_router,
    canary_agents_registry,
    canary_stt,
    canary_model,
)


def run_canaries() -> dict[str, Any]:
    """Run every canary. Never raises. Returns a pass/fail summary."""
    results = []
    for fn in _CANARIES:
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001
            results.append(_result(fn.__name__.replace("canary_", ""), False, f"crashed: {exc}"))
    failed = [r for r in results if not r["passed"]]
    summary = {
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "total": len(results),
        "ok": not failed,
        "results": results,
    }
    if failed:
        logger.warning("CANARY FAIL: %s", "; ".join(f"{r['name']}: {r['detail']}" for r in failed))
    else:
        logger.info("Canaries passed (%d/%d).", summary["passed"], summary["total"])
    return summary
