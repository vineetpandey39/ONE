"""Isolated Floor 12 science production, built from shared YouTube services.

Importing this module never queues work, installs packages, starts providers,
changes schedules, resolves credentials or publishes anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import replace, asdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from openjarvis.one_agents import space_research
from openjarvis.one_agents.planexium_adapters import fingerprint
from openjarvis.one_agents.youtube_channels import PLANEXIUM, ProductionContext
from openjarvis.one_agents.youtube_production import ProductionServices, resource_lease

SUITE = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG = SUITE / "src" / "configs" / "planexium.json"
BUILD_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
TOPICS = (
    {"topic": "Mars and its two moons", "sources": ["https://science.nasa.gov/mars/moons/", "https://science.nasa.gov/mars/moons/phobos/"]},
    {"topic": "Jupiter's atmosphere and exploration", "sources": ["https://science.nasa.gov/jupiter/facts/"]},
    {"topic": "Saturn's rings", "sources": ["https://science.nasa.gov/saturn/facts/"]},
    {"topic": "What a black hole is", "sources": ["https://science.nasa.gov/universe/black-holes/"]},
    {"topic": "How the Sun works", "sources": ["https://science.nasa.gov/sun/facts/"]},
    {"topic": "Earth's Moon", "sources": ["https://science.nasa.gov/moon/facts/"]},
    {"topic": "The International Space Station", "sources": ["https://www.nasa.gov/international-space-station/space-station-facts-and-figures/"]},
)

SOURCE_ALIASES = {
    "https://www.nasa.gov/international-space-station/":
        "https://www.nasa.gov/international-space-station/space-station-facts-and-figures/",
}


def load_config(path: Path | None = None) -> dict:
    path = path or Path(os.environ.get("PLANEXIUM_CONFIG", DEFAULT_CONFIG))
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("brand") != "planexium" or config.get("public_publish_authorized") is not False:
        raise ValueError("PLANEXIUM configuration must retain private review policy")
    if not isinstance(config.get("providers_enabled"), bool):
        raise ValueError("Provider execution requires an explicit boolean setting")
    if config.get("channel_id") and not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", config["channel_id"]):
        raise ValueError("Channel ID is not a verified YouTube channel identifier")
    return config


def context_for(mission: str, config: dict) -> ProductionContext:
    root = Path(config.get("media_root") or SUITE / "data" / "planexium" / "media")
    voice = config.get("voice") or {}
    profile = replace(PLANEXIUM, voice_name=voice.get("name", PLANEXIUM.voice_name),
                      narration_backend=voice.get("backend", PLANEXIUM.narration_backend))
    if config.get("channel_id"):
        profile = replace(profile, subscribe_url=f"https://www.youtube.com/channel/{config['channel_id']}?sub_confirmation=1")
    return ProductionContext(profile, root.resolve(), mission)


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def manual_upload_result(context: ProductionContext) -> dict | None:
    path = context.artifact('manual-upload.json')
    if not path.exists():
        return None
    receipt = json.loads(path.read_text(encoding='utf-8'))
    if (receipt.get('brand') != 'planexium' or receipt.get('mission_id') != context.mission_id
            or receipt.get('confirmation') != 'user_reported_uploaded'
            or receipt.get('master_sha256') != _hash(context.artifact('edit/master.mp4'))):
        raise ValueError('Manual upload receipt does not match this completed master')
    return {'agent': 'PLANEXIUM', 'mission_id': context.mission_id,
            'status': 'uploaded_manually', 'production_complete': True, 'uploaded': True,
            'public_visibility_verified': False, 'duplicate_execution_skipped': True,
            'master': str(context.artifact('edit/master.mp4')), 'receipt': str(path)}


def record_manual_upload(context: ProductionContext, *, confirmed_by_user: bool) -> dict:
    """Record the user's completed external action; never authorize a future upload."""
    if confirmed_by_user is not True:
        raise ValueError('Explicit user confirmation of the completed upload is required')
    with resource_lease(context.media_root / '.leases', 'planexium-production'):
        existing = manual_upload_result(context)
        if existing:
            return existing
        completed = context.artifact('checkpoints/package.json')
        if not completed.is_file():
            raise ValueError('A completed review package is required before recording its upload')
        for checkpoint_path in [completed,context.artifact('checkpoints/render.json')]:
            checkpoint = json.loads(checkpoint_path.read_text(encoding='utf-8'))
            for relative, expected in checkpoint.get('files', {}).items():
                if _hash(context.artifact(relative)) != expected:
                    raise ValueError('Completed package changed before upload confirmation')
        receipt = {'brand': 'planexium', 'mission_id': context.mission_id,
                   'confirmation': 'user_reported_uploaded',
                   'recorded_at': datetime.now(ZoneInfo('UTC')).isoformat(),
                   'master_sha256': _hash(context.artifact('edit/master.mp4')),
                   'public_visibility_verified': False, 'public_publish_authorized': False}
        _write(context.artifact('manual-upload.json'), receipt)
        ledger_path = context.root.parent / 'production-ledger.json'
        ledger = json.loads(ledger_path.read_text(encoding='utf-8')) if ledger_path.exists() else {}
        ledger.setdefault(context.mission_id, {}).update(status='uploaded_manually',
            manual_upload_receipt='manual-upload.json', master_sha256=receipt['master_sha256'])
        _write(ledger_path, ledger)
        return manual_upload_result(context)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repair_stage(context: ProductionContext, stage: str, *, reason: str) -> list[str]:
    """Explicit, auditable checkpoint invalidation; never re-voices a visual repair."""
    if stage not in {"render", "thumbnail", "media", "direction", "package"} or not reason.strip():
        raise ValueError("Only named visual repairs with a reason are supported here")
    stages = {"media":["media","render","package"],"direction":["direction","render","package"],
              "render":["render","package"],"thumbnail":["thumbnail","package"],"package":["package"]}[stage]
    with resource_lease(context.media_root / ".leases", "planexium-production"):
        tag = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        moved = []
        for name in stages:
            path = context.artifact(f"checkpoints/{name}.json")
            if path.exists():
                target = context.artifact(f"repairs/{tag}/{name}.json")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target))
                moved.append(name)
        _write(context.artifact(f"repairs/{tag}/reason.json"), {"stage": stage, "reason": reason,
                "invalidated": moved, "narration_preserved": True})
        gate = context.artifact("review-gate.json")
        if gate.exists():
            value = json.loads(gate.read_text())
            value["status"] = "repair_in_progress"
            _write(gate, value)
        return moved


def _stamp(seconds: float, *, srt=False) -> str:
    ms = round(seconds * 1000)
    hour, rest = divmod(ms, 3600000)
    minute, rest = divmod(rest, 60000)
    second, milli = divmod(rest, 1000)
    return f"{hour:02}:{minute:02}:{second:02},{milli:03}" if srt else f"{hour * 60 + minute}:{second:02}"


class Pipeline:
    def __init__(self, context: ProductionContext, config: dict, *, writer=None, image=None,
                 stock=None, capture=None, source_reader=space_research.read_public,
                 narrator=None, renderer=None, on_stage=None, director=None, editorial=None):
        self.context, self.config = context, config
        self.services = ProductionServices(context)
        self.writer, self.image, self.stock, self.capture = writer, image, stock, capture
        self.source_reader, self.narrator, self.renderer = source_reader, narrator, renderer
        self.on_stage, self.director = on_stage, director
        self.editorial = editorial

    def event(self, stage: str, status: str, **details):
        """Non-secret, mission-owned evidence for real stage performance."""
        row = {"at": datetime.now(ZoneInfo("UTC")).isoformat(), "stage": stage, "status": status,
               "agent_id": self.config.get("_agent_id", "planexium"),
               "job_id": self.config.get("_agent_job_id"), "production_build": self.config.get("_production_build"), **details}
        path = self.context.artifact("stage-events.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        if status in {"started", "failed"}:
            self.health("running" if status == "started" else "needs_resume",
                        stage=stage, error_class=details.get("error_class"))

    def health(self, status, *, stage=None, error_class=None):
        path = self.context.artifact("production-health.json")
        previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        previous.update(agent="PLANEXIUM", mission_id=self.context.mission_id,
            agent_job_id=self.config.get("_agent_job_id"), status=status,
            current_stage=stage, production_complete=status == "awaiting_review",
            public_publish_authorized=False, published=False,
            blocked_reason=error_class, updated_at=datetime.now(ZoneInfo("UTC")).isoformat())
        _write(path, previous)

    def stage(self, name: str, request, action):
        receipt = self.context.artifact(f"checkpoints/{name}.json")
        request_hash = fingerprint(request)
        if receipt.is_file():
            saved = json.loads(receipt.read_text(encoding="utf-8"))
            if saved["request_hash"] != request_hash:
                raise ValueError(f"{name} checkpoint differs; use a new mission or a targeted repair")
            for relative, expected in saved.get("files", {}).items():
                path = self.context.artifact(relative)
                if not path.is_file() or _hash(path) != expected:
                    raise ValueError(f"{name} checkpoint artifact changed; targeted repair required")
            self.event(name, "cache_verified", artifact_count=len(saved.get("files", {})))
            return saved["result"]
        if self.on_stage:
            self.on_stage(name)
        started = time.monotonic()
        self.event(name, "started")
        try:
            result, files = action()
        except Exception as exc:
            self.event(name, "failed", seconds=round(time.monotonic() - started, 3), error_class=type(exc).__name__)
            raise
        hashes = {str(Path(p).resolve().relative_to(self.context.root.resolve())): _hash(Path(p)) for p in files}
        _write(receipt, {"request_hash": request_hash, "result": result, "files": hashes})
        self.event(name, "passed", seconds=round(time.monotonic() - started, 3), artifact_count=len(hashes))
        return result

    def produce(self, commission: dict, *, plan: dict | None = None, pilot=False) -> dict:
        if commission.get("brand") != "planexium" or not commission.get("topic"):
            raise ValueError("Explicit PLANEXIUM commission required")
        # One channel production at a time; other floors/channels remain free.
        with resource_lease(self.context.media_root / ".leases", "planexium-production"):
            uploaded = manual_upload_result(self.context)
            if uploaded:
                return uploaded
            ledger_path = self.context.root.parent / "production-ledger.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
            unfinished = [key for key, row in ledger.items() if key != self.context.mission_id
                          and row.get("status") in {"producing", "needs_resume"}]
            if unfinished:
                raise RuntimeError("An earlier PLANEXIUM production needs resume; do not create backlog")
            ledger[self.context.mission_id] = {"topic": commission["topic"], "status": "producing"}
            _write(ledger_path, ledger)
            try:
                result = self._produce(commission, plan=plan, pilot=pilot)
            except Exception as exc:
                ledger[self.context.mission_id]["status"] = "needs_resume"
                _write(ledger_path, ledger)
                self.health("needs_resume", stage="pipeline", error_class=type(exc).__name__)
                raise
            ledger[self.context.mission_id]["status"] = "review_ready"
            _write(ledger_path, ledger)
            self.health("awaiting_review", stage="package")
            if self.config.get("ares_seo") and result.get("output"):
                from openjarvis.one_agents.planexium_seo import require_seo
                package = json.loads(Path(result["output"]).read_text(encoding="utf-8"))
                try:
                    require_seo(package)
                except ValueError:
                    from openjarvis.one_agents.runtime import enqueue_job
                    self.health("awaiting_seo", stage="seo")
                    ledger[self.context.mission_id]["status"] = "awaiting_seo"
                    _write(ledger_path, ledger)
                    try:
                        seo = enqueue_job("ares", json.dumps({"brand": "planexium", "stage": "seo",
                            "mission_id": self.context.mission_id}), mode="execute", tier="fast",
                            dedupe_key=f"planexium:{self.context.mission_id}:ares-seo-v1")
                    except Exception as exc:
                        ledger[self.context.mission_id]["status"] = "seo_failed"
                        _write(ledger_path, ledger)
                        self.health("seo_failed", stage="seo", error_class=type(exc).__name__)
                        raise
                    result.update(status="awaiting_seo", handed_to={"agent": "ARES", "job_id": seo["id"]})
            return result

    def _produce(self, commission, *, plan, pilot):
        root = self.context.root
        root.mkdir(parents=True, exist_ok=True)
        def gather():
            path = self.context.artifact("evidence.json")
            return space_research.research(commission["sources"], path, read=self.source_reader), [path]
        evidence = self.stage("research", commission, gather)
        def write_script():
            if plan is None and self.writer is None:
                raise RuntimeError("Science writer binding required")
            result = plan if plan is not None else self.writer(space_research.writer_prompt(commission["topic"], evidence))
            # Preserve rejected provider output so HELIOS can diagnose the
            # actual claim/scene instead of receiving only a generic traceback.
            _write(self.context.artifact("script-draft.json"), result)
            space_research.validate_script(result, evidence)
            path = self.context.artifact("science-plan.json")
            _write(path, result)
            return result, [path]
        science = self.stage("script", {"commission": commission, "evidence": evidence, "supplied_plan": plan}, write_script)
        space_research.validate_script(science, evidence)
        episode_policy = self.config.get("episode_policy") or {}
        if episode_policy and not pilot:
            words = sum(len(str(scene.get("narration", "")).split()) for scene in science["scenes"])
            minimum_words = int(episode_policy.get("target_words", [900])[0])
            minimum_scenes = int(episode_policy.get("target_scenes", [10])[0])
            if words < minimum_words or len(science["scenes"]) < minimum_scenes:
                raise ValueError(f"Long-form gate: script has {words} words/{len(science['scenes'])} scenes; needs at least {minimum_words}/{minimum_scenes}")
        if not pilot and not any(s.get("visual_kind") == "stock" for s in science["scenes"]):
            raise ValueError("Full productions require at least one licensed Envato stock scene; pilot exemption only")
        def speak():
            texts = [s["narration"] for s in science["scenes"]]
            result = self.narrator(texts) if self.narrator else self.services.narration(texts, rate=(self.config.get("voice") or {}).get("rate", -1))
            if result.get("backend") not in {"windows_sapi", "windows_onecore"}:
                raise ValueError("PLANEXIUM refuses cloud narration")
            path = self.context.artifact("narration/narration.segments.json")
            if not path.is_file():
                _write(path, result)
            return result, [path] + [Path(s["path"]) for s in result["segments"]]
        voice_request = {"scenes": science["scenes"], "voice": self.context.channel.voice_name}
        if self.config.get("voice"):
            voice_request["settings"] = self.config["voice"]
        voice = self.stage("narration", voice_request, speak)
        if episode_policy and not pilot:
            total_seconds = sum(float(segment["seconds"]) for segment in voice["segments"])
            minimum_seconds = float(episode_policy.get("target_minutes", [8])[0]) * 60 * 0.875
            maximum_seconds = float(episode_policy.get("target_minutes", [8, 12])[-1]) * 60 * 1.10
            if not minimum_seconds <= total_seconds <= maximum_seconds:
                raise ValueError(f"Long-form gate: measured narration is {total_seconds/60:.1f} minutes; target is 8-12 minutes")
        if self.director and (self.context.artifact("motion-copy.json").exists()
                              or not (self.context.artifact("checkpoints/render.json").exists()
                                      or any(self.context.artifact("repairs").glob("*/render.json")))):
            from openjarvis.one_agents.planexium_direction import validate_motion
            def direct():
                result = self.director(science, voice)
                copy = validate_motion(result, science, voice)
                path = self.context.artifact("motion-copy.json")
                _write(path, copy)
                return copy, [path]
            self.stage("direction", {"science": science, "timing": voice["segments"], "version": 1}, direct)
        if self.config.get('editing_mode') == 'footage_first' and not (root/'cinematic-plan.json').exists():
            if self.editorial is None:raise RuntimeError('Footage-first production requires an editorial planning adapter')
            _write(root/'cinematic-plan.json', self.editorial(science))
        def acquire():
            media = {"scenes": {}}
            stock_requests, stock_targets, files = [], [], []
            for i, (scene, segment) in enumerate(zip(science["scenes"], voice["segments"], strict=True), 1):
                kind = scene.get("visual_kind", "image")
                if kind == "stock":
                    if self.config.get('editing_mode') == 'footage_first':
                        media['scenes'][str(i)]={'kind':'graphic','assets':[],'credit':'Footage acquired by cinematic editor'}
                        continue
                    from openjarvis.one_agents.planexium_adapters import stock_search
                    query, subject, blocked = stock_search(scene["media_query"])
                    count = max(1, math.ceil(float(segment["seconds"]) / 12))
                    for _ in range(count):
                        stock_requests.append({"query": query, "title": science["video_title"],
                                               "subject": scene.get("subject") or subject, "blocked_keywords": blocked})
                        stock_targets.append(str(i))
                    media["scenes"][str(i)] = {"kind": "stock", "assets": [], "credit": "Envato - illustrative footage"}
                elif kind == "obs":
                    if self.config.get("render_backend") == "resolve_fusion":
                        # A photo article is evidence media, not an obligation
                        # to record a browser. Keep its original figure credits.
                        rows = space_research.article_images(scene["url"],
                            self.context.artifact("sources/article-images"), read=self.source_reader)
                        if rows:
                            media["scenes"][str(i)] = {"kind":"image","assets":rows,"credit":scene["url"]}
                            files.extend(Path(row["path"]) for row in rows)
                            files.extend(Path(row["path"]).with_name("source-receipt.json") for row in rows)
                            continue
                    if self.capture is None:
                        raise RuntimeError("An explicitly requested OBS scene needs its capture adapter")
                    capture = self.services.capture([{"id": str(i), "url": scene["url"], "title": scene["title"],
                        "seconds": min(float(segment["seconds"]), 12.0)}], allowed_hosts=tuple(space_research.SOURCE_HOSTS), adapter=self.capture)
                    rows = capture["captures"]
                    media["scenes"][str(i)] = {"kind": "obs", "assets": rows, "credit": scene["url"]}
                    files.extend(Path(r["path"]) for r in rows)
                elif kind == "graphic":
                    media["scenes"][str(i)] = {"kind": "graphic", "assets": [], "credit": "The Planexium - original graphic"}
                else:
                    row = space_research.nasa_image(scene["media_query"], self.context.artifact(f"sources/scene-{i}"), read=self.source_reader)
                    media["scenes"][str(i)] = {"kind": "image", "assets": [row], "credit": row["credit"]}
                    files += [Path(row["path"]), Path(row["path"]).with_name("source-receipt.json")]
            if len(stock_requests) > 24:
                raise ValueError("Stock plan exceeds bounded 24-clip budget; revise visual mix")
            if stock_requests:
                if self.stock is None:
                    raise RuntimeError("Licensed stock adapter is required")
                result = self.services.acquire(stock_requests, adapter=self.stock)
                if len(result.get("assets", [])) != len(stock_targets):
                    raise ValueError("Envato acquisition receipt does not cover the stock plan")
                for target, row in zip(stock_targets, result["assets"], strict=True):
                    media["scenes"][target]["assets"].append(row)
                    files.append(Path(row["path"]))
            path = self.context.artifact("media-manifest.json")
            _write(path, media)
            return media, files + [path]
        media = self.stage("media", {"science": science, "timing": voice["segments"]}, acquire)
        # Pin the renderer for this mission. A configuration rollout must not
        # retroactively invalidate an already sealed review master.
        renderer_path = root / "render-backend.json"
        if renderer_path.exists():
            renderer_config = json.loads(renderer_path.read_text(encoding="utf-8"))
        else:
            renderer_config = ({"backend": "legacy"} if (root/"checkpoints/render.json").exists()
                else {"backend": self.config.get("render_backend", "legacy"),
                      "resolve": self.config.get("resolve")})
            _write(renderer_path, renderer_config)
        resolve_settings = renderer_config.get("resolve") if renderer_config["backend"] == "resolve_fusion" else None
        if renderer_config["backend"] == "resolve_fusion" and not resolve_settings:
            raise ValueError("Resolve/Fusion configuration missing; no legacy fallback")
        def cut():
            if self.renderer:
                result = self.renderer(root)
            else:
                tools = Path(self.config.get("edit_tools") or Path.home() / "Documents" / "LAO" / "yatra-edit")
                from openjarvis.one_agents.planexium_render_job import run_render
                from openjarvis.one_agents import stages
                result = run_render(root, tools, motion_format=self.config.get("motion_format"),
                    resolve_settings=resolve_settings,
                    on_progress=(lambda progress: stages.set_stage("planexium", stages.EXECUTING,
                        str(progress.get('detail') or
                            f"{progress.get('status','rendering').replace('_',' ')}: scene {progress.get('scene',0)} / {progress.get('total_scenes',0)}")))
                        if self.config.get("_agent_job_id") else None)
            expected_master = self.context.artifact("edit/master.mp4")
            if Path(result["master"]).resolve() != expected_master or not expected_master.stat().st_size:
                raise ValueError("Renderer did not produce the mission's own master")
            rows = json.loads(self.context.artifact("edit/qc-report.json").read_text(encoding="utf-8"))
            required = {"resolution", "audio stream", "picture vs voice", "black frames", "narration gaps", "per-scene sync"}
            if (not isinstance(rows, list) or not required.issubset({r.get("check") for r in rows})
                    or any(r.get("level") == "FAIL" for r in rows)):
                raise ValueError("Technical QC failed or mandatory checks are missing")
            return result, [self.context.artifact("edit/master.mp4"), self.context.artifact("edit/qc-report.json")]
        from openjarvis.one_agents.youtube_motion import library_hash
        from openjarvis.one_agents.planexium_shared_motion import fingerprint as shared_motion_hash
        tools = Path(self.config.get("edit_tools") or Path.home() / "Documents" / "LAO" / "yatra-edit")
        render_request = {"science": science, "media": media, "voice": voice,
            "visual_repair": _hash(root / "visual-repair.json") if (root / "visual-repair.json").exists() else None,
            "cinematic_plan": _hash(root / "cinematic-plan.json") if (root / "cinematic-plan.json").exists() else None,
            "motion_library": library_hash(), "installed_motion_library": shared_motion_hash(tools) if self.config.get("editing_mode")=="footage_first" else None, "motion_format": self.config.get("motion_format"),
            "motion_copy": _hash(root / "motion-copy.json") if (root / "motion-copy.json").exists() else None}
        if resolve_settings and not renderer_config.get("legacy_parent_request"):
            from openjarvis.one_agents import planexium_resolve
            render_request["resolve"] = {"settings": resolve_settings, "adapter": _hash(Path(planexium_resolve.__file__))}
        if (root / "asset-repair.json").exists():
            render_request["asset_repair"] = _hash(root / "asset-repair.json")
        master = self.stage("render", render_request, cut)
        return self.package(science, voice, evidence, master)

    def package(self, science, voice, evidence, master):
        def build():
            result=self._package(science,voice,evidence,master)
            package=json.loads(Path(result["output"]).read_text(encoding="utf-8"))
            files=[self.context.artifact(name) for name in ["production-plan.json",
                "seo/youtube-seo-package.json","edit/subtitles.srt","review-gate.json","thumbnail/thumbnail-experiment.json"]]
            files += [Path(package["thumbnail_path"]), *[Path(v["path"]) for v in package["thumbnail_experiment"]["variants"]]]
            for name in ['cinematic-plan.json','edit/cinematic-assets.json','edit/cinematic-edit-report.json','edit/music-bed.m4a','edit/resolved-editorial-plan.json','edit/timeline-uniqueness.json','edit/shared-director-plan.json','edit/resolve-project.drp','edit/resolve.comp','edit/resolve-receipt.json']:
                path=self.context.artifact(name)
                if path.exists():files.append(path)
            audit=self.context.artifact('edit/cinematic-edit-report.json')
            if audit.exists():
                value=json.loads(audit.read_text(encoding='utf-8'))
                files += [Path(p) for p in sorted({s['asset']['path'] for s in value['shots']} | {value['music']['path']})]
            return result,files
        reviewed_inputs = {}
        for name in ('completed-thumbnail-v1.json', 'completed-thumbnail-v2.json', 'caption-alignment-v1.json'):
            path = self.context.root / 'repairs' / name
            if path.exists():
                reviewed_inputs[name] = _hash(path)
        return self.stage("package", {"science":science,"voice":voice,"evidence":evidence,
            "master_sha256":_hash(Path(master["master"])),"channel":asdict(self.context.channel),"version":3,
            **({'reviewed_inputs': reviewed_inputs} if reviewed_inputs else {})},build)

    def _package(self, science, voice, evidence, master):
        root = self.context.root
        script = "\n".join(f"[{_stamp(v['start'])}-{_stamp(v['end'])}]\n{s['narration']}"
                            for s, v in zip(science["scenes"], voice["segments"], strict=True))
        record = {"brand": "planexium", "video_title": science["video_title"], "language": "en",
                  "full_script": script, "claim_ledger": evidence,
                  "scene_plan": "\n".join(f"{i}:\npurpose: {s['title']}\non_screen_text: {s.get('screen_text',s['title'])}"
                                          for i, s in enumerate(science["scenes"], 1))}
        _write(self.context.artifact("production-plan.json"), [record])
        package = self.services.metadata(record)
        hook = str(science.get("thumbnail_hook") or " ".join(science["video_title"].split()[:3])).upper()
        if not 1 <= len(hook.split()) <= 4:
            raise ValueError("Thumbnail hook must have 1-4 words")
        package["thumbnail"]["variants"][0]["text"] = hook
        package["thumbnail"]["variants"][0]["left_usp"] = science["scenes"][0].get("media_query") or science["video_title"]
        editorial_path=root/'cinematic-plan.json'
        if editorial_path.exists():
            editorial=json.loads(editorial_path.read_text(encoding='utf-8'))
            if editorial.get('packaging'):
                from openjarvis.one_agents.planexium_packaging import apply_packaging
                apply_packaging(package,editorial['packaging'],science)
        def thumbnail():
            if self.image is None:
                raise RuntimeError("Portrait-free ChatGPT image binding required")
            result = self.services.thumbnail_experiment(package, generate=self.image)
            return result, [Path(result["path"]), self.context.artifact("thumbnail/thumbnail-experiment.json"),
                            *[Path(row["path"]) for row in result["variants"]]]
        from openjarvis.one_agents.planexium_completed_thumbnail import selection_request
        thumb = self.stage("thumbnail", {"title": science["video_title"], "brief": package["thumbnail"],
                                         "experiment_version": 1, "variant_count": 3,
                                         **selection_request(root)}, thumbnail)
        package["thumbnail_path"] = thumb["path"]
        package["thumbnail"]["variants"] = [row["creative"] for row in thumb["variants"]]
        package["thumbnail_experiment"] = {"winner": thumb["winner"], "winner_score": thumb["winner_score"],
            "audience_winner": thumb.get("audience_winner"), "winner_status": thumb.get("winner_status", "legacy_internal_selection"),
            "variants": [{"name": row["variant"], "path": row["path"], "score": row["preupload_score"]}
                         for row in thumb["variants"]], "selection": thumb["selection"]}
        subtitles, index = [], 1
        for scene, segment in zip(science["scenes"], voice["segments"], strict=True):
            words = scene["narration"].split()
            groups = [words[i:i + 8] for i in range(0, len(words), 8)]
            for j, group in enumerate(groups):
                start = segment["start"] + segment["seconds"] * j / len(groups)
                end = segment["start"] + segment["seconds"] * (j + 1) / len(groups)
                subtitles.append(f"{index}\n{_stamp(start,srt=True)} --> {_stamp(end,srt=True)}\n{' '.join(group)}\n")
                index += 1
        from openjarvis.one_agents.planexium_caption_alignment import reviewed_cues
        aligned = reviewed_cues(root, voice)
        if aligned is not None:
            subtitles = [f"{i}\n{_stamp(cue['start'],srt=True)} --> {_stamp(cue['end'],srt=True)}\n{cue['text']}\n"
                         for i, cue in enumerate(aligned, 1)]
        caption = self.context.artifact("edit/subtitles.srt")
        caption.write_text("\n".join(subtitles), encoding="utf-8")
        package.update(master=master["master"], caption=str(caption), source_evidence=str(self.context.artifact("evidence.json")),
                       human_science_review_required=True, human_rights_review_required=True,
                       subtitle_word_timing=("reviewed local ASR cue boundaries; verbatim narration; not forced word alignment" if aligned is not None else "estimated within measured narration segments"), public_publish_authorized=False)
        if (root/'edit/resolve-receipt.json').exists():
            package['resolve_project'] = str(root/'edit/resolve-project.drp')
            package['resolve_render_receipt'] = str(root/'edit/resolve-receipt.json')
        if self.context.artifact('edit/cinematic-edit-report.json').exists():
            package['editorial_evidence']=str(self.context.artifact('edit/cinematic-edit-report.json'))
            package['music_and_stock_receipts']=str(self.context.artifact('edit/cinematic-assets.json'))
            package['music_bed_stem']=str(self.context.artifact('edit/music-bed.m4a'))
        path = self.context.artifact("seo/youtube-seo-package.json")
        _write(path, package)
        gate = {"brand": "planexium", "status": "awaiting_human_review", "package": str(path),
                "package_sha256": _hash(path), "master_sha256": _hash(Path(master["master"])),
                "public_publish_authorized": False, "review": ["science claims", "imagery rights/credits", "voice/pronunciation", "thumbnail", "subtitle timing"]}
        gate["thumbnail_sha256"] = _hash(Path(package["thumbnail_path"]))
        gate["caption_sha256"] = _hash(caption)
        _write(self.context.artifact("review-gate.json"), gate)
        return {"agent": "PLANEXIUM", "mission_id": self.context.mission_id, "status": "awaiting_human_review", "production_complete": True,
                "published": False, "output": str(path), "master": master["master"], "gate": str(self.context.artifact("review-gate.json"))}


def daily_commission(day: str | None = None) -> dict:
    date = datetime.fromisoformat(day).date() if day else datetime.now(ZoneInfo("Asia/Kolkata")).date()
    topic = TOPICS[date.toordinal() % len(TOPICS)]
    return {"brand": "planexium", "production_date": date.isoformat(), "mission_id": f"daily-{date:%Y%m%d}", "auto_discover": True, **topic}


def head_job(job: dict, *, enqueue) -> dict:
    """HELIOS's additional channel hat; never routes this work to YATRA."""
    raw = str(job.get("task") or "")
    # The company clock prefixes every task with its durable trigger name.
    raw = re.sub(r"^\[ONE trigger: [^\]]+\]\s*", "", raw)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"brand": "planexium", "topic": raw}
    if not isinstance(payload, dict) or payload.get("brand") != "planexium":
        raise ValueError("HELIOS PLANEXIUM route requires an unambiguous channel")
    if job.get("mode") == "report" or payload.get("stage") == "production_complete":
        return {"agent": "HELIOS", "brand": "planexium", "status": payload.get("status"),
                "published": False, "output": payload.get("output"),
                "content": "PLANEXIUM local package returned; human science/rights review and public-release approval remain."}
    if str(job.get("mode")) != "execute":
        return {"agent": "HELIOS", "brand": "planexium", "mode": "plan",
                "content": "PLANEXIUM production uses local Windows voice, shared services and a human release gate."}
    commission = payload.get("commission") or daily_commission(payload.get("production_date"))
    if payload.get("topic"):
        commission["topic"] = payload["topic"]
        if not payload.get("sources"):
            raise ValueError("A custom science topic needs explicit authoritative source URLs")
        commission["sources"] = payload["sources"]
        commission["auto_discover"] = False
    follow = enqueue("planexium", json.dumps({"brand": "planexium", "commission": commission}),
                     mode="execute", dedupe_key=f"youtube:planexium:{commission['mission_id']}:produce")
    return {"agent": "HELIOS", "brand": "planexium", "handed_to": {"agent": "PLANEXIUM", "job_id": follow["id"]}}


def run_job(job: dict) -> dict:
    payload = json.loads(str(job.get("task") or "{}"))
    if payload.get("brand") != "planexium":
        raise ValueError("PLANEXIUM refuses another channel's job")
    config = load_config()
    if config.get("providers_enabled") is not True:
        return {"agent": "PLANEXIUM", "status": "awaiting_setup_approval", "production_complete": False,
                "published": False, "content": "Provider execution remains disabled; approved rollout is required."}
    if not config.get("integration_approval_id"):
        raise PermissionError("Live LAO integration requires a channel-specific OLYMPUS approval receipt")
    db_path = SUITE / "one-company" / "data" / "company.db"
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT status,decided_by,action_type,payload_json FROM approvals WHERE approval_id=?",
                         (config["integration_approval_id"],)).fetchone()
    if (not row or row[:3] != ("approved", "olympus", "lao_integration_wire")
            or json.loads(row[3]).get("brand") != "planexium"):
        raise PermissionError("LAO integration approval is absent or belongs to another channel")
    commission = payload.get("commission") or daily_commission(payload.get("production_date"))
    requested_commission = dict(commission)
    context = context_for(commission["mission_id"], config)
    ledger_path = context.root.parent / "production-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    unfinished = next((key for key, row in ledger.items() if row.get("status") in {"producing", "needs_resume"}), None)
    # An old, dated news commission must not consume every subsequent daily
    # slot indefinitely. Preserve its files for a separately researched revision.
    if unfinished and unfinished != requested_commission["mission_id"]:
        previous_path = context_for(unfinished, config).artifact("commission.json")
        if previous_path.exists():
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
            if news_commission_expired(previous, requested_commission):
                ledger[unfinished].update(status="needs_fresh_research",
                    recovery_reason="Dated news commission expired before completion; retained for revision")
                _write(ledger_path, ledger)
                unfinished = None
    if unfinished:
        context = context_for(unfinished, config)
    commission_path = context.artifact("commission.json")
    if commission_path.exists():
        commission = json.loads(commission_path.read_text(encoding="utf-8"))
    else:
        if commission.get("auto_discover"):
            recent = {row.get("topic", "") for row in ledger.values()}
            try:
                commission.update(space_research.discover_topic(recent))
            except space_research.NoUnusedTopicError:
                # Daily commissions carry a curated evergreen topic and
                # authoritative sources so an exhausted news feed need not
                # turn a valid production slot into a failed job.
                if not str(commission.get("topic") or "").strip() or not commission.get("sources"):
                    raise
        _write(commission_path, commission)
    if job.get("id"):
        from openjarvis.one_agents import runtime
        register_checkpoint_owner(str(job["id"]), context, runtime._connect)
    from openjarvis.one_agents.planexium_adapters import BUILD_SHA as ADAPTER_BUILD
    draft_path = context.artifact("script-draft.json")
    # A draft may be created before its writer has finished. Treat an empty
    # checkpoint as absent so the pipeline can use its normal writer path.
    script_sealed = context.artifact("checkpoints/script.json").is_file()
    draft = (json.loads(draft_path.read_text(encoding="utf-8"))
             if not script_sealed and draft_path.is_file() and draft_path.stat().st_size else None)
    result = bound_pipeline(context, {**config, "_agent_job_id": job.get("id"),
        "_production_build": {"pipeline": BUILD_SHA, "adapters": ADAPTER_BUILD}}).produce(commission, plan=draft)
    if result.get("production_complete") and requested_commission["mission_id"] != context.mission_id:
        result["deferred_commission"] = requested_commission
    return result


def news_commission_expired(previous: dict, requested: dict) -> bool:
    if not previous.get("auto_discover") or not previous.get("production_date") or not requested.get("production_date"):
        return False
    return (datetime.fromisoformat(requested["production_date"]).date()
            - datetime.fromisoformat(previous["production_date"]).date()).days > 1


def enqueue_deferred_commission(result: dict, *, enqueue):
    commission = result.get("deferred_commission")
    if not result.get("production_complete") or not commission:
        return None
    if commission.get("brand") != "planexium" or commission.get("mission_id") == result.get("mission_id"):
        raise ValueError("Deferred production must be a distinct PLANEXIUM commission")
    # HELIOS already commissioned this exact work before recovery selected the
    # older mission. Use a distinct key so completion of the old run cannot
    # consume today's normal handoff key and silently skip today's video.
    return enqueue("planexium", json.dumps({"brand":"planexium", "commission":commission}), mode="execute",
        dedupe_key=f"youtube:planexium:{commission['mission_id']}:after-resume:{result['mission_id']}")


def register_checkpoint_owner(job_id: str, context: ProductionContext, connect):
    """A durable mission is safe to resume after an unrelated worker replacement."""
    if not context.artifact("commission.json").is_file():
        raise ValueError("Cannot register recovery before a durable commission exists")
    from openjarvis.one_agents import job_recovery
    job_recovery.attach(connect, job_id, context.mission_id, kind="planexium_checkpoint")


def recover_known_source_drift(connect, job_id: str) -> str:
    """Migrate one allow-listed stale source and queue a checkpoint-safe retry."""
    with connect() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT task,status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row or row["status"] != "failed":
        return ""
    payload = json.loads(row["task"])
    commission = payload.get("commission") or {}
    if commission.get("brand") != "planexium" or not commission.get("mission_id"):
        return ""
    old_sources = list(commission.get("sources", []))
    migrated = [SOURCE_ALIASES.get(url, url) for url in old_sources]
    if migrated == old_sources:
        return ""
    context = context_for(commission["mission_id"], load_config())
    durable_commission = context.artifact("commission.json")
    if durable_commission.exists():
        saved = json.loads(durable_commission.read_text(encoding="utf-8"))
        if saved.get("source_revision") == "known-alias-recovery-v1":
            return ""
    with resource_lease(context.media_root / ".leases", "planexium-production"):
        tag = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        repair_root = context.artifact(f"repairs/{tag}")
        moved = []
        for relative in ("evidence.json", "checkpoints/research.json", "receipts/writer.json"):
            source = context.artifact(relative)
            if source.exists():
                target = repair_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                moved.append(relative)
        commission["sources"] = migrated
        commission["source_revision"] = "known-alias-recovery-v1"
        _write(context.artifact("commission.json"), commission)
        _write(repair_root / "source-recovery.json", {
            "failed_job": job_id, "reason": "Known authoritative source URL changed target",
            "archived": moved, "previous_sources": old_sources, "replacement_sources": migrated,
        })
        ledger_path = context.root.parent / "production-ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
        ledger.setdefault(context.mission_id, {}).update(
            status="needs_resume", recovery_reason="known_source_alias_migrated")
        _write(ledger_path, ledger)
    payload["commission"] = commission
    from openjarvis.one_agents.runtime import enqueue_job
    retry = enqueue_job("planexium", json.dumps(payload), mode="execute", tier="fast",
        dedupe_key=f"youtube:planexium:{commission['mission_id']}:source-recovery-v1")
    return f"migrated stale authoritative source and queued {retry['id']} from saved mission"


def bound_pipeline(context: ProductionContext, config: dict) -> Pipeline:
    if config.get("providers_enabled") is not True:
        raise PermissionError("Provider execution remains disabled")
    from openjarvis.one_agents import runtime
    from openjarvis.one_agents.planexium_adapters import LaoDraft, ChatGPTAdapter, EnvatoAdapter, OBSAdapter, production_home
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool
    lao = Path(config.get("lao_root") or Path.home() / "Documents" / "LAO")
    draft = LaoDraft(LaoOrchestratorTool(), config.get("lao_folder_id") or runtime._PEITHO_LAO_FOLDER_ID,
                     tuple(Path(p) for p in config.get("artifact_roots", [])) or runtime._YATRA_ROBOT_ARTIFACTS)
    queue = SUITE / "data" / "agent_queue.db"
    provider_lock = Path(config["provider_lock"])
    profile_root = Path(config["browser_root"])
    from openjarvis.one_agents.planexium_recovery import recover_dead_leases
    recover_dead_leases(context, draft, provider_lock, SUITE / "data" / "planexium" / "leases", wait_seconds=3600)
    chat = ChatGPTAdapter(draft, context, queue=queue, profile_root=profile_root)
    stock = EnvatoAdapter(draft, lao / "yatra-acquisition" / "workflow.yaml", context, queue,
                         provider_lock, wait_seconds=1800, profile_root=profile_root)
    capture = OBSAdapter(draft, lao / "yatra-capture" / "workflow.yaml", context, queue,
                         SUITE / "data" / "planexium" / "leases", prepare_video=True, wait_seconds=1800, profile_root=profile_root)
    from openjarvis.one_agents import stages
    draft.on_wait = lambda detail: stages.set_stage("planexium", stages.AWAITING_WORKER, detail)
    draft.on_progress = lambda detail: stages.set_stage("planexium", stages.EXECUTING, detail)
    labels = {"research": "Researching authoritative science sources", "script": "Writing and validating the source-linked script",
              "narration": "Synthesizing local Windows narration", "media": "Acquiring licensed footage and official imagery",
              "direction": "Authoring narration-aligned kinetic motion copy",
              "render": "Rendering the kinetic director and running technical QC", "thumbnail": "Generating and scoring three original thumbnails"}
    return Pipeline(context, config, writer=chat.write, image=chat.image, stock=stock, capture=capture, director=chat.direct,
                    editorial=chat.editorial,
                    on_stage=lambda name: stages.set_stage("planexium", stages.EXECUTING, labels.get(name, name)))


def repackage_job(payload: dict) -> dict:
    """LYRA can finish/recheck a cached PLANEXIUM package without using Sonia assets."""
    if payload.get("brand") != "planexium" or payload.get("stage") != "package":
        raise ValueError("LYRA requires an explicit PLANEXIUM packaging handoff")
    config = load_config()
    context = context_for(payload["mission_id"], config)
    # Primary production already generated the thumbnail. Packaging retries
    # must not silently spend another image-generation request.
    if not context.artifact("checkpoints/thumbnail.json").is_file():
        raise ValueError("PLANEXIUM thumbnail checkpoint required before LYRA packaging")
    def load(name):
        return json.loads(context.artifact(name).read_text(encoding="utf-8"))
    with resource_lease(context.media_root / ".leases", "planexium-production"):
        result = Pipeline(context, {**config, "_agent_id": "lyra"}).package(load("science-plan.json"), load("narration/narration.segments.json"),
            load("evidence.json"), {"master": str(context.artifact("edit/master.mp4"))})
    return {**result, "agent": "LYRA"}


def install_disabled_trigger() -> dict:
    """Explicit operator setup only; never auto-enables a daily schedule."""
    import importlib.util

    path = SUITE / "one-company" / "floors" / "_work" / "triggers.py"
    spec = importlib.util.spec_from_file_location("planexium_trigger_setup", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    definition = SUITE / "one-company" / "floors" / "floor_12_youtube_studio" / "agents" / "planexium" / "daily-trigger.json"
    trigger = json.loads(definition.read_text())
    if trigger.get("enabled") is not False:
        raise ValueError("PLANEXIUM trigger definition must remain disabled during setup")
    db_path = SUITE / "data" / "company_triggers.db"
    if db_path.exists():
        with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            existing = db.execute("SELECT enabled FROM triggers WHERE id=?", (trigger["id"],)).fetchone()
        if existing:
            return {"status": "already_present", "enabled": bool(existing[0]), "unchanged": True}
    return module.upsert(trigger)


STANDING_PRIVATE_SCOPE = "private_upload_standing"


def standing_private_approval(config: dict, db_path: Path | None = None) -> dict | None:
    """The Chairman's standing OLYMPUS approval for Planexium private uploads, or None.

    Granted 2026-10-22 ("Planexium ka API upload in private mode ... agent mein jod do"): private drafts on the
    Planexium channel only. Going public stays a person's Studio action."""
    db_path = db_path or SUITE / "one-company" / "data" / "company.db"
    if not Path(db_path).is_file():
        return None
    with sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT payload_json FROM approvals WHERE status='approved' AND decided_by='olympus' "
                          "AND action_type='publish_routine_update' ORDER BY decided_at DESC").fetchall()
    for (raw,) in rows:
        try:
            granted = json.loads(raw or "{}")
        except ValueError:
            continue
        if (granted.get("brand") == "planexium" and granted.get("scope") == STANDING_PRIVATE_SCOPE
                and granted.get("channel_id") == config.get("channel_id")
                and granted.get("synthetic") in ("yes", "no")):
            return granted
    return None


def stage_private(payload: dict, *, approval_db: Path | None = None, adapter=None) -> dict:
    """Only an existing OLYMPUS decision bound to this exact package authorizes staging."""
    config = load_config()
    context = context_for(payload["mission_id"], config)
    path = context.artifact("seo/youtube-seo-package.json")
    gate_path = context.artifact("review-gate.json")
    if gate_path.exists():
        selected = Path(json.loads(gate_path.read_text(encoding="utf-8"))["package"]).resolve()
        if not selected.is_relative_to(context.root.resolve()):
            raise ValueError("Review package escapes mission")
        path = selected
    package = json.loads(path.read_text(encoding="utf-8"))
    channel = config.get("channel_id")
    if not channel or not config.get("credential_asset"):
        raise ValueError("The Planexium channel ID and credential-asset binding have not been configured")
    db_path = approval_db or SUITE / "one-company" / "data" / "company.db"
    if payload.get("standing"):
        # The Chairman's standing approval covers private uploads only; each video must still be exactly the
        # package, master, thumbnail and subtitles its review gate recorded after ARES passed the SEO audit.
        standing = standing_private_approval(config, db_path)
        if standing is None:
            raise PermissionError("No standing OLYMPUS approval for Planexium private uploads")
        if not gate_path.exists():
            raise PermissionError("A standing private upload needs the mission's review gate")
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        if gate.get("independent_review_pending"):
            raise PermissionError("Owner-reviewed SEO revision awaits independent acceptance before ECHO")
        if gate.get("status") != "awaiting_human_review" or gate.get("seo_audit_passed") is not True:
            raise PermissionError("The review gate has not passed ARES's SEO audit")
        approved = {**gate, "brand": "planexium", "channel_id": channel, "scope": "private_upload",
                    "synthetic": standing.get("synthetic")}
    else:
        with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute("SELECT status,decided_by,action_type,payload_json FROM approvals WHERE approval_id=?",
                             (payload.get("approval_id"),)).fetchone()
        if not row or row[:3] != ("approved", "olympus", "publish_routine_update"):
            raise PermissionError("An existing human OLYMPUS approval is required for private staging")
        approved = json.loads(row[3])
    expected = {"brand": "planexium", "channel_id": channel, "package_sha256": _hash(path), "scope": "private_upload"}
    if any(approved.get(k) != v for k, v in expected.items()):
        raise PermissionError("Approval does not match the exact channel/package/private scope")
    # Hash the actual master as well: package metadata alone cannot authorize a replaced video.
    if approved.get("master_sha256") != _hash(Path(package["master"])):
        raise PermissionError("Approved master changed")
    from openjarvis.one_agents.planexium_seo import require_seo
    require_seo(package)
    for key, approval_key in (("thumbnail_path", "thumbnail_sha256"), ("caption", "caption_sha256")):
        if not package.get(key) or approved.get(approval_key) != _hash(Path(package[key])):
            raise PermissionError("Approval does not match the thumbnail/subtitle artifacts")
    package["channel_id"] = channel
    if adapter is None:
        from openjarvis.one_agents.youtube_production import ExistingPrivateUploader

        lao = Path(config.get("lao_root") or Path.home() / "Documents" / "LAO")
        adapter = ExistingPrivateUploader(lao / "yatra-upload" / "youtube_api_upload.py",
            credential_asset=config["credential_asset"], channel_id=channel, synthetic=approved.get("synthetic"))
    result = ProductionServices(context).upload_private(
        package, expected_channel_id=channel, adapter=adapter, authorized=True)
    # Distribution is a separate durable stage from production and public
    # review.  Record the private draft immediately so Floor 12 never shows a
    # completed ECHO upload beside stale ``awaiting_review`` production state.
    health_path = context.artifact("production-health.json")
    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else {}
    health.update(status="uploaded_private", current_stage="review", production_complete=True,
                  uploaded=True, published=False, public_publish_authorized=False,
                  private_video_id=result.get("video_id"), blocked_reason=None, error_class=None,
                  updated_at=datetime.now(timezone.utc).isoformat())
    _write(health_path, health)
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate.update(private_upload_complete=True, private_video_id=result.get("video_id"),
                public_publish_authorized=False)
    _write(gate_path, gate)
    ledger_path = context.root.parent / "production-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    ledger.setdefault(context.mission_id, {})["status"] = "uploaded_private"
    _write(ledger_path, ledger)
    return result


def _channel_uploader(config: dict, ledger: Path):
    """A fresh uploader module bound to Planexium's own credential, channel and mission ledger.

    The uploader script is shared with Sonia's channel, so every call gets its own instance: Planexium's bindings
    can never leak into Sonia's sweep or the other way round."""
    import importlib.util
    import uuid
    lao = Path(config.get("lao_root") or Path.home() / "Documents" / "LAO")
    spec = importlib.util.spec_from_file_location(f"planexium_uploader_{uuid.uuid4().hex}",
                                                  lao / "yatra-upload" / "youtube_api_upload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ASSET = config["credential_asset"]
    module.EXPECTED_CHANNEL_ID = config["channel_id"]
    module.LEDGER = ledger
    return module


def mission_ledgers(config: dict) -> list[Path]:
    """Every Planexium mission's own upload ledger (one per mission folder, never Sonia's ledger)."""
    root = context_for("daily-00000000", config).root.parent
    return sorted(root.glob("*/upload-ledger.json"))


def pending_comment_videos(config: dict | None = None) -> list[str]:
    """Planexium uploads that still owe their channel comment (posted once the video is public)."""
    config = config or load_config()
    if not config.get("channel_id") or not config.get("credential_asset"):
        return []
    owed = []
    for ledger in mission_ledgers(config):
        module = _channel_uploader(config, ledger)
        owed += [str(entry.get("video_id")) for _, entry in module.pending_comment_entries(module.ledger_load())]
    return owed


def post_pending_comments(config: dict | None = None) -> list[dict]:
    """Post each public Planexium video's comment from its own package, mission by mission."""
    config = config or load_config()
    results = []
    for ledger in mission_ledgers(config):
        module = _channel_uploader(config, ledger)
        if module.pending_comment_entries(module.ledger_load()):
            results += [{"channel": "planexium", **row} for row in module.post_pending_comments()]
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PLANEXIUM local production configuration checks")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--date")
    parser.add_argument("--install-disabled-trigger", action="store_true")
    args = parser.parse_args()
    config = load_config()
    if args.install_disabled_trigger:
        print(json.dumps(install_disabled_trigger()))
        raise SystemExit(0)
    print(json.dumps({"brand": config["brand"], "providers_enabled": config["providers_enabled"],
                      "daily_commission": daily_commission(args.date), "public_publish_authorized": False}, indent=2))
