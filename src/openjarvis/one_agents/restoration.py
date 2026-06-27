"""Removed — the RESTORATION/PUNARJEEVAN agent has been torn out.

It's being rebuilt from scratch (separate request) so credentials and the
job-execution path can be designed correctly from the start instead of
patched incrementally. All wiring that referenced this module has been
removed from:
  - one_agents/runtime.py (AGENTS dict entry, scheduler enqueue function,
    execute_job() dispatch branch)
  - server/api_routes.py (restoration_router and its request models)

This file is intentionally left as an empty stub (my file tools can't
delete files outright) rather than removed from disk. It is safe to delete
manually, or it will be overwritten once the new agent is built.
"""

from __future__ import annotations

__all__: list[str] = []
