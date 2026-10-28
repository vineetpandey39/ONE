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
        allowed = {"focus_place", "context_place", "context_label", "wide_headline", "close_headline"}
        if set(map_overrides) - allowed:
            raise RuntimeError("Editorial repair tried to change map identity or map-shot count")
        raw_map = record["opening_map_spec"]
        if isinstance(raw_map, str):
            raw_map = re.sub(r"^\s*(?:```json\s*|json\s+)", "", raw_map,
                             flags=re.IGNORECASE).strip().removesuffix("```").strip()
        map_spec = json.loads(raw_map) if isinstance(raw_map, str) else dict(raw_map)
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
    audit = []
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
