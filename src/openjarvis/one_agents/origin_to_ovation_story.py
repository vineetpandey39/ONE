"""Evidence-led story contract for Origin to Ovation long-form biographies.

This module deliberately avoids universal retention targets.  YouTube does not
publish a credible "90% AVD" benchmark for 10--12 minute biographies; each
episode is improved against its own traffic-source and retention evidence.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

OFFICIAL_MODEL = {
    "appeal": "A truthful title/thumbnail promise that earns the intended viewer's choice",
    "engagement": "A promise-matched first 30 seconds and a story that keeps earning attention",
    "satisfaction": "A complete, accurate payoff and a useful next-video path",
    "sources": [
        "https://support.google.com/youtube/answer/16559650",
        "https://support.google.com/youtube/answer/9314415",
        "https://support.google.com/youtube/answer/16533387",
    ],
}

BEAT_CYCLE = ("problem", "attempt", "setback", "turning_point", "payoff")
PATTERN_INTERRUPTS = (
    "scale_change", "time_or_score_graphic", "environmental_insert",
    "sound_or_silence_shift", "camera_grammar_change",
)

NARRATION_RULES = (
    "Third-person English narration; emotionally specific, conversational and restrained. "
    "Humanise through documented choices, effort, consequences and relationships. Never invent dialogue, "
    "private thoughts, motives or convenient drama. Attribute recollections. Every factual beat carries claim_ids."
)


def _chapters(plan: list[dict[str, Any]]) -> list[tuple[int, list[dict[str, Any]]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for shot in plan:
        grouped[int(shot.get("chapter", 0))].append(shot)
    return sorted(grouped.items())


def annotate_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add editorial intent without changing sourced narration or provider paths."""
    chapters = _chapters(plan)
    total = max(len(plan), 1)
    ordinal = 0
    for chapter_no, shots in chapters:
        for within, shot in enumerate(shots):
            progress = ordinal / total
            if chapter_no == chapters[0][0]:
                role = ("cold_open_payoff", "promise_proof", "stakes", "central_question", "story_launch")[min(within, 4)]
            elif chapter_no == chapters[-1][0]:
                role = ("final_escalation", "records_payoff", "meaning", "earned_resolution", "next_story_cta")[min(within, 4)]
            else:
                role = BEAT_CYCLE[within % len(BEAT_CYCLE)]
            shot["story"] = {
                "role": role,
                "open_loop": role in {"cold_open_payoff", "problem", "setback", "central_question"},
                "must_pay_off_with_documented_fact": True,
                "pattern_interrupt": PATTERN_INTERRUPTS[(chapter_no + within) % len(PATTERN_INTERRUPTS)],
                "retention_checkpoint": round(progress, 3),
            }
            ordinal += 1
    return plan


def build_contract(plan: list[dict[str, Any]], metadata: dict[str, Any], subject: str) -> dict[str, Any]:
    annotate_plan(plan)
    chapters = _chapters(plan)
    title = metadata.get("title") or (metadata.get("title_options") or [f"{subject}: The Journey"])[0]
    central_question = metadata.get("central_dramatic_question") or (
        f"What did {subject} have to overcome, change or sustain to fulfil the promise made by “{title}”?"
    )
    checkpoints = []
    for number, shots in chapters:
        checkpoints.append({
            "chapter": number,
            "title": shots[0].get("chapter_title", f"Chapter {number}"),
            "start_shot": shots[0].get("shot_id"),
            "end_shot": shots[-1].get("shot_id"),
            "beat_sequence": [s["story"]["role"] for s in shots],
            "required_payoff_claim_ids": sorted({c for s in shots for c in s.get("claim_ids", [])}),
        })
    return {
        "version": "oto-story-2026.1",
        "benchmark_policy": "No public 90% AVD claim. Improve against channel/video baselines and similar-length comparisons.",
        "youtube_model": OFFICIAL_MODEL,
        "packaging_promise": {"title": title, "first_30_seconds_must_prove_title_and_thumbnail": True},
        "central_dramatic_question": central_question,
        "narration": NARRATION_RULES,
        "story_engine": "cold-open payoff -> central question -> repeated problem/attempt/setback/turning-point/payoff loops -> escalating milestones -> records-led resolution -> next-story CTA",
        "retention_map": checkpoints,
        "post_publish_learning": {
            "wait_for_processing": "Audience-retention data commonly needs 1–2 days; do not diagnose before available.",
            "intro_30s": "Compare title/thumbnail promise with the opening proof; rewrite the next episode's hook when mismatch drives loss.",
            "dips": "Map timestamp to shot, narration beat and traffic source; remove repetition, confusion or delayed payoff in the next script.",
            "spikes": "Determine whether rewatch indicates delight or confusion before copying the device.",
            "top_moments": "Move the underlying value earlier or expand it in a future episode.",
            "ctr_by_traffic_source": "Diagnose Browse, Suggested, Search and External separately; never use one blended CTR as the verdict.",
            "satisfaction": "Review comments, likes/dislikes where available, end-screen continuation and returning-viewer behaviour with retention.",
            "ledger_fields": ["video_id", "traffic_source", "impressions", "ctr", "intro_30s", "average_view_duration", "average_percentage_viewed", "top_moments", "spikes", "dips", "editorial_hypothesis", "next_episode_change"],
        },
    }


def validate(plan: list[dict[str, Any]], contract: dict[str, Any]) -> list[str]:
    errors = []
    if not plan:
        return ["story plan is empty"]
    if not contract.get("central_dramatic_question"):
        errors.append("central dramatic question is missing")
    roles = [s.get("story", {}).get("role") for s in plan]
    for required in ("cold_open_payoff", "central_question", "records_payoff", "next_story_cta"):
        if required not in roles:
            errors.append(f"story role missing: {required}")
    for shot in plan:
        narration = str(shot.get("narration", "")).strip()
        if narration and not shot.get("claim_ids"):
            errors.append(f"{shot.get('shot_id')}: narrated factual beat has no claim_ids")
    return errors


def write_contract(master_dir: Path, plan: list[dict[str, Any]], metadata: dict[str, Any], subject: str, write_json) -> dict[str, Any]:
    contract = build_contract(plan, metadata, subject)
    errors = validate(plan, contract)
    contract["validation"] = {"status": "passed" if not errors else "blocked", "errors": errors}
    write_json(master_dir / "story-retention-contract.json", contract)
    write_json(master_dir / "shot-plan.json", plan)
    return contract
