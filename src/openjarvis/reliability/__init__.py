"""ONE reliability layer — turn one-off bug fixes into reusable self-healing.

Every failure we kept hand-patching had the same shape: an open-loop handoff
where one stage's imperfect output hard-failed the next and nothing verified the
goal was met. This package holds the reusable mechanisms that fix the *shape*:

* ``self_heal``  -- expect -> verify -> self-correct -> escalate wrapper (#2).
* ``health``     -- supervisor probes over each subsystem, auto-remediation (#3).
* ``canary``     -- synthetic end-to-end self-tests that catch regressions on
                    startup + on demand, before the user hits them (#3).

Smart routing (#1) lives in ``server/routes.py`` (the deterministic fast-path is
conservative and defers ambiguous input to the Ghost Agent); ``canary`` locks it
against regressions.
"""

from openjarvis.reliability.self_heal import RecoveryError, run_with_recovery
from openjarvis.reliability.health import system_health
from openjarvis.reliability.canary import run_canaries
from openjarvis.reliability.diagnose import self_diagnose

__all__ = [
    "run_with_recovery",
    "RecoveryError",
    "system_health",
    "run_canaries",
    "self_diagnose",
]
