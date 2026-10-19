"""Deterministic cinematic direction for Motion V3.

The approved Motion V2 card spec remains the compatibility boundary.  This
module only adds direction metadata, so a V3 manifest can still be rendered by
V2 if the experiment is rejected.  Choices are semantic, deterministic and
checked against recent receipts rather than being cosmetic randomisation.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

GRAMMAR_VERSION = "2026-10-13.1"

PALETTES = {
    "andaman": {"ink": "#071A1E", "ink2": "#0D2A30", "salt": "#EEF2EC", "mute": "#86A5A2", "accent": "#FFB320"},
    "monsoon": {"ink": "#101A2B", "ink2": "#172D49", "salt": "#F3F6FA", "mute": "#91A7C0", "accent": "#55D6BE"},
    "saffron": {"ink": "#1D1310", "ink2": "#39231B", "salt": "#FFF5E8", "mute": "#C0A58F", "accent": "#FF8A32"},
    "lagoon": {"ink": "#071B26", "ink2": "#0B3441", "salt": "#F0FBFA", "mute": "#85AFB4", "accent": "#3FE0C5"},
    "plum": {"ink": "#1A1022", "ink2": "#352044", "salt": "#FAF2FF", "mute": "#B59BBE", "accent": "#FF6F91"},
    "paper": {"ink": "#192027", "ink2": "#303A43", "salt": "#FFF9EC", "mute": "#ADB4B8", "accent": "#F3C969"},
}

COMPOSITIONS = {
    "statement": ("editorial-left", "editorial-right", "center-monument", "diagonal-stage", "frame-within-frame"),
    "stat": ("giant-left", "giant-right", "number-window", "radial-counter"),
    "versus": ("vertical-split", "diagonal-split", "stacked-verdict", "sliding-panels"),
    "window": ("horizontal-track", "vertical-countdown", "passport-timeline", "radial-window"),
    "checklist": ("two-column", "boarding-stack", "radial-checks", "progressive-folder"),
    "lower": ("bottom-cinema", "left-glass", "top-editorial", "floating-caption"),
    "proof": ("document-lens", "browser-stage", "source-wall", "magnified-clause"),
    "coast": ("atlas-coast", "globe-route", "airport-network", "regional-zoom"),
}

MOTIFS = ("contour", "orbit", "document-grid", "route-lines", "soft-particles", "architectural-bars")
ENTRANCES = ("mask-rise", "word-cluster", "kinetic-slide", "focus-pull", "scale-resolve")
CAMERAS = ("locked", "dolly-left", "dolly-right", "slow-push", "parallax-drift")
EXITS = ("match-cut", "iris-wipe", "directional-blur", "panel-collapse", "ink-reveal")

INTENT_PALETTES = {
    "warning": ("saffron", "plum", "andaman"),
    "evidence": ("paper", "monsoon", "andaman"),
    "map": ("lagoon", "monsoon", "andaman"),
    "cost": ("saffron", "paper", "lagoon"),
    "destination": ("lagoon", "plum", "andaman"),
    "plan": ("monsoon", "paper", "lagoon"),
}


def intent_for(beat: dict, spec: dict) -> str:
    text = " ".join(str(beat.get(k) or "") for k in ("layout", "headline", "body", "kicker")).lower()
    if beat.get("family") == "map": return "map"
    if beat.get("family") == "obs" or any(x in text for x in ("official", "source", "proof", "verify")): return "evidence"
    if any(x in text for x in ("warning", "avoid", "don't", "risk", "alert", "visa")): return "warning"
    if any(x in text for x in ("cost", "price", "budget", "₹", "fare")): return "cost"
    if any(x in text for x in ("itinerary", "plan", "day", "route", "checklist")): return "plan"
    return "destination" if spec.get("template") in ("lower", "coast") else "plan"


def _rank(seed: str, values) -> list[str]:
    return sorted(values, key=lambda value: hashlib.sha256(f"{seed}|{value}".encode()).hexdigest())


def signature(direction: dict) -> str:
    keys = ("format_family", "visual_world", "intent", "composition", "palette", "motif", "entrance", "camera", "exit")
    raw = "|".join(str(direction.get(k, "")) for k in keys)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def recent_signatures(history_dir: Path | None, limit: int = 10) -> list[str]:
    if not history_dir or not history_dir.is_dir(): return []
    receipts = sorted(history_dir.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)[:limit]
    out = []
    for path in receipts:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.extend(x.get("signature", "") for x in data.get("beats", []) if x.get("signature"))
        except (OSError, ValueError):
            continue
    return out


def direct(spec: dict, beat: dict, *, video_id: str, scene_id: str, beat_id: str,
           recent: list[str], used: set[str], usage: dict | None = None,
           world: dict | None = None) -> dict:
    """Add a high-quality direction tuple while avoiding exact recent signatures."""
    template = spec["template"]
    intent = intent_for(beat, spec)
    seed = f"{video_id}|{scene_id}|{beat_id}|{template}|{intent}|{spec.get('lines')}"
    world_rules = (world or {}).get("rules") or {}
    palette_pool = tuple(x for x in world_rules.get("palettes", ()) if x in INTENT_PALETTES[intent]) \
        or INTENT_PALETTES[intent]
    motif_pool = world_rules.get("motifs") or MOTIFS
    dimensions = (
        _rank(seed + "c", COMPOSITIONS.get(template, ("editorial-left",))),
        _rank(seed + "p", palette_pool),
        _rank(seed + "m", motif_pool), _rank(seed + "e", ENTRANCES),
        _rank(seed + "k", CAMERAS), _rank(seed + "x", EXITS),
    )
    blocked = set(recent[-160:]) | used
    best = None
    candidates = []
    usage = usage if usage is not None else {}
    for values in itertools.product(*dimensions):
        candidate = {"format_family": (world or {}).get("format_family", "travel-dossier"),
                     "visual_world": (world or {}).get("visual_world", "unassigned"),
                     "intent": intent, "composition": values[0], "palette": values[1],
                     "motif": values[2], "entrance": values[3], "camera": values[4], "exit": values[5]}
        candidate["signature"] = signature(candidate)
        if candidate["signature"] not in blocked:
            score = (
                usage.get((template, "composition", candidate["composition"]), 0) * 100,
                usage.get(("global", "exit", candidate["exit"]), 0) * 25,
                usage.get(("global", "entrance", candidate["entrance"]), 0) * 15,
                usage.get((template, "palette", candidate["palette"]), 0) * 10,
                usage.get((template, "motif", candidate["motif"]), 0),
            )
            candidates.append((score, candidate))
    if candidates:
        best = min(candidates, key=lambda item: item[0])[1]
    if best is None:
        raise RuntimeError(f"Motion V3 exhausted unique directions for {video_id} beat {beat_id}")
    used.add(best["signature"])
    for dimension in ("composition", "palette", "motif"):
        key = (template, dimension, best[dimension])
        usage[key] = usage.get(key, 0) + 1
    for dimension in ("exit", "entrance"):
        key = ("global", dimension, best[dimension])
        usage[key] = usage.get(key, 0) + 1
    return {**spec, "direction": best, "palette_values": PALETTES[best["palette"]],
            "grammar_version": GRAMMAR_VERSION}


def similarity_report(beats: list[dict], recent: list[str]) -> dict:
    sigs = [b["direction"]["signature"] for b in beats if b and b.get("direction")]
    exact_recent = sorted(set(sigs) & set(recent))
    unique_ratio = len(set(sigs)) / max(1, len(sigs))
    compositions = [b["direction"]["composition"] for b in beats if b and b.get("direction")]
    composition_ratio = len(set(compositions)) / max(1, len(compositions))
    return {"beats": len(sigs), "unique_signatures": len(set(sigs)), "unique_ratio": round(unique_ratio, 4),
            "unique_compositions": len(set(compositions)), "composition_ratio": round(composition_ratio, 4),
            "exact_recent_repeats": exact_recent, "ok": unique_ratio == 1.0 and not exact_recent}

