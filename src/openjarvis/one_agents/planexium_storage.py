"""Conservative storage reclamation for completed PLANEXIUM missions.

Only reproducible media from independently verified private deliveries is
eligible.  Masters, narration, thumbnails, metadata, QC, checkpoints and JSON
provider receipts are never removed.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


MEDIA_SUFFIXES = {".aac", ".m4a", ".mkv", ".mov", ".mp3", ".mp4", ".mxf", ".wav", ".webm"}


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _eligible(mission: Path, *, now: datetime, minimum_age_seconds: int) -> bool:
    health = _read(mission / "production-health.json")
    gate = _read(mission / "review-gate.json")
    master = mission / "edit" / "master.mp4"
    if not master.is_file() or health.get("status") != "uploaded_private":
        return False
    if (health.get("production_complete") is not True or health.get("uploaded") is not True
            or not health.get("private_video_id") or health.get("published") is not False):
        return False
    if (gate.get("private_upload_complete") is not True
            or gate.get("private_video_id") != health.get("private_video_id")):
        return False
    try:
        updated = datetime.fromisoformat(str(health["updated_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return False
    if (now - updated.astimezone(timezone.utc)).total_seconds() < minimum_age_seconds:
        return False
    master_hash = _sha256(master)
    ledger = _read(mission / "upload-ledger.json")
    delivery = ledger.get(master_hash)
    return bool(isinstance(delivery, dict)
                and delivery.get("video_id") == health.get("private_video_id")
                and delivery.get("privacy") == "private"
                and delivery.get("thumbnail_set") is True
                and delivery.get("delivery_verified_at")
                and any(str(key).startswith("caption_") for key in delivery))


def sweep_finished_missions(root: Path, current_mission: str, *, minimum_age_seconds: int = 600) -> dict:
    """Remove only reproducible media from older verified private missions."""
    root = Path(root).resolve()
    now = datetime.now(timezone.utc)
    freed = 0
    cleaned: list[str] = []
    if not root.is_dir():
        return {"freed_bytes": 0, "missions_cleaned": 0, "skipped": "mission root is unavailable"}
    for mission in sorted(root.glob("daily-*")):
        if (not mission.is_dir() or mission.name == current_mission
                or mission.parent.resolve() != root
                or not _eligible(mission, now=now, minimum_age_seconds=minimum_age_seconds)):
            continue
        targets = [mission / "edit" / "cinematic", mission / "edit" / "picture.mp4",
                   mission / "edit" / "soundtrack.m4a", mission / "edit" / "music-bed.m4a"]
        before = 0
        for target in targets:
            if target.is_dir():
                before += sum(path.stat().st_size for path in target.rglob("*") if path.is_file())
                shutil.rmtree(target)
            elif target.is_file():
                before += target.stat().st_size
                target.unlink()
        assets = mission / "cinematic-assets"
        if assets.is_dir():
            for path in list(assets.rglob("*")):
                if path.is_file() and path.suffix.casefold() in MEDIA_SUFFIXES:
                    before += path.stat().st_size
                    path.unlink()
        if before:
            freed += before
            cleaned.append(mission.name)
    return {"freed_bytes": freed, "missions_cleaned": len(cleaned), "missions": cleaned,
            "preserved": ["master", "narration", "thumbnails", "metadata", "QC", "checkpoints", "JSON receipts"]}
