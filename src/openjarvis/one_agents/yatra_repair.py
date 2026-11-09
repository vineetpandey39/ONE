"""Apply an explicitly reviewed, checkpoint-bound YATRA editorial repair.

The immutable LAO artifact stays intact. A sidecar may replace timed cue text
and the matching opening visual beats, but cannot change scene count or timing.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


_CUE = re.compile(r"(?m)^(\[\d{1,2}:\d{2}[–-]\d{1,2}:\d{2}\])\s*")


def apply_targeted_repair(source: Path, repair_file: Path) -> dict[str, Any]:
    raw = source.read_bytes()
    repair = json.loads(repair_file.read_text(encoding="utf-8"))
    if hashlib.sha256(raw).hexdigest().upper() != repair["base_sha256"].upper():
        raise RuntimeError("Editorial repair does not match its frozen LAO checkpoint")
    record = json.loads(raw.decode("utf-8"))[0]
    original_script = record["full_script"]
    matches = list(_CUE.finditer(original_script))
    if len(matches) != 20:
        raise RuntimeError(f"Cannot repair {len(matches)} cues; expected 20")
    chunks = []
    for index, match in enumerate(matches, 1):
        end = matches[index].start() if index < len(matches) else len(original_script)
        replacement = repair.get("cue_overrides", {}).get(str(index))
        chunks.append(match.group(1) + "\n\n" + (replacement.strip() if replacement else original_script[match.end():end].strip()))
    record["full_script"] = "\n\n".join(chunks) + "\n"

    opening = repair.get("scene_1")
    if opening:
        beats = opening["beats"]
        if len(beats) != 10 or any(beat["family"] not in {"stock", "map"} for beat in beats):
            raise RuntimeError("Opening repair requires ten stock/map beats")
        if [beat["family"] for beat in beats] != ["stock"] * 2 + ["map"] * 2 + ["stock"] * 6:
            raise RuntimeError("Opening repair must use two scenic shots, two map shots, then six unique scenic shots")
        shot_lines = []
        beat_lines = []
        director_beats = []
        stock_index = 0
        for i, beat in enumerate(beats):
            start, end = i * 3, (i + 1) * 3
            purpose = beat["purpose"]
            source_requirement = beat["source"]
            evidence = beat["verify"]
            beat_lines.append(
                f'      - {{beat_id: "01-{i+1:02d}", family: {beat["family"]}, '
                f'relative_start: {start}, relative_end: {end}, narrative_purpose: "{purpose}", '
                f'source_requirement: "{source_requirement}", evidence_requirement: "{evidence}", '
                'fallback_policy: "Replan; never use unrelated footage"}'
            )
            director_beats.append({
                "id": f"1.{i+1}", "family": beat["family"],
                "relative_start": start, "relative_end": end,
                "narrative_purpose": purpose, "layout": "", "headline": "", "body": "",
                "source_requirement": source_requirement, "evidence_requirement": evidence,
                "fallback_policy": "Replan; never use unrelated footage",
            })
            if beat["family"] == "stock":
                shot_lines.append(
                    f'      - S01{chr(65+stock_index)}; subject: {beat["subject"]}; '
                    f'exact_query: {source_requirement}; fallback_query: {beat["subject"]} drone; '
                    f'verify_primary: {evidence}; verify_alternate: {beat["subject"]}; shot_type: drone'
                )
                stock_index += 1
        block = "\n".join([
            "  - id: 1", '    time: "00:00-00:30"', "    duration: 30",
            f'    title: {opening["title"]}',
            f'    visual_purpose: {opening["visual_purpose"]}',
            "    graphic_template: destination_montage",
            f'    on_screen_text: "{opening["on_screen_text"]}"',
            "    geography_mode: verified_destination",
            "    source_requirement: Eight verified US-location clips plus Natural Earth maps.",
            "    evidence_requirement: Asset metadata verifies each place; H-1B hook starts only at the end.",
            "    director_beats:", *beat_lines, "    stock_shots:", *shot_lines,
        ])
        plan = record["scene_plan"]
        start = plan.index("  - id: 1\n")
        end = plan.index("  - id: 2\n", start)
        record["scene_plan"] = plan[:start] + block + "\n\n" + plan[end:]
        record["scene_plan"] = record["scene_plan"].replace("stock_planned_seconds: 267", "stock_planned_seconds: 276").replace(
            "stock_planned_share: 44.5_percent", "stock_planned_share: 46_percent"
        )
        manifest = json.loads(record["director_manifest_draft"])
        if str(manifest["scenes"][0].get("scene_id")) != "1":
            raise RuntimeError("Director manifest does not start at scene one")
        manifest["scenes"][0].update({"purpose": opening["visual_purpose"], "beats": director_beats})
        record["director_manifest_draft"] = json.dumps(manifest, ensure_ascii=False, indent=2)
    map_overrides = repair.get("opening_map_overrides") or {}
    if map_overrides:
        allowed = {"focus_place", "context_place", "context_label", "wide_headline", "close_headline",
                   "focus_region", "context_region", "require_exact_places", "narrative_maps"}
        if set(map_overrides) - allowed:
            raise RuntimeError("Editorial repair tried to change map identity or map-shot count")
        raw_map = record["opening_map_spec"]
        if isinstance(raw_map, str):
            raw_map = re.sub(r"^\s*(?:```json\s*|json\s+)", "", raw_map,
                             flags=re.IGNORECASE).strip().removesuffix("```").strip()
            raw_map = raw_map.removesuffix('<escape>').rstrip()
        map_spec = json.loads(raw_map) if isinstance(raw_map, str) else dict(raw_map)
        if 'narrative_maps' in map_overrides:
            old_maps, new_maps = map_spec.get('narrative_maps') or [], map_overrides['narrative_maps']
            if not isinstance(new_maps, list) or len(old_maps) != len(new_maps):
                raise RuntimeError('Map repair cannot change authored map count')
            mutable = {'focus_place', 'context_place', 'context_label', 'destination_label',
                       'wide_headline', 'close_headline', 'viewer_subtitle', 'travel_mode',
                       'focus_region', 'context_region', 'require_exact_places'}
            for old, new in zip(old_maps, new_maps):
                if {k:v for k,v in old.items() if k not in mutable} != {k:v for k,v in new.items() if k not in mutable}:
                    raise RuntimeError('Map repair cannot change scene, narration cue or country identity')
                if new.get('require_exact_places') is not True:
                    raise RuntimeError('Reviewed narrative maps require exact location resolution')
        if 'require_exact_places' in map_overrides and map_overrides['require_exact_places'] is not True:
            raise RuntimeError('Map repair cannot disable exact location resolution')
        map_spec.update(map_overrides)
        record["opening_map_spec"] = json.dumps(map_spec, ensure_ascii=False, separators=(",", ":"))
    capture_plan = str(record.get("browser_capture_plan") or "")
    for override in repair.get("capture_url_overrides") or []:
        old, new = override.get("from", ""), override.get("to", "")
        from urllib.parse import urlparse
        old_url, new_url = urlparse(old), urlparse(new)
        if (old_url.scheme != "https" or new_url.scheme != "https"
                or old_url.netloc != new_url.netloc or not old_url.netloc
                or old not in capture_plan):
            raise RuntimeError("Capture URL repair must replace a present HTTPS URL on the same host")
        capture_plan = capture_plan.replace(old, new)
    if repair.get("capture_url_overrides"):
        record["browser_capture_plan"] = capture_plan
    # Exact, reviewed edits to a frozen plan; never permit a sidecar to replace
    # identity, script, approval verdict or arbitrary top-level fields.
    plan_edits = repair.get("plan_text_edits") or []
    allowed_fields = {"scene_plan", "director_manifest_draft", "browser_capture_plan", "claim_ledger"}
    for edit in plan_edits:
        field = edit.get("field")
        before, after = edit.get("before"), edit.get("after")
        if (field not in allowed_fields or not isinstance(before, str) or not before
                or not isinstance(after, str) or not str(edit.get("reason") or "").strip()):
            raise RuntimeError("Plan repair requires an allowed field, exact text and review reason")
        value = record.get(field)
        if not isinstance(value, str) or value.count(before) != 1:
            raise RuntimeError("Plan repair text must match exactly once")
        record[field] = value.replace(before, after, 1)
    if any(edit["field"] == "director_manifest_draft" for edit in plan_edits):
        original = json.loads(json.loads(raw.decode("utf-8"))[0]["director_manifest_draft"])
        revised = json.loads(record["director_manifest_draft"])
        if [s["scene_id"] for s in original["scenes"]] != [s["scene_id"] for s in revised["scenes"]]:
            raise RuntimeError("Plan repair cannot change director scene identity or order")
        for scene in revised["scenes"]:
            end = 0
            for beat in scene["beats"]:
                if beat["relative_start"] != end or beat["relative_end"] <= end:
                    raise RuntimeError("Plan repair has a gap, overlap or invalid beat duration")
                end = beat["relative_end"]
            old = next(s for s in original["scenes"] if s["scene_id"] == scene["scene_id"])
            if end != old["beats"][-1]["relative_end"]:
                raise RuntimeError("Plan repair cannot change scene duration")
    audit = []
    if plan_edits:
        audit.append("reviewed exact plan edits: " + ",".join(sorted({e["field"] for e in plan_edits})))
    if repair.get("cue_overrides"):
        cue_ids = ",".join(sorted(repair["cue_overrides"], key=lambda value: int(value)))
        audit.append(f"timed cue overrides {cue_ids}")
    if opening:
        audit.append("reviewed scene-1 stock/map beat replacement")
    if map_overrides:
        audit.append("opening-map fields " + ",".join(sorted(map_overrides)))
    if repair.get("capture_url_overrides"):
        audit.append("same-host capture URL replacements")
    record["quality_gate"] = str(record.get("quality_gate") or "") + (
        "\nTARGETED_REPAIR: " + "; ".join(audit or ["checkpoint-bound metadata review"]) + ". "
        "Original REWRITE verdict retained for audit; approval is recorded separately in the repair receipt."
    )
    record["editorial_repair"] = {"source_sha256": repair["base_sha256"], "status": repair["status"]}
    return record
