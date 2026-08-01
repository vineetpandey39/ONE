"""Closed-loop action wrapper: expect -> verify -> self-correct -> escalate.

Mechanism #2 from the reliability brainstorm. We hand-wrote this exact pattern
four separate times in one session (ChatGPT continue-nudge, Leonardo panel
recheck, robot 401 -> reauth, peek-then-commit). This is the single reusable
version so no one writes it a fifth time.

The contract every resilient step should follow:

    result = run_with_recovery(
        lambda: do_the_thing(),          # ACTION  -- produce a result
        verify=lambda r: is_good(r),     # VERIFY  -- did it meet the goal?
        correct=lambda attempt, r: nudge(),   # SELF-CORRECT (optional)
        escalate=lambda r, err: fallback(),   # ESCALATE (optional)
        max_attempts=3,
        label="chatgpt_plan",
    )

If ``verify`` passes, that result is returned. Otherwise ``correct`` runs and the
action is retried, up to ``max_attempts``. If it never verifies, ``escalate`` is
called and its return value is used; with no ``escalate`` a ``RecoveryError`` is
raised carrying the last result and error -- a *loud, contextful* failure instead
of a silent wrong answer. Nothing here is ONE-specific; it wraps any callable.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("openjarvis.reliability")


class RecoveryError(RuntimeError):
    """Raised when an action never verified and no escalation was provided.

    Carries the last result and last exception so the caller (or the Ghost
    Agent's self-diagnosis) can see *what* the failure actually looked like."""

    def __init__(self, label: str, attempts: int, last_result: Any, last_error: Optional[BaseException]):
        self.label = label
        self.attempts = attempts
        self.last_result = last_result
        self.last_error = last_error
        detail = f" last_error={last_error!r}" if last_error is not None else ""
        super().__init__(f"'{label}' did not succeed after {attempts} attempt(s).{detail}")


def run_with_recovery(
    action: Callable[[], Any],
    *,
    verify: Callable[[Any], bool],
    correct: Optional[Callable[[int, Any], None]] = None,
    escalate: Optional[Callable[[Any, Optional[BaseException]], Any]] = None,
    max_attempts: int = 3,
    backoff_seconds: float = 0.0,
    on_event: Optional[Callable[[str, dict], None]] = None,
    label: str = "action",
) -> Any:
    """Run ``action`` until ``verify`` passes, self-correcting between tries.

    Args:
        action: zero-arg callable producing a result (may raise).
        verify: predicate on the result; True means the goal was met.
        correct: optional (attempt_number, last_result) -> None hook run before
            each retry (e.g. send a "you got cut off, continue" nudge).
        escalate: optional (last_result, last_error) -> Any, used when all
            attempts fail; its return becomes the return of this call.
        max_attempts: total attempts including the first.
        backoff_seconds: base delay multiplied by attempt index before retries.
        on_event: optional observability hook (event_name, fields).
        label: name for logs / RecoveryError.

    Returns:
        The first verifying result, or ``escalate``'s result.

    Raises:
        RecoveryError: if it never verifies and no ``escalate`` is given.
    """
    max_attempts = max(1, int(max_attempts))
    last_result: Any = None
    last_error: Optional[BaseException] = None

    def _emit(event: str, **fields: Any) -> None:
        if on_event is not None:
            try:
                on_event(event, fields)
            except Exception:  # noqa: BLE001 -- observability must never break the loop
                pass

    for attempt in range(1, max_attempts + 1):
        if attempt > 1 and backoff_seconds > 0:
            time.sleep(backoff_seconds * (attempt - 1))
        try:
            if attempt > 1 and correct is not None:
                try:
                    correct(attempt, last_result)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[%s] correct() hook failed on attempt %d: %s", label, attempt, exc)
            last_result = action()
            last_error = None
            ok = False
            try:
                ok = bool(verify(last_result))
            except Exception as exc:  # noqa: BLE001 -- a throwing verifier means "not verified"
                last_error = exc
                logger.warning("[%s] verify() raised on attempt %d: %s", label, attempt, exc)
            if ok:
                if attempt > 1:
                    logger.info("[%s] recovered on attempt %d/%d", label, attempt, max_attempts)
                _emit("verified", attempt=attempt)
                return last_result
            _emit("unverified", attempt=attempt)
            logger.warning("[%s] attempt %d/%d did not verify", label, attempt, max_attempts)
        except Exception as exc:  # noqa: BLE001 -- action itself failed; treat as a retryable attempt
            last_error = exc
            _emit("error", attempt=attempt, error=repr(exc))
            logger.warning("[%s] attempt %d/%d raised: %s", label, attempt, max_attempts, exc)

    if escalate is not None:
        logger.warning("[%s] all %d attempts failed; escalating", label, max_attempts)
        _emit("escalated", attempts=max_attempts)
        return escalate(last_result, last_error)

    _emit("failed", attempts=max_attempts)
    raise RecoveryError(label, max_attempts, last_result, last_error)
