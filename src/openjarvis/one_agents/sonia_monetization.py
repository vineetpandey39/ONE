"""Durable Sonia monetization scorecard updated by daily production agents."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCES = {
    "watch_page_ads": {"state": "active", "agent_action": "YATRA keeps long videos eligible and supports mid-roll review above 8 minutes"},
    "shorts_feed_ads": {"state": "active", "agent_action": "VISTA produces original policy-safe Shorts"},
    "shopping_affiliate": {"state": "active", "agent_action": "LYRA/ARES plan relevant products; ECHO attaches and verifies them"},
    "memberships": {"state": "studio_review_required", "agent_action": "HELIOS may draft perks; activation and pricing require operator review"},
    "supers_and_gifts": {"state": "studio_review_required", "agent_action": "ECHO never enables financial features silently"},
    "brand_partnerships": {"state": "studio_review_required", "agent_action": "HELIOS prepares a media-kit lead only; no outreach without authorization"},
    "external_affiliates": {"state": "not_agent_authorized", "agent_action": "No off-platform tracking links are inserted without an approved account and disclosure"},
}


def record(package_path: Path, *, video_id: str, shopping: dict[str, Any]) -> Path:
    path = package_path.with_name("monetization-scorecard.json")
    body = {"schema": "sonia-monetization-scorecard/1", "recorded_at": datetime.now(timezone.utc).isoformat(),
            "video_id": video_id, "shopping": shopping, "income_sources": SOURCES,
            "operator_actions": [
                "Review Memberships eligibility, perk workload and pricing in Studio",
                "Review Supers & gifts eligibility and tax/payment setup in Studio",
                "Review Partnerships/channel-insights sharing and create a current media kit",
            ],
            "guardrails": ["No irrelevant product tags", "No false personal endorsement",
                           "No duplicate upload for monetization metadata", "No public publish by this stage"]}
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
