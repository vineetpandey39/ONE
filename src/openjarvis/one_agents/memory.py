"""Company memory — every agent's work, written into the Obsidian vault.

Agent output used to land in `agent_outputs/*.md`, keyed by job id: fine for
debugging, useless as memory. Nothing linked, nothing searchable by topic, and
an agent had no way to know what it had already decided last month.

This writes the same work into the vault instead, as dated notes filed by
floor, so it becomes part of the same knowledge base ONE already searches —
and so an agent can read its own history before repeating itself.

Layout:
    Company/
      Floor 05 - Book Publishing (KDP)/
        2026-08-10 HERMES - Commissioning Brief.md
        2026-08-10 SCRIBE - Delivery.md

Never raises: memory is a side effect of doing the work, and failing to
record it must never fail the work itself.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from openjarvis.one_agents.obsidian import (
    obsidian_status,
    search_obsidian,
    write_obsidian_file,
)

COMPANY_ROOT = "Company"


def _slug(value: str) -> str:
    """Filesystem-safe fragment that still reads as English in the vault."""
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "")).strip()
    return re.sub(r"\s+", " ", cleaned)[:80] or "Untitled"


def floor_folder(floor_id: str, floor_name: str) -> str:
    # Zero-pad numeric floors so the vault sorts B1/B2/01..11 sensibly.
    label = floor_id.zfill(2) if floor_id.isdigit() else floor_id.upper()
    return f"{COMPANY_ROOT}/Floor {label} - {_slug(floor_name)}"


def remember(
    *,
    agent: str,
    floor_id: str,
    floor_name: str,
    kind: str,
    body: str,
    task: str = "",
    links: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Write one piece of agent work into the vault.

    ``kind`` becomes part of the note title ("Commissioning Brief",
    "Delivery", "Report"), so a floor's folder reads as a work diary.
    """
    try:
        if not obsidian_status().get("connected"):
            return {"saved": False, "reason": "vault not connected"}

        now = datetime.now().astimezone()
        folder = floor_folder(floor_id, floor_name)
        title = f"{now:%Y-%m-%d %H%M} {agent} - {_slug(kind)}"
        path = f"{folder}/{title}.md"

        front = [
            f"# {agent} — {kind}",
            "",
            f"- **Floor:** {floor_id} — {floor_name}",
            f"- **Agent:** {agent}",
            f"- **When:** {now:%Y-%m-%d %H:%M %Z}",
        ]
        if task:
            front.append(f"- **Asked:** {' '.join(str(task).split())[:300]}")
        if links:
            front.append("- **Related:** " + " ".join(f"[[{l}]]" for l in links))
        if tags:
            front.append("")
            front.append(" ".join(f"#{t}" for t in tags))
        front += ["", "---", "", body.strip(), ""]

        # A same-minute collision would otherwise raise on create.
        try:
            result = write_obsidian_file(path, "\n".join(front), mode="create")
        except ValueError:
            path = f"{folder}/{title} ({now:%S}s).md"
            result = write_obsidian_file(path, "\n".join(front), mode="create")
        result["note"] = title
        return result
    except Exception as exc:  # noqa: BLE001 - memory must never break the job
        return {"saved": False, "reason": str(exc)}


def recall(query: str, limit: int = 6) -> list[dict[str, Any]]:
    """Prior company notes matching a topic. Empty list on any failure."""
    try:
        if not obsidian_status().get("connected"):
            return []
        hits = search_obsidian(query, limit=limit * 3)
        # Only the company's own working notes, not the whole vault.
        company = [h for h in hits if str(h.get("path", "")).startswith(COMPANY_ROOT)]
        return company[:limit]
    except Exception:  # noqa: BLE001
        return []


def prior_titles(floor_id: str, floor_name: str, limit: int = 25) -> list[str]:
    """Titles this floor has already commissioned, newest first.

    Used to stop an agent proposing the same book twice — reading its own
    history is what makes the vault memory rather than a log.
    """
    try:
        status = obsidian_status()
        if not status.get("connected"):
            return []
        from pathlib import Path

        folder = Path(status["path"]) / floor_folder(floor_id, floor_name)
        if not folder.is_dir():
            return []
        notes = sorted(folder.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        titles: list[str] = []
        for note in notes[:limit]:
            try:
                text = note.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            match = re.search(r"^ANGLE:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
            if match:
                titles.append(match.group(1).strip())
        return titles
    except Exception:  # noqa: BLE001
        return []
