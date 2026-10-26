"""Versioned, local-only cinematic repairs; never fetch, enqueue or rewrite checkpoints."""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from pathlib import Path

from openjarvis.one_agents.youtube_production import resource_lease

SCHEMA = "planexium-local-assets-v1"
POINTER = "asset-repair.json"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def snapshot(root):
    root = Path(root)
    paths = [root / name for name in ("science-plan.json", "cinematic-plan.json",
             "media-manifest.json", "narration/narration.segments.json", "edit/cinematic-assets.json")]
    checkpoints = list((root / "checkpoints").glob("*.json"))
    paths += checkpoints
    for checkpoint in checkpoints:
        for name, expected in read(checkpoint).get("files", {}).items():
            path = (root / name).resolve()
            if not path.is_relative_to(root.resolve()) or digest(path) != expected:
                raise ValueError("Accepted upstream checkpoint artifact changed")
            paths.append(path)
    paths += list((root / "cinematic-assets").rglob("acquired/stock-*.json"))
    paths += list((root / "sources").rglob("source-receipt.json"))
    return {str(p.relative_to(root)).replace("\\", "/"): digest(p) for p in paths}


def _idle(root):
    from openjarvis.one_agents.planexium_render_job import child_alive
    if any((root / name).exists() for name in
           ("checkpoints/render.json", "edit/master.mp4", "edit/render-complete.json")):
        raise ValueError("Sealed or existing output requires separate governed review")
    owner = root / "edit/render-owner.json"
    if owner.exists() and child_alive(read(owner), root):
        raise RuntimeError("Existing renderer owns this mission")


def _asset(root, asset):
    path = Path(asset["path"]).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Repair asset must already exist inside its mission")
    if digest(path) != asset["sha256"]:
        raise ValueError("Repair asset hash mismatch")


def validate_bundle(root, bundle):
    """All-scene preflight with existing gates, without network or output writes."""
    from openjarvis.one_agents.planexium_adapters import probe_stock, stock_context_matches
    from openjarvis.one_agents.planexium_cinematic import usable_start
    from openjarvis.one_agents.planexium_editorial import build_scene_shots
    from openjarvis.one_agents.space_research import source_identity, nasa_subject_matches, validate_url, MEDIA_HOSTS

    root = Path(root).resolve()
    if bundle.get("schema") != SCHEMA or bundle.get("mission_id") != root.name:
        raise ValueError("Repair schema or mission mismatch")
    if not bundle.get("reason", "").strip() or bundle.get("base_hashes") != snapshot(root):
        raise ValueError("Repair base changed or reason missing")
    original_plan = read(root / "cinematic-plan.json")
    original_assets = read(root / "edit/cinematic-assets.json")
    science = read(root / "science-plan.json")
    voice = read(root / "narration/narration.segments.json")
    plan = copy.deepcopy(bundle["plan"])
    assets = copy.deepcopy(bundle["assets"])
    scenes = bundle.get("scenes", [])
    if not scenes or len(set(scenes)) != len(scenes) or any(
            type(n) is not int or not 1 <= n <= len(science["scenes"]) for n in scenes):
        raise ValueError("Repair must name distinct existing scenes")
    if plan.get("scene_shots") or len(plan["stock_requests"]) != len(original_plan["stock_requests"]):
        raise ValueError("Repair cannot bypass planning or change acquisition count")
    indexes = {i for n in scenes for i in original_plan["scene_assets"][str(n)]}
    comparison = copy.deepcopy(plan)
    for n in scenes:
        comparison["scene_visuals"][str(n)] = original_plan["scene_visuals"][str(n)]
    for i in indexes:
        if not set(original_plan["stock_requests"][i].get("blocked_keywords", [])).issubset(
                plan["stock_requests"][i].get("blocked_keywords", [])):
            raise ValueError("Repair cannot remove blocked stock subjects")
        comparison["stock_requests"][i] = original_plan["stock_requests"][i]
    if comparison != original_plan or assets.get("music") != original_assets.get("music"):
        raise ValueError("Repair changed unrelated plan or music")
    if len(assets["stock"]) != len(original_assets["stock"]):
        raise ValueError("Repair must retain stock slots")
    identities = set()
    for i, asset in enumerate(assets["stock"]):
        if i not in indexes and asset != original_assets["stock"][i]:
            raise ValueError("Repair changed an unrelated asset")
        _asset(root, asset)
        identity = source_identity(asset)
        if identity in identities:
            raise ValueError("Repeated stock source identity")
        identities.add(identity)
        if not stock_context_matches(plan["stock_requests"][i], asset):
            raise ValueError("Stock context is not relevant")
        asset.update(probe_stock(Path(asset["path"])))
        asset["usable_in"] = usable_start(asset)
    _asset(root, assets["music"])
    archives = bundle.get("archive_assets", {})
    for key, asset in archives.items():
        n, index = (int(v) for v in key.split(":"))
        if n not in scenes or not 1 <= index <= len(plan["scene_visuals"][str(n)]):
            raise ValueError("Archive replacement is outside scoped scenes")
        _asset(root, asset)
        if asset.get("editorial_query") != plan["scene_visuals"][str(n)][index - 1]:
            raise ValueError("Archive replacement brief mismatch")
        if (asset.get("provider") != "NASA" or not asset.get("credit")
                or not nasa_subject_matches(asset["editorial_query"], asset.get("metadata", {}))):
            raise ValueError("Archive replacement lacks relevant NASA provenance")
        validate_url(asset["download_url"], MEDIA_HOSTS)
    articles = bundle.get("article_assets", [])
    for asset in articles:
        _asset(root, asset)
        if asset.get("provider") != "NASA" or not asset.get("credit"):
            raise ValueError("Article replacement lacks provenance")
        validate_url(asset["download_url"], MEDIA_HOSTS)
    # The placeholder is never selected: existing scene media owns no such hash.
    # It prevents the renderer from fetching an unrelated primary image.
    original = {"path": str(root / "unused-primary.jpg"), "sha256": "unused", "seconds": 0}
    shots = build_scene_shots(root, science, voice, assets, original,
        read(root / "media-manifest.json")["scenes"], plan,
        archive_assets=archives, article_assets=articles, offline=True, write_outputs=False)
    return {"plan": plan, "assets": assets, "scene_shots": shots}


def stage_repair(root, bundle):
    """Store a verified immutable candidate. Does not activate or resume it."""
    root = Path(root).resolve()
    with resource_lease(root.parent.parent / ".leases", "planexium-production"):
        _idle(root)
        validate_bundle(root, bundle)
        target = root / "repairs/local-assets" / uuid.uuid4().hex / "bundle.json"
        target.parent.mkdir(parents=True, exist_ok=False)
        target.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
        return {"bundle": str(target.relative_to(root)), "sha256": digest(target)}


def _bundle(root, pointer):
    path = (root / pointer["bundle"]).resolve()
    if not path.is_relative_to((root / "repairs/local-assets").resolve()) or digest(path) != pointer["sha256"]:
        raise ValueError("Repair bundle identity changed")
    return read(path)


def _switch(root, pointer, expected_pointer_hash):
    path = root / POINTER
    current = digest(path) if path.exists() else None
    if current != expected_pointer_hash:
        raise ValueError("Active repair changed; reconcile before switching")
    history = root / "repairs/local-assets" / (uuid.uuid4().hex + "-switch.json")
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text(json.dumps({"before": read(path) if path.exists() else None,
                                   "after": pointer}), encoding="utf-8")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(pointer, indent=2), encoding="utf-8")
    temporary.replace(path)
    return {"pointer_sha256": digest(path), "history": str(history)}


def activate_repair(root, pointer, *, expected_pointer_hash=None):
    root = Path(root).resolve()
    with resource_lease(root.parent.parent / ".leases", "planexium-production"):
        _idle(root)
        validate_bundle(root, _bundle(root, pointer))
        return _switch(root, pointer, expected_pointer_hash)


def rollback_repair(root, *, expected_pointer_hash):
    """Disable the overlay, retaining bundle, switch history and original files."""
    root = Path(root).resolve()
    with resource_lease(root.parent.parent / ".leases", "planexium-production"):
        _idle(root)
        return _switch(root, {"bundle": None}, expected_pointer_hash)


def load_active(root):
    root = Path(root).resolve()
    path = root / POINTER
    if not path.exists() or not read(path).get("bundle"):
        return None
    return validate_bundle(root, _bundle(root, read(path)))
