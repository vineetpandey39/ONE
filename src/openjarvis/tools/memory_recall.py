"""Date-aware recall of ONE's past conversations from the Obsidian journals.

ONE already saves every exchange into dated journals
(``{vault}/Memory/YYYY/MM/YYYY-MM-DD - ONE Journal.md`` via
one_agents.obsidian.remember_exchange). The gap was recall: when Sir asked
"what did we discuss yesterday?", ONE only had keyword search, which can't map
"yesterday" onto a date/file, so it wrongly claimed there was no log. This tool
resolves natural time references (yesterday, last week, a specific date, in
English or Hinglish) to the right journal file(s) and returns their content so
the Ghost Agent can answer accurately instead of guessing.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_MAX_TOTAL_CHARS = 6000
_MAX_PER_DAY_CHARS = 2600


def _resolve_dates(when: str, today: date) -> tuple[list[date], str]:
    """Map a natural time phrase to concrete dates (most recent first)."""
    w = (when or "").strip().lower()

    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", w)
    if m:
        try:
            return [date(int(m.group(1)), int(m.group(2)), int(m.group(3)))], "specific date"
        except ValueError:
            pass
    m = re.search(r"last\s+(\d{1,2})\s+day", w)
    if m:
        n = max(1, min(int(m.group(1)), 31))
        return [today - timedelta(days=i) for i in range(1, n + 1)], f"last {n} days"

    if any(k in w for k in ("day before yesterday", "parso", "parson")):
        return [today - timedelta(days=2)], "day before yesterday"
    if any(k in w for k in ("yesterday", "kal", "kl", "beeta din")):
        return [today - timedelta(days=1)], "yesterday"
    if any(k in w for k in ("today", "aaj", "abhi", "aj")):
        return [today], "today"
    if any(k in w for k in ("last week", "past week", "previous week", "pichle hafte", "pichhle hafte", "last 7")):
        return [today - timedelta(days=i) for i in range(1, 8)], "last week"
    if any(k in w for k in ("this week", "is hafte", "es hafte")):
        return [today - timedelta(days=i) for i in range(0, today.weekday() + 1)], "this week"
    if any(k in w for k in ("last month", "pichle mahine", "past month")):
        return [today - timedelta(days=i) for i in range(1, 31)], "last month"

    # Sensible default: today + yesterday.
    return [today, today - timedelta(days=1)], "recent days"


def _journal_path(vault: Path, d: date) -> Path:
    return vault / "Memory" / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.strftime('%Y-%m-%d')} - ONE Journal.md"


@ToolRegistry.register("recall_memory")
class MemoryRecallTool(BaseTool):
    """Read ONE's own saved conversation journals for a given day/period."""

    tool_id = "recall_memory"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="recall_memory",
            description=(
                "Recall what you and Sir actually talked about on a past day or period, "
                "by reading ONE's own saved conversation journals. ALWAYS call this before "
                "answering any question about past conversations -- 'what did we discuss "
                "yesterday / last week / on <date>', 'kal / pichle hafte kya baat hui', "
                "'remind me what we decided about X'. Never claim there is no log without "
                "calling this first. Returns the real journal text; summarise it for Sir."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "when": {
                        "type": "string",
                        "description": (
                            "The time reference to recall, e.g. 'yesterday', 'today', "
                            "'last week', 'last 3 days', or a date '2026-08-03'. "
                            "Hinglish (kal, aaj, pichle hafte, parso) is understood."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional topic to focus on within that period (e.g. 'ALFA', 'the reel').",
                    },
                },
                "required": ["when"],
            },
            category="memory",
            cost_estimate=0.0,
            timeout_seconds=10,
        )

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.one_agents.obsidian import obsidian_status

        status = obsidian_status()
        if not status.get("connected"):
            return ToolResult(
                tool_name=self.tool_id,
                content="Obsidian memory vault is not connected, so I can't read past conversations. Connect the vault on the /credentials or memory page first.",
                success=False,
            )
        vault = Path(status["path"])
        when = str(params.get("when") or "recent")
        query = str(params.get("query") or "").strip()
        today = datetime.now().astimezone().date()
        dates, label = _resolve_dates(when, today)

        chunks: list[str] = []
        found_days: list[str] = []
        missing_days: list[str] = []
        total = 0
        for d in dates:
            p = _journal_path(vault, d)
            if not p.is_file():
                missing_days.append(d.strftime("%Y-%m-%d"))
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore").strip()
            except OSError:
                missing_days.append(d.strftime("%Y-%m-%d"))
                continue
            if query:
                # keep only entries (## HH:MM:SS blocks) mentioning the topic
                blocks = re.split(r"(?=^## )", text, flags=re.MULTILINE)
                kept = [b for b in blocks if query.lower() in b.lower()]
                if kept:
                    text = "".join(kept).strip()
                elif query.lower() not in text.lower():
                    # topic not on this day; skip it from the focused view
                    continue
            if len(text) > _MAX_PER_DAY_CHARS:
                text = text[:_MAX_PER_DAY_CHARS] + "\n…(truncated)…"
            found_days.append(d.strftime("%A %Y-%m-%d"))
            chunks.append(f"===== {d.strftime('%A, %d %B %Y')} =====\n{text}")
            total += len(text)
            if total >= _MAX_TOTAL_CHARS:
                break

        if not chunks:
            miss = f" (checked: {', '.join(missing_days)})" if missing_days else ""
            focus = f" about '{query}'" if query else ""
            return ToolResult(
                tool_name=self.tool_id,
                content=f"No saved conversation was found for {label}{focus}{miss}.",
                success=True,
            )

        header = f"Recovered conversation journal(s) for {label}"
        if query:
            header += f", focused on '{query}'"
        header += f" — days with a log: {', '.join(found_days)}."
        body = "\n\n".join(chunks)[:_MAX_TOTAL_CHARS]
        return ToolResult(tool_name=self.tool_id, content=f"{header}\n\n{body}", success=True)


__all__ = ["MemoryRecallTool"]
