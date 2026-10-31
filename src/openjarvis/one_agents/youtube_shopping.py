"""Deterministic, relevance-first YouTube Shopping plans for Sonia."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "sonia-shopping-plan/1"
_RULES = (
    ("universal_travel_adapter", "universal travel adapter India", ("travel adapter", "plug adapter", "universal adapter", "power socket")),
    ("luggage_scale", "digital luggage weighing scale", ("luggage scale", "weighing scale", "baggage weight", "excess baggage")),
    ("packing_cubes", "travel packing cubes", ("packing cube", "packing cubes", "organise your suitcase", "organize your suitcase")),
    ("power_bank", "travel power bank", ("power bank", "portable charger")),
    ("travel_document_organizer", "passport travel document organizer", ("passport organizer", "passport holder", "document organizer", "travel wallet")),
    ("neck_pillow", "travel neck pillow", ("neck pillow", "travel pillow")),
    ("cabin_bag", "cabin luggage bag", ("cabin bag", "carry-on bag", "carry on bag")),
    ("rain_cover", "waterproof backpack rain cover", ("rain cover", "waterproof backpack cover")),
)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _snippet(text: str, needle: str) -> str:
    at = text.lower().find(needle)
    return re.sub(r"\s+", " ", text[max(0, at - 95): at + len(needle) + 95]).strip()


def build_plan(*, script: Any, title: str = "", content_format: str = "youtube_long",
               owner: str = "LYRA") -> dict[str, Any]:
    text = _text(script or "")
    normalized = re.sub(r"\s+", " ", text).lower()
    candidates = []
    for category, query, phrases in _RULES:
        hit = next((phrase for phrase in phrases if phrase in normalized), "")
        if hit:
            candidates.append({"category": category, "search_query": query, "required": False,
                               "evidence": {"source": "spoken_script", "matched_phrase": hit,
                                            "snippet": _snippet(text, hit)}})
    limit = 1 if content_format == "youtube_short" else 3
    candidates = candidates[:limit]
    return {"schema": SCHEMA, "owner": owner, "content_format": content_format, "video_title": title,
            "status": "planned" if candidates else "skipped_no_relevant_product",
            "eligibility": "strong" if len(candidates) >= 2 else ("contextual" if candidates else "none"),
            "policy": {"relevance_required": True, "spoken_evidence_required": True,
                       "commission_is_tiebreaker_only": True, "publish_without_products_on_no_match": True,
                       "never_repeat_upload_for_shopping": True, "max_tags": limit},
            "merchant_preferences": ["Amazon India", "Flipkart", "Myntra"], "candidates": candidates}


def attach_to_package(package: dict[str, Any], *, script: Any, owner: str,
                      content_format: str) -> dict[str, Any]:
    package["shopping"] = build_plan(script=script, title=str(package.get("recommended_title") or ""),
                                     content_format=content_format, owner=owner)
    return package


def write_plan(package_path: Path, plan: dict[str, Any]) -> Path:
    path = package_path.with_name("shopping-plan.json")
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def plan_hash(plan: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
