"""Deterministic, relevance-first YouTube Shopping plans for Sonia."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
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

_TOPIC_RULES = (
    ("universal_travel_adapter", ("socket", "plug type", "voltage", "charging abroad")),
    ("cabin_bag", ("cabin baggage", "hand baggage", "carry-on allowance")),
    ("luggage_scale", ("baggage allowance", "baggage limit", "excess baggage", "luggage weight")),
    ("packing_cubes", ("packing guide", "packing list", "what to pack")),
    ("power_bank", ("battery rule", "power bank rule", "charging on flight")),
    ("neck_pillow", ("overnight flight", "long haul", "long-haul")),
    ("rain_cover", ("monsoon travel", "heavy rain", "rainy season")),
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


def topic_intent(brief: Any) -> dict[str, str] | None:
    """Select at most one useful product category from the commissioned topic.

    This is intentionally narrower than general travel: a visa or destination
    news story does not become a shopping video merely because travellers may
    own luggage.
    """
    text = re.sub(r"\s+", " ", _text(brief or "")).lower()
    for category, phrases in _TOPIC_RULES:
        hit = next((phrase for phrase in phrases if phrase in text), "")
        if hit:
            rule = next(row for row in _RULES if row[0] == category)
            return {"category": category, "search_query": rule[1], "topic_evidence": hit}
    return None


def exact_contract(intent: dict[str, str], catalog: dict[str, str]) -> dict[str, Any]:
    title = re.sub(r"\s+", " ", str(catalog.get("title") or "")).strip()
    merchant = re.sub(r"\s+", " ", str(catalog.get("merchant") or "")).strip()
    if not title or not merchant:
        raise ValueError("Exact Shopping contract requires catalog title and merchant")
    spoken_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").strip()
    if not spoken_title:
        raise ValueError("Catalog product has no narration-safe title")
    product = {"category": intent["category"], "search_query": intent["search_query"],
               "topic_evidence": intent["topic_evidence"], "catalog_title": title,
               "spoken_title": spoken_title, "merchant": merchant, "catalog_fingerprint": hashlib.sha256(
                   f"{title}\n{merchant}".encode("utf-8")).hexdigest()}
    return {"schema": "sonia-shopping-script-contract/1", "status": "exact_product_locked",
            "product": product,
            "writer_instruction": (f"Mention the exact product name '{spoken_title}' naturally once because it is "
                                   f"directly useful to this topic. Do not claim Sonia used or endorses it."),
            "no_product_fallback": "continue the normal video without Shopping"}


def validate_script_binding(script: Any, contract: dict[str, Any] | None) -> dict[str, Any]:
    """Fail before paid narration when an exact locked product is not spoken."""
    if not contract:
        return {"bound": False, "reason": "no shopping contract; legacy/non-shopping path"}
    product = dict(contract.get("product") or {})
    exact = re.sub(r"\s+", " ", str(product.get("spoken_title") or product.get("catalog_title") or "")).strip()
    spoken = re.sub(r"[^a-z0-9]+", " ", _text(script or "").lower()).strip()
    wanted = re.sub(r"[^a-z0-9]+", " ", exact.lower()).strip()
    if contract.get("status") != "exact_product_locked" or not wanted:
        raise ValueError("Shopping contract is partial; refusing narration")
    if wanted not in spoken:
        raise ValueError(f"Approved script does not speak the exact locked product: {exact}")
    script_sha = hashlib.sha256(_text(script or "").strip().encode("utf-8")).hexdigest()
    return {"bound": True, "catalog_fingerprint": product.get("catalog_fingerprint"),
            "script_sha256": script_sha, "catalog_title": exact, "merchant": product.get("merchant")}


def attach_to_package(package: dict[str, Any], *, script: Any, owner: str,
                      content_format: str, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    if contract:
        binding = validate_script_binding(script, contract)
        product = dict(contract["product"])
        package["shopping"] = {
            "schema": SCHEMA, "owner": owner, "content_format": content_format,
            "video_title": str(package.get("recommended_title") or ""), "status": "planned_exact",
            "eligibility": "strong", "script_binding": binding,
            "policy": {"relevance_required": True, "spoken_evidence_required": True,
                       "exact_catalog_match_required": True, "commission_is_tiebreaker_only": True,
                       "publish_without_products_on_no_match": True,
                       "never_repeat_upload_for_shopping": True,
                       "max_tags": 1 if content_format == "youtube_short" else 3},
            "candidates": [{"category": product["category"], "search_query": product["search_query"],
                            "required": False, "catalog_title": product["catalog_title"],
                            "spoken_title": product["spoken_title"],
                            "merchant": product["merchant"],
                            "catalog_fingerprint": product["catalog_fingerprint"],
                            "evidence": {"source": "pre_script_catalog_contract",
                                         "matched_phrase": product["catalog_title"],
                                         "snippet": product["topic_evidence"]}}],
        }
    else:
        detected = build_plan(script=script, title=str(package.get("recommended_title") or ""),
                              content_format=content_format, owner=owner)
        package["shopping"] = {
            **detected,
            "status": "skipped_no_exact_catalog_contract",
            "eligibility": "none",
            "candidates": [],
            "detected_unbound_categories": [row["category"] for row in detected["candidates"]],
            "skip_reason": "A spoken category without a pre-script exact catalog lock is not taggable",
        }
    return package


def write_plan(package_path: Path, plan: dict[str, Any]) -> Path:
    path = package_path.with_name("shopping-plan.json")
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def plan_hash(plan: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
