"""Truthful YouTube-native thumbnail A/B/C experiment contract.

The Data API can set one thumbnail, but it cannot create YouTube Studio's
concurrent thumbnail test.  ARES therefore seals three QC-passed candidates,
ECHO uploads the editorial winner on the private draft, and the Studio stage
may start the native test only after the video is an eligible public long-form
video.  YouTube owns the watch-time-share measurement and winner selection;
we never turn a design-readiness score into a pretend audience result.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "sonia-youtube-thumbnail-ab/1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_plan(root: Path, receipt: dict[str, Any], *, visibility: str = "private",
               content_format: str = "long_form") -> dict[str, Any]:
    """Seal exactly three real candidates, with the editorial winner first."""
    root = Path(root)
    variants: list[dict[str, Any]] = []
    blockers: list[str] = []
    for row in receipt.get("variants") or []:
        path = Path(str(row.get("path") or ""))
        if not row.get("ok") or not path.is_file():
            continue
        if row.get("source") == "local_fallback":
            continue
        variants.append({
            "name": str(row.get("variant") or path.stem),
            "path": str(path.resolve()),
            "sha256": _sha256(path),
            "qc": row.get("qc") or {},
            "preupload_score": row.get("preupload_score") or {},
        })
    if len(variants) != 3:
        blockers.append(f"native A/B/C requires exactly 3 generated QC-passed thumbnails (found {len(variants)})")
    elif len({row["sha256"] for row in variants}) != 3:
        blockers.append("native A/B/C candidates are not visually distinct files")

    winner = str(receipt.get("winner") or "")
    variants.sort(key=lambda row: (row["name"] != winner, -float((row["preupload_score"] or {}).get("score") or 0)))
    for index, row in enumerate(variants, 1):
        row["position"] = index
        row["editorial_default"] = index == 1

    eligibility = {
        "visibility": visibility,
        "content_format": content_format,
        "requires_public": True,
        "requires_long_form": True,
        "private_draft_eligible": False,
    }
    if content_format == "youtube_short":
        blockers.append("YouTube native thumbnail testing is not available for Shorts")
    if blockers:
        status = "blocked"
    elif visibility != "public":
        status = "waiting_for_public"
    else:
        status = "ready_for_studio"
    plan = {
        "schema": SCHEMA,
        "status": status,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "platform": "youtube_studio_native_test_and_compare",
        "measurement": "watch_time_share",
        "data_api_can_start_test": False,
        "candidates": variants,
        "editorial_default": variants[0]["path"] if variants else None,
        "eligibility": eligibility,
        "blockers": blockers,
        "winner_policy": (
            "YouTube automatically applies the highest watch-time-share winner. "
            "If YouTube reports same or inconclusive, keep candidate 1. Never simulate this by sequential rotation."
        ),
        "result": None,
    }
    out = root / "thumbnail" / "native-ab-test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    plan["path"] = str(out)
    return plan


def mark_private_upload(plan: dict[str, Any], *, video_id: str | None, studio_url: str | None) -> dict[str, Any]:
    """Bind the sealed candidates to the private draft without claiming that a test has started."""
    updated = dict(plan)
    updated.update(status="waiting_for_public", video_id=video_id, studio_url=studio_url,
                   private_thumbnail=plan.get("editorial_default"))
    raw_path = str(plan.get("path") or "").strip()
    if raw_path:
        path = Path(raw_path)
        persisted = {k: v for k, v in updated.items() if k != "path"}
        path.write_text(json.dumps(persisted, ensure_ascii=False, indent=2), encoding="utf-8")
    return updated
