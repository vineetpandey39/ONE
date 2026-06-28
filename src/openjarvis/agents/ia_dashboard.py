"""Dashboard visibility bridge for the IA pipeline.

IA is a deterministic, code-driven agent registered in
``AgentRegistry`` -- it has no row in the ``managed_agents`` SQLite table
that the desktop app's Agents page (``/v1/managed-agents``) reads from, so
it is invisible on screen no matter how it's invoked (CLI, scheduler).

Rather than rebuild IA as an LLM tool-calling "managed agent"
(which would mean trusting an LLM to call image_generate /
leonardo_video_generate / video_merge in the right order every run instead
of a fixed deterministic sequence), this module keeps the deterministic
pipeline as-is and just *mirrors* its progress into one managed-agent
record so it shows up as a normal card on the dashboard, with real
status/activity-log/run-history.

Best-effort only: any failure here is logged and swallowed -- a dashboard
visibility hiccup must never break the actual reel pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DASHBOARD_AGENT_NAME = "IA"
_manager_cache = None


def _resolve_db_path() -> str:
    from openjarvis.core.config import load_config
    from openjarvis.core.paths import get_config_dir

    try:
        config = load_config()
        return config.agent_manager.db_path or str(get_config_dir() / "agents.db")
    except Exception:
        return str(get_config_dir() / "agents.db")


def _get_manager():
    """Lazily open (and cache) the same agents.db the server/dashboard uses."""
    global _manager_cache
    if _manager_cache is not None:
        return _manager_cache
    from openjarvis.agents.manager import AgentManager

    _manager_cache = AgentManager(db_path=_resolve_db_path())
    return _manager_cache


def _get_or_create_record(manager) -> Optional[str]:
    try:
        for agent in manager.list_agents(include_archived=True):
            if agent.get("name") == _DASHBOARD_AGENT_NAME:
                return agent["id"]
        created = manager.create_agent(
            name=_DASHBOARD_AGENT_NAME,
            agent_type="monitor_operative",
            config={
                "description": (
                    "Universal restoration-reel pipeline. Runs twice daily via "
                    "the scheduler -- this card mirrors a deterministic "
                    "image -> video -> reel pipeline; it does not chat or "
                    "decide its own tool order."
                ),
                "managed_externally": True,
            },
        )
        return created["id"]
    except Exception as exc:
        logger.warning("IA dashboard bridge: could not get/create record: %s", exc)
        return None


class DashboardRun:
    """Context-manager-free helper tracking one IA run's dashboard state."""

    def __init__(self) -> None:
        self.agent_id: Optional[str] = None
        self._manager = None
        self._tick_held = False
        try:
            self._manager = _get_manager()
            self.agent_id = _get_or_create_record(self._manager)
            if self.agent_id:
                try:
                    self._manager.start_tick(self.agent_id)
                    self._tick_held = True
                except ValueError:
                    # Already "running" (e.g. overlapping scheduler runs) --
                    # don't block the pipeline over a UI status flag.
                    pass
        except Exception as exc:
            logger.warning("IA dashboard bridge: init failed: %s", exc)

    def log(self, event_type: str, description: str, data: Optional[Dict[str, Any]] = None) -> None:
        if not (self._manager and self.agent_id):
            return
        try:
            self._manager.update_agent(self.agent_id, current_activity=description)
            self._manager.add_learning_log(self.agent_id, event_type, description, data or {})
        except Exception as exc:
            logger.warning("IA dashboard bridge: log failed: %s", exc)

    def finish(
        self,
        *,
        success: bool,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if not (self._manager and self.agent_id):
            return
        try:
            self._manager.store_agent_response(self.agent_id, content, tool_calls=tool_calls)
            self._manager.update_agent(self.agent_id, total_runs_increment=1)
            if self._tick_held:
                self._manager.end_tick(self.agent_id)
            self._manager.update_agent(
                self.agent_id,
                status="idle" if success else "error",
                current_activity="",
            )
        except Exception as exc:
            logger.warning("IA dashboard bridge: finish failed: %s", exc)


__all__ = ["DashboardRun"]
