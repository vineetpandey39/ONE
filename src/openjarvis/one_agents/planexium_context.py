"""Hash-bound editorial context labels; they do not establish scientific evidence."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

LABELS = {
    5: (3, "Jupiter cloud tops - illustration"),
    6: (3, "Jupiter clouds - illustration"),
    8: (4, "Great Red Spot - illustration"),
    10: (5, "Juno at Jupiter - illustration"),
    14: (7, "Jupiter atmosphere - illustration"),
    20: (10, "Juno at Jupiter - illustration"),
    19: (10, "Generic probe - not Juno"),
    9: (5, "Cloud-top context - illustration"),
    11: (6, "Jupiter atmosphere - illustration"),
    13: (7, "Jupiter exterior - illustration"),
    15: (8, "Exterior view - illustration"),
}
MISSION = "daily-20261026"
ARCHIVE_LABELS = {
    "3:1": ("PIA02865", "727 nm cloud-depth view", "scientific_observation"),
    "9:1": ("PIA22949", "Cloud tops - core not visible", "archival_context"),
}

PIPELINE_LABELS = {
    'Illustrative audience - not NASA event footage',
    'Illustrative capsule descent - not actual Soyuz footage',
    'Illustrative bioprinter - not ISS experiment footage',
    'Illustrative inspection - not Expedition 74 footage',
}


def bind_pipeline_context(root, plan, stock):
    """Bind code-authored disclosures to the sealed brief, scene and asset bytes."""
    from openjarvis.one_agents.planexium_adapters import concrete_stock_brief
    from openjarvis.one_agents.planexium_cinematic import bind_illustrative_stock_requests
    root = Path(root)
    science_path = root / 'science-plan.json'
    science = json.loads(science_path.read_text(encoding='utf-8'))
    original = json.loads((root / 'cinematic-plan.json').read_text(encoding='utf-8'))
    original = bind_illustrative_stock_requests(original, science)
    def fingerprint(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    approved = {}
    for index, request in enumerate(original['stock_requests']):
        brief = concrete_stock_brief(request)
        if brief.get('contextual_label') in PIPELINE_LABELS:
            scenes = {int(n) for n, indices in original['scene_assets'].items() if index in indices}
            approved.setdefault(fingerprint(brief), set()).update(scenes)
    for index, asset in enumerate(stock):
        label = asset.get('contextual_label')
        if not label:
            continue
        brief = concrete_stock_brief(plan['stock_requests'][index])
        identity = fingerprint(brief)
        scenes = {int(n) for n, indices in plan['scene_assets'].items() if index in indices}
        if (label not in PIPELINE_LABELS or brief.get('contextual_label') != label
                or not scenes or not scenes.issubset(approved.get(identity, set()))
                or not all(science['scenes'][n-1].get('illustrative') is True for n in scenes)
                or hashlib.sha256(Path(asset['path']).read_bytes()).hexdigest() != asset['sha256']):
            raise ValueError('Pipeline context disclosure is not bound to verified authored illustration')
        asset['context_label_proof'] = {
            'policy': 'authored-illustration-v1', 'label': label,
            'asset_sha256': asset['sha256'], 'science_sha256': hashlib.sha256(science_path.read_bytes()).hexdigest(),
            'brief_sha256': identity, 'scenes': sorted(scenes)}

def bind_archive_context(root, bundle, archives):
    if any(a.get("contextual_label") or a.get("contextual_role") for a in archives.values()):
        raise ValueError("Archive context labels must originate in bound review records")
    records = bundle.get("archive_contextual_labels", {})
    if records and Path(root).name != MISSION:
        raise ValueError("Archive context amendment is mission scoped")
    if set(records) - set(ARCHIVE_LABELS):
        raise ValueError("Unapproved archive context slot")
    science_hash = hashlib.sha256((Path(root)/"science-plan.json").read_bytes()).hexdigest()
    for key, record in records.items():
        nasa_id, label, role = ARCHIVE_LABELS[key]
        asset = archives.get(key, {})
        if (int(key.split(":")[0]) not in bundle["scenes"]
                or asset.get("nasa_id") != nasa_id or record.get("label") != label
                or record.get("asset_sha256") != asset.get("sha256")
                or record.get("science_sha256") != science_hash
                or not record.get("not_evidence_of", "").strip()):
            raise ValueError("Archive context identity or limitation mismatch")
        asset.update(contextual_label=label, contextual_role=role)
        if key == "9:1":
            # The explicit authored slots, validated separately, retain the core coverage.
            expected = {bundle["assets"].get("authored_motion", {}).get(str(slot), {}).get("sha256")
                        for slot in (17, 18)}
            if None in expected or set(record.get("phenomenon_evidence", [])) != expected:
                raise ValueError("Cloud-top context cannot replace both authored core sequences")
    return records


def bind_context(root, bundle, original_plan, assets):
    """Validate explicit reviewed rebriefs, without accepting lexical matching as review."""
    if any(a.get("contextual_label") for a in assets["stock"]):
        raise ValueError("Context labels must originate in bound review records")
    records = bundle.get("contextual_labels", {})
    if records and Path(root).name != MISSION:
        raise ValueError("Context amendment is mission scoped")
    if set(records) - {str(n) for n in LABELS}:
        raise ValueError("Unapproved context slot")
    science_hash = hashlib.sha256((Path(root)/"science-plan.json").read_bytes()).hexdigest()
    for slot, (scene, label) in LABELS.items():
        if Path(root).name != MISSION:
            continue
        changed = bundle["plan"]["stock_requests"][slot-1] != original_plan["stock_requests"][slot-1]
        record = records.get(str(slot))
        if changed and not record:
            raise ValueError("Context rebrief requires a reviewed visible label")
        if not record:
            continue
        asset = assets["stock"][slot-1]
        if (record.get("scene") != scene or scene not in bundle["scenes"]
                or record.get("label") != label or record.get("role") != "contextual_illustration"
                or record.get("asset_sha256") != asset["sha256"]
                or record.get("science_sha256") != science_hash
                or not record.get("depicted_subject", "").strip()
                or not record.get("not_evidence_of", "").strip()):
            raise ValueError("Context review identity, scope or limitation mismatch")
        frames = record.get("review_frames", [])
        if len(frames) < 2 or len({f.get("sha256") for f in frames}) != len(frames):
            raise ValueError("Context requires distinct reviewed motion frames")
        for frame in frames:
            path = Path(frame["path"]).resolve()
            if (not path.is_relative_to(Path(root).resolve()) or not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != frame["sha256"]):
                raise ValueError("Context review frame changed")
        if not record.get("phenomenon_evidence"):
            raise ValueError("Context cannot replace phenomenon evidence")
        asset["contextual_label"] = label
    return records

def validate_context_coverage(records, scene_shots):
    """Referenced evidence must actually be scheduled, distinct from contextual clips."""
    for record in records.values():
        row = scene_shots.get(str(record["scene"]), [])
        available = {s["asset"]["sha256"] for s in row if not s["asset"].get("contextual_label") or s["asset"].get("contextual_role") == "scientific_observation"}
        if not set(record["phenomenon_evidence"]).issubset(available):
            raise ValueError("Context phenomenon evidence is absent from the scene timeline")

def context_filter(asset, directory, ordinal, font):
    label = asset.get("contextual_label")
    if not label:
        return ""
    proof = asset.get('context_label_proof') or {}
    pipeline_label = (label in PIPELINE_LABELS and proof.get('policy') == 'authored-illustration-v1'
        and proof.get('label') == label and proof.get('asset_sha256') == asset.get('sha256')
        and bool(proof.get('science_sha256')) and bool(proof.get('brief_sha256')) and bool(proof.get('scenes')))
    if not pipeline_label and label not in ({row[1] for row in LABELS.values()} | {row[1] for row in ARCHIVE_LABELS.values()}):
        raise ValueError("Unvalidated context label")
    path = Path(directory)/f"context-{ordinal}.txt"
    path.write_text(label, encoding="utf-8")
    escaped = path.as_posix().replace(":", "\\:")
    # No enable/time expression: attribution remains visible throughout the finite cut.
    return (f",drawtext=fontfile='{font}':textfile='{escaped}':fontsize=32:fontcolor=white:"
            "x=w-tw-48:y=48:box=1:boxcolor=black@0.8:boxborderw=14")
