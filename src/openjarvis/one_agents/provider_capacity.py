"""Durable fail-closed gates for exhausted paid external providers.

Provider exhaustion is not a code defect.  Retrying it can spend time, create
duplicate paid work, and hide the one action that can actually unblock the
pipeline.  These receipts deliberately store only a provider key and a short
operator-safe reason; screenshots, prompts, credentials, and account details
never belong here.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ProviderCapacityBlocked(RuntimeError):
    """Raised before a new paid provider job can be started."""


def _home() -> Path:
    return Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))


def _safe_provider(provider: str) -> str:
    normalized = "".join(ch for ch in str(provider).casefold() if ch.isalnum() or ch in "-_")
    if not normalized:
        raise ValueError("provider name is required")
    return normalized[:80]


def _path(provider: str) -> Path:
    return _home() / "provider_capacity_blocks" / f"{_safe_provider(provider)}.json"


def active_block(provider: str) -> dict[str, Any] | None:
    path = _path(provider)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return record if record.get("status") == "blocked" else None


def record_block(provider: str, *, reason: str, evidence_kind: str,
                 source_job: str = "") -> dict[str, Any]:
    """Atomically stop new paid starts until a verified capacity check clears it."""
    path = _path(provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "provider": _safe_provider(provider),
        "status": "blocked",
        "reason": str(reason or "provider capacity unavailable").splitlines()[0][:240],
        "evidence_kind": str(evidence_kind or "provider_response")[:80],
        "source_job": str(source_job or "")[:120],
        "blocked_at": datetime.now(timezone.utc).isoformat(),
        "clearance": "verified_capacity_check_required",
    }
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return record


def clear_block(provider: str, *, capacity_verified: bool) -> bool:
    """Clear only after an explicit, successful provider-capacity verification."""
    if not capacity_verified:
        raise ValueError("provider block requires verified capacity before clearing")
    try:
        _path(provider).unlink()
        return True
    except FileNotFoundError:
        return False


def require_available(provider: str) -> None:
    record = active_block(provider)
    if not record:
        return
    raise ProviderCapacityBlocked(
        f"{record['provider']} capacity is blocked: {record.get('reason') or 'capacity unavailable'}; "
        "a verified provider-capacity check is required before another paid start"
    )
