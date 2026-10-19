"""Commercial strategy gates for Floor 5 book commissioning.

This module is deliberately pure: it cannot enqueue jobs, launch LAO, touch
KDP, or mutate the publishing workflow. It converts an evidence-backed brief
into a build/no-build decision before manuscript production starts.
"""
from __future__ import annotations

from typing import Any
import re


WEIGHTS = {
    "demand": 20,
    "buyer_intent": 20,
    "authority_fit": 15,
    "differentiation": 15,
    "packaging": 10,
    "thumbnail_clarity": 10,
    "series_fit": 5,
    "launch_readiness": 5,
}
BUILD_THRESHOLD = 85
HARD_FLOORS = {
    "buyer_intent": 70,
    "authority_fit": 80,
    "differentiation": 65,
    "thumbnail_clarity": 70,
    "launch_readiness": 70,
}
REQUIRED_EVIDENCE = {"demand_discovery", "reader_intent", "competition"}

AUTHORITY_PATTERNS = (
    r"\bwindows\b", r"\bpowershell\b", r"\bcommand[- ]line\b",
    r"\bnetwork(?:ing)?\b", r"\bsysadmin\b", r"\bworkflow automation\b",
    r"\benterprise automation\b", r"\brpa\b", r"\buipath\b",
    r"\bagentic ai\b", r"\bai agent(?:s)?\b", r"\bllmops\b",
    r"\bai governance\b", r"\bmodel governance\b",
)


def authority_fit(text: str) -> dict[str, Any]:
    """Deterministically enforce the catalogue lane; the model cannot self-score it."""
    matches = [pattern for pattern in AUTHORITY_PATTERNS
               if re.search(pattern, text, re.IGNORECASE)]
    return {"passed": bool(matches), "score": 100.0 if matches else 0.0,
            "matches": matches}


def commercial_audit(title_id: str, dimensions: dict[str, Any],
                     evidence: list[Any]) -> dict[str, Any]:
    """Fail closed on missing evidence, weak buyer intent, or weak packaging."""
    missing = [key for key in WEIGHTS if dimensions.get(key) is None]
    roles = {
        str(item.get("role") or "")
        for item in evidence
        if isinstance(item, dict)
    }
    missing_evidence = sorted(REQUIRED_EVIDENCE - roles)
    if missing or missing_evidence:
        return {
            "title_id": title_id, "score": None, "decision": "UNKNOWN",
            "build_eligible": False, "missing": missing,
            "missing_evidence": missing_evidence, "dimensions": dimensions,
            "weights": WEIGHTS, "hard_floors": HARD_FLOORS,
            "floor_failures": {}, "evidence": evidence,
        }

    normalized = {
        key: max(0.0, min(100.0, float(dimensions[key])))
        for key in WEIGHTS
    }
    score = round(sum(normalized[key] * weight / 100
                      for key, weight in WEIGHTS.items()), 2)
    floor_failures = {
        key: {"score": normalized[key], "minimum": minimum}
        for key, minimum in HARD_FLOORS.items()
        if normalized[key] < minimum
    }
    eligible = score >= BUILD_THRESHOLD and not floor_failures
    decision = (
        "SCALE" if eligible else
        "REPACKAGE" if score >= 70 else
        "REBUILD" if score >= 55 else "HOLD"
    )
    return {
        "title_id": title_id, "score": score, "decision": decision,
        "build_eligible": eligible, "missing": [], "missing_evidence": [],
        "dimensions": normalized, "weights": WEIGHTS,
        "hard_floors": HARD_FLOORS, "floor_failures": floor_failures,
        "evidence": evidence,
    }
