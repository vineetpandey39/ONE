"""Hash-bound handoff contracts for YATRA's dedicated OCULUS capture worker.

OCULUS owns only official-page OBS recording and capture QC.  Keeping these
contracts outside ``runtime.py`` makes the agent boundary explicit and lets a
failed capture resume without replaying narration, acquisition, or editing.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VISUALS_SCHEMA = "yatra-to-oculus/1"
CAPTURE_SCHEMA = "oculus-to-yatra-render/1"


def sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _atomic_json(path: Path, body: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def _binding(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"required handoff artifact is missing: {path}")
    return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}


def write_visuals_receipt(*, asset_root: Path, checkpoint: str, source_job: str,
                          plan: Path, narration_manifest: Path, obs_plan: Path,
                          context: dict[str, Any]) -> Path:
    receipt = asset_root / "captures" / "yatra-visuals-receipt.json"
    body = {
        "schema": VISUALS_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checkpoint": checkpoint,
        "source_job": source_job,
        "asset_root": str(asset_root),
        "bindings": {
            "plan": _binding(plan),
            "narration_manifest": _binding(narration_manifest),
            "obs_plan": _binding(obs_plan),
        },
        "context": context,
    }
    return _atomic_json(receipt, body)


def validate_visuals_receipt(path: Path, *, checkpoint: str, asset_root: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"OCULUS needs YATRA's visual handoff receipt: {path}")
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("schema") != VISUALS_SCHEMA or str(body.get("checkpoint")) != str(checkpoint):
        raise RuntimeError("YATRA visual receipt schema/checkpoint mismatch")
    if Path(str(body.get("asset_root") or "")).resolve() != asset_root.resolve():
        raise RuntimeError("YATRA visual receipt points at a different production folder")
    for name, binding in (body.get("bindings") or {}).items():
        artifact = Path(str(binding.get("path") or ""))
        if not artifact.is_file() or sha256_file(artifact) != str(binding.get("sha256") or ""):
            raise RuntimeError(f"YATRA visual receipt binding changed: {name}")
    return body


def write_capture_receipt(*, asset_root: Path, checkpoint: str, source_job: str,
                          visuals_receipt: Path, integrity: dict[str, Any]) -> Path:
    recordings: list[dict[str, Any]] = []
    for row in integrity.get("semantic_receipts") or []:
        capture_id = str(row.get("capture_id") or "")
        matches = [p for p in (asset_root / "captures").glob(f"{capture_id}-capture.*")
                   if p.is_file() and p.suffix.lower() in {".mkv", ".mp4", ".mov"}]
        if len(matches) != 1:
            raise RuntimeError(f"OCULUS receipt expected one recording for {capture_id}, found {len(matches)}")
        recording = _binding(matches[0])
        recording["capture_id"] = capture_id
        recordings.append(recording)
    body = {
        "schema": CAPTURE_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checkpoint": checkpoint,
        "source_job": source_job,
        "asset_root": str(asset_root),
        "visuals_receipt": _binding(visuals_receipt),
        "semantic_qc": _binding(Path(str(integrity.get("receipt") or ""))),
        "recordings": recordings,
        "capture_count": int(integrity.get("captures") or 0),
        "status": "passed" if integrity.get("ok") else "failed",
    }
    if body["status"] != "passed":
        raise RuntimeError("OCULUS cannot issue a render receipt for failed capture integrity")
    return _atomic_json(asset_root / "captures" / "oculus-receipt.json", body)


def validate_capture_receipt(path: Path, *, checkpoint: str, asset_root: Path,
                             visuals_receipt: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"YATRA render needs OCULUS's capture receipt: {path}")
    body = json.loads(path.read_text(encoding="utf-8"))
    if (body.get("schema") != CAPTURE_SCHEMA or body.get("status") != "passed"
            or str(body.get("checkpoint")) != str(checkpoint)):
        raise RuntimeError("OCULUS receipt is not a passed receipt for this checkpoint")
    if Path(str(body.get("asset_root") or "")).resolve() != asset_root.resolve():
        raise RuntimeError("OCULUS receipt points at a different production folder")
    visual_binding = body.get("visuals_receipt") or {}
    if (Path(str(visual_binding.get("path") or "")).resolve() != visuals_receipt.resolve()
            or not visuals_receipt.is_file()
            or sha256_file(visuals_receipt) != str(visual_binding.get("sha256") or "")):
        raise RuntimeError("OCULUS receipt is not bound to the current YATRA visual receipt")
    for recording in body.get("recordings") or []:
        media = Path(str(recording.get("path") or ""))
        if not media.is_file() or sha256_file(media) != str(recording.get("sha256") or ""):
            raise RuntimeError(f"OCULUS recording changed after QC: {recording.get('capture_id')}")
    semantic = body.get("semantic_qc") or {}
    semantic_path = Path(str(semantic.get("path") or ""))
    if not semantic_path.is_file() or sha256_file(semantic_path) != str(semantic.get("sha256") or ""):
        raise RuntimeError("OCULUS semantic-QC receipt changed after handoff")
    return body
