"""Origin to Ovation's resumable, channel-scoped Floor 12 pipeline."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from contextlib import contextmanager
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path("E:/ONE-SUITE/data/youtube/origin_to_ovation")
BRAND = "origin_to_ovation"


def commission_next(job):
    """Create the next queued, evidence-backed mission for a scheduler fire.

    Topic research remains an explicit durable input.  This function never
    guesses an athlete from prose and never reuses somebody already present in
    the permanent content calendar.
    """
    queue_path = ROOT / "commission-queue.json"
    if not queue_path.is_file():
        queue_path = Path(__file__).with_name("origin_to_ovation_commission_queue.json")
    if not queue_path.is_file():
        raise ValueError("Origin to Ovation commission queue is missing")
    queue = read(queue_path)
    candidates = queue.get("candidates") or []
    calendar_path = ROOT / "content-calendar.json"
    calendar = read(calendar_path) if calendar_path.is_file() else {"episodes": []}
    used = {str(row.get("subject_id") or "") for row in calendar.get("episodes", [])}
    candidate = next((row for row in candidates if row.get("status", "ready") == "ready"
                      and row.get("subject_id") not in used), None)
    if candidate is None:
        raise ValueError("No evidence-backed, duplicate-safe canonical subject remains in the commission queue")
    required = ("subject_id", "subject", "selection", "working_title",
                "central_dramatic_question", "sources", "reference_stages")
    if any(not candidate.get(key) for key in required):
        raise ValueError("Queued Origin to Ovation subject is missing commissioning evidence")
    if (len(candidate["reference_stages"]) < 3
            or not all(str(url).startswith("https://") for url in candidate["sources"].values())):
        raise ValueError("Queued Origin to Ovation evidence is incomplete")
    today = datetime.now().strftime("%Y-%m-%d")
    mission_id = f"{candidate['subject_id']}-{today}"
    path = ROOT / "missions" / mission_id
    if path.exists():
        raise ValueError(f"Commission path already exists: {mission_id}")
    for part in ("research", "runtime", "production/character-bible", "production/master-v1/images"):
        (path / part).mkdir(parents=True, exist_ok=True)
    voice = calendar.get("next_new_episode_voice") or {"name": "George", "voice_id": "JBFqnCBsd6RMkjVDRZzb"}
    manifest = {
        "schema": "one.youtube-mission/v1", "brand": BRAND,
        "display_name": "Origin to Ovation", "handle": "@OriginToOvation",
        "channel_account_label": "Chandan", "floor_id": "12",
        "head_agent": "helios", "agent_id": "chandan",
        "mission_id": mission_id, "subject": candidate["subject"],
        "subject_id": candidate["subject_id"], "master_language": "en-US",
        "production_phase": "reference_first", "current_model": True,
        "upload_authorized": False, "public_publish_authorized": False,
        "upload_policy": "package_only_until_later_explicit_user_instruction",
        # The scheduler invokes the already-tested channel runtime. Reserve an
        # exact-id deployment only for an explicit code migration/repair, not
        # for every ordinary biography, otherwise the normal worker correctly
        # leaves each episode parked in `reserved` forever.
        "fresh_code_required": False, "reference_review_required": True,
        "commissioned_date": today,
        "editorial_system": {
            "story": "truthful cold open -> formative years -> setbacks -> reinvention -> records-led resolution",
            "direction": "15 sourced chapters, five varied cinematic shots each, motivated motion and restrained sound design",
            "visual": "original photoreal cinematic CGI with recognisable age-locked editorial identity",
            "camera_variety": "front, three-quarter and true side views lead; rear views transitional only",
            "seo": "ARES story-specific metadata gate using the proven channel format",
        },
        "browser": {
            "owner": "origin-to-ovation-chandan-youtube",
            "profile_dir": str(ROOT / "chrome-profile"),
            "cdp_url": "http://127.0.0.1:9350", "start_url": "https://chatgpt.com/",
            "persistent": True, "shared_with_other_agents": False,
            "login_status": "user_confirmed_signed_in",
            "observed_studio_channel_id": "UClXpP8uPW7uSe0-APZBK0iw",
            "observed_route_requires_owner_confirmation": True,
        },
    }
    brief = {key: candidate[key] for key in required}
    brief.update({
        "voice": voice,
        "opening_hook": candidate.get("opening_hook", "The greatest ending only matters after the unfinished years before it."),
        "direction_requirements": candidate.get("direction_requirements", {}),
        "factual_guardrails": candidate.get("factual_guardrails", [
            "No invented dialogue, thoughts, private routines, hardship or travel details.",
            "Every milestone and statistic must remain within a linked official source.",
        ]),
        "upload_authorized": False,
        "scheduler_origin_job_id": job["id"],
    })
    write(path / "mission.json", manifest)
    write(path / "research" / "commission-brief.json", brief)
    write(path / "runtime" / "commission-receipt.json", {
        "status": "commissioned", "mission_id": mission_id,
        "subject_id": candidate["subject_id"], "origin_job_id": job["id"],
        "queue_sha256": digest(queue_path), "public_publish_authorized": False,
    })
    return {"brand": BRAND, "mission_id": mission_id, "stage": "commission"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@contextmanager
def building_progress(subject, plan):
    """Show CHANDAN's work on the building: image count every 30 s, then each phase; cleared however it ends.

    The building draws a worker's activity only from its stage, and CHANDAN never set one, so on 2026-10-22 it was
    invisible on Floor 12 while generating 75 images beside YATRA."""
    import threading
    from openjarvis.one_agents import stages
    phase = {"name": ""}
    stop = threading.Event()

    def show():
        done = sum(Path(s["image"]).is_file() for s in plan)
        stages.set_stage("chandan", stages.EXECUTING, phase["name"] or f"{subject} · images {done}/{len(plan)}")

    def report():
        while not stop.wait(30):
            show()

    def set_phase(name):
        phase["name"] = f"{subject} · {name}"
        stages.set_stage("chandan", stages.EXECUTING, phase["name"])

    show()
    threading.Thread(target=report, daemon=True).start()
    try:
        yield set_phase
    finally:
        stop.set()
        stages.clear_stage("chandan")


def mission_path(payload):
    if payload.get("brand") != BRAND:
        raise ValueError("Wrong brand")
    name = payload.get("mission_id", "")
    if not name or Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("Invalid mission")
    path = (ROOT / "missions" / name).resolve()
    if not path.is_relative_to((ROOT / "missions").resolve()):
        raise ValueError("Mission escapes channel")
    if not (path / "mission.json").is_file():
        raise ValueError("Mission must already be commissioned")
    return path


def transfer(job, path, target, stage, enqueue, evidence):
    evidence_hashes = {str(p): digest(p) for p in evidence}
    packet = {"brand": BRAND, "mission_id": path.name, "stage": stage,
              "from_agent": job["agent_id"], "parent_job": job["id"],
              "evidence": evidence_hashes}
    revision = hashlib.sha256(json.dumps(evidence_hashes, sort_keys=True).encode()).hexdigest()[:12]
    dispatch_options = {"reserved": True} if read(path / "mission.json").get("fresh_code_required") else {}
    receipt = enqueue(target, json.dumps(packet), mode="execute",
                      dedupe_key=f"{BRAND}:{path.name}:{stage}:{revision}", **dispatch_options)
    write(path / "runtime" / f"handoff-{job['agent_id']}-{target}.json",
          {**packet, "to_agent": target, "job_id": receipt["id"]})
    return {"status": "handed_off", "next_job": receipt["id"], "to_agent": target,
            "handed_to": {"agent": target.upper(), "job_id": receipt["id"]},
            "mission_id": path.name}


def verify_packet(payload, mission=None, agent=None):
    if agent in {"chandan", "ares", "echo"}:
        stage, sender = {"chandan": ("produce", "helios"), "ares": ("seo", "chandan"),
                         "echo": ("thumbnail_upload", "ares")}[agent]
        if payload.get("stage") != stage or payload.get("from_agent") != sender or not payload.get("evidence"):
            raise ValueError("Missing or invalid upstream handoff")
    for name, expected in payload.get("evidence", {}).items():
        path = Path(name).resolve()
        scope = Path(mission).resolve() if mission else ROOT.resolve()
        if not path.is_relative_to(scope) or not path.is_file() or digest(path) != expected:
            raise ValueError("Handoff artifact missing or changed")


def image_provider(path, shot):
    """The worker invokes the installed LAO ChatGPT provider; never uses Codex media."""
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool
    from openjarvis.one_agents.planexium_adapters import LaoDraft
    from openjarvis.one_agents.origin_to_ovation_faceless import enforce_prompt
    config = read(ROOT / "runtime-config.json")
    manifest = read(path / "mission.json")
    browser = manifest["browser"]
    if Path(browser["profile_dir"]).resolve() != (ROOT / "chrome-profile").resolve():
        raise ValueError("CHANDAN browser ownership mismatch")
    output = Path(shot["image"])
    if not output.resolve().is_relative_to(path.resolve()):
        raise ValueError("Output escapes mission")
    if output.is_file() and output.stat().st_size > 10000:
        return {"status": "reused", "sha256": digest(output)}
    provider = LaoDraft(LaoOrchestratorTool(), config.get("lao_folder_id"),
                        tuple(Path(p) for p in config["artifact_roots"]))
    steps = [
        {"action": "open_browser", "args": {
            "profile_dir": browser["profile_dir"], "cdp_url": browser["cdp_url"],
            "start_url": "https://chatgpt.com/"}},
        # Image generation is unavailable in temporary chats.  Open a regular
        # chat, then explicitly select New chat so a stale generating thread
        # cannot poison the next shot while the dedicated profile persists.
        # Continue the verified P50 conversation.  Its canonical reference is
        # already attached, which preserves identity and avoids 25 uploads.
        {"action": "navigate", "args": {
            "url": browser["chat_url"]}},
        {"action": "wait_for_any_selector", "args": {
            "selectors": ["#prompt-textarea", "[contenteditable='true']", "textarea"],
            "timeout_ms": 60000, "as": "composer"}},
        {"action": "generate_and_download_chatgpt_image", "args": {
            "prompt": enforce_prompt(shot["prompt"]) + "\nRequest marker: OTO-" + path.name + "-" + shot["shot_id"],
            "request_marker": "OTO-" + path.name + "-" + shot["shot_id"],
            "reference_image_path": shot["reference"],
            "reference_settle_seconds": 12,
            "filename": output.name, "max_attempts": 3, "allow_fresh_chat_recovery": False, "strict_fresh_turn": True,
            "stall_timeout_ms": 480000, "as": "image_path"}},
    ]
    result, provider_job = provider.run(
        f"Origin to Ovation - {manifest['subject']} - {shot['shot_id']}", steps, {},
        path / "runtime" / "providers" / f"{shot['shot_id']}.json",
        timeout=1500)
    source = provider.artifact(result, provider_job, output.name)
    source_hash = digest(source)
    for existing in (path / "production").rglob("*.png"):
        if existing.resolve() != output.resolve() and digest(existing) == source_hash:
            write(path / "runtime" / "images" / f"{shot['shot_id']}-rejected.json",
                  {"status": "rejected_stale_duplicate", "duplicate_of": str(existing),
                   "provider_job": provider_job, "sha256": source_hash})
            raise RuntimeError("Provider returned a previous scene instead of a fresh image")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)
    receipt = {"status": "generated", "provider": "ChatGPT via LAO",
               "provider_job": provider_job, "sha256": digest(output),
               "editorial_review": "pending"}
    write(path / "runtime" / "images" / f"{shot['shot_id']}.json", receipt)
    return receipt


def image_batch_provider(path, shots):
    """Generate all missing episode frames in one persistent ChatGPT chat."""
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool
    from openjarvis.one_agents.planexium_adapters import LaoDraft
    from openjarvis.one_agents.origin_to_ovation_faceless import enforce_prompt
    config = read(ROOT / "runtime-config.json")
    manifest = read(path / "mission.json")
    browser = manifest["browser"]
    if Path(browser["profile_dir"]).resolve() != (ROOT / "chrome-profile").resolve():
        raise ValueError("CHANDAN browser ownership mismatch")
    if not browser.get("chat_url", "").startswith("https://chatgpt.com/c/"):
        raise ValueError("Episode must have a recorded persistent conversation")
    for shot in shots:
        if not Path(shot["image"]).resolve().is_relative_to(path.resolve()):
            raise ValueError("Image escapes mission")
    missing = [shot for shot in shots if not (Path(shot["image"]).is_file()
               and Path(shot["image"]).stat().st_size > 10000)]
    if not missing:
        return {"status": "reused", "count": len(shots)}
    output_root = Path(missing[0]["image"]).parent
    batch_plan = path / "runtime" / "chatgpt-image-batch-plan.json"
    # A small number of biography shots can be refused repeatedly when a prompt
    # combines a named public figure, multiple ages, awards, or a close portrait.
    # Preserve the editorial beat while switching only those failed frames to
    # neutral evidence-led visual grammar.  Existing images are never touched.
    recovery_prompts = {}
    if manifest.get("subject_id") in {"lionel-messi", "cristiano-ronaldo"}:
        recovery_prompts.update({
            "P27": "Create one full-frame 16:9 photoreal cinematic CGI scene of a neutral football equipment timeline: four distinct pairs of period-appropriate boots and four footballs arranged chronologically on a dark studio bench, subtle changes in material and wear, warm-to-cool light progression, no people, faces, names, logos, trophies, text or branding.",
            "P41": "Create one full-frame 16:9 photoreal cinematic CGI biography scene of an anonymous mature adult footballer in true side profile at a generic evening training ground, plain deep maroon shirt, short dark hair and trimmed beard, medium-wide framing, natural posture, face not identifiable, no club cues, logos, text, awards or match recreation.",
            "P45": "Create one full-frame 16:9 photoreal cinematic CGI quiet-aftermath scene inside a generic South American stadium tunnel: a plain pale-blue-and-white training shirt folded on a wooden bench beside clean boots and a football, soft daylight from the pitch, no people, faces, names, logos, trophies, flags or readable text.",
            "P67": "Create one full-frame 16:9 photoreal cinematic CGI football-career timeline using three separate equipment stations for early, middle and mature career eras: period-appropriate boots, footballs and plain folded training shirts, neutral stadium backgrounds, natural chronological lighting progression, no people, portraits, names, logos, trophies, flags or readable text.",
            "P72": "Create one full-frame 16:9 photoreal cinematic CGI triptych suggesting three international-football eras through stadium architecture, match balls and plain pale-blue-and-white folded shirts, each panel visually distinct and chronological, no people, portraits, medals, trophies, names, logos, flags, ceremonies or readable text.",
            "P73": "Create one full-frame 16:9 photoreal cinematic CGI scene of an anonymous mature adult footballer in true side profile at a generic modern stadium, plain pale-blue training shirt, medium-wide framing, short dark hair and trimmed beard, natural athletic posture, face not identifiable, no awards, trophies, names, logos, flags, text or match recreation.",
            "P74": "Create one full-frame 16:9 photoreal cinematic CGI low-angle wide stadium portrait with one small anonymous adult footballer near the centre circle, plain pale-blue-and-white kit, face indistinct due to distance, realistic floodlights and restrained atmosphere, no celebration, trophies, names, logos, flags, scoreboards or readable text.",
        })
    if manifest.get("subject_id") == "serena-williams":
        recovery_prompts.update({
            "P27": "Create one full-frame 16:9 photoreal cinematic CGI tennis-equipment timeline: four period-appropriate rackets, tennis shoes and tennis balls arranged chronologically on a dark studio bench, warm-to-cool light progression, no people, faces, names, logos, trophies, text or branding.",
            "P41": "Create one full-frame 16:9 photoreal cinematic CGI biography scene of an anonymous mature adult woman tennis player in true side profile on a generic hard tennis court, plain deep-purple unbranded tennis kit, racket held naturally, correct tennis anatomy, no football pitch, goals, logos, text, awards or match recreation.",
            "P45": "Create one full-frame 16:9 photoreal cinematic CGI quiet-aftermath scene inside a generic tennis-stadium tunnel: a plain tennis dress folded on a wooden bench beside clean tennis shoes, a racket and tennis balls, soft daylight from a regulation tennis court, no people, faces, names, logos, trophies, flags or readable text.",
            "P67": "Create one full-frame 16:9 photoreal cinematic CGI tennis-career timeline using three separate equipment stations for early, middle and mature career eras: period-appropriate rackets, tennis shoes, balls and plain folded tennis kits, neutral tennis-court backgrounds, no football pitch, people, portraits, names, logos, trophies, flags or readable text.",
            "P72": "Create one full-frame 16:9 photoreal cinematic CGI triptych suggesting three international-tennis eras through hard, grass and clay court architecture, rackets, tennis balls and plain folded tennis kits, each panel visually distinct, no people, portraits, medals, trophies, names, logos, flags, ceremonies or readable text.",
            "P73": "Create one full-frame 16:9 photoreal cinematic CGI scene of an anonymous mature adult woman tennis player in true side profile at a generic modern hard court, plain dark tennis kit, racket held naturally, medium-wide framing, no football pitch, awards, trophies, names, logos, flags, text or match recreation.",
            "P74": "Create one full-frame 16:9 photoreal cinematic CGI low-angle wide tennis-stadium portrait with one small anonymous adult woman tennis player near the baseline of a regulation hard tennis court, plain dark kit and racket, realistic floodlights, no football pitch, goals, celebration, trophies, names, logos, flags, scoreboards or readable text.",
        })
    if manifest.get("subject_id") == "usain-bolt":
        recovery_prompts.update({
            "P32": "Create one full-frame 16:9 original cinematic CGI sprint illustration. True-side action view of the tall adult Black sprint protagonist from the attached reference running upright on a straight athletics track, plain black-and-yellow unbranded singlet, technically correct arm drive, hip extension, stride and foot contact, generic evening stadium, restrained motion blur, no named person, competitors, event recreation, logos, flags, bib text, scoreboards or watermarks.",
            "P52": "Create one full-frame 16:9 original cinematic CGI sprint illustration. True-side action view of the mature tall Black sprint protagonist from the attached reference running on a generic international track, plain black-and-yellow unbranded singlet, realistic stride cycle and anatomically correct hands, arms, legs and feet, neutral stadium lighting, no named person, exact race, competitors, finish gesture, logos, flags, bib text, scoreboards or watermarks.",
            "P73": "Create one full-frame 16:9 original cinematic CGI athletics illustration. Wide generic modern sprint stadium with the mature tall Black sprint protagonist from the attached reference standing in a front three-quarter medium view beside the track, plain black-and-yellow unbranded singlet, calm reflective expression and subtle layered lighting suggesting a long career, no named person, multiple ages, event recreation, logos, flags, bib text, scoreboards, trophies or watermarks.",
        })
    recovery_only = all(shot["shot_id"] in recovery_prompts for shot in missing)
    write(batch_plan, {"calls": [{
        "kind": "scene", "filename": Path(shot["image"]).name,
        # Recovery prompts are already deliberately subject-free.  Passing
        # them through enforce_prompt appended identity/face requirements that
        # contradicted equipment-only and anonymous fallback scenes and caused
        # fresh provider refusals.
        "prompt": (recovery_prompts[shot["shot_id"]] if shot["shot_id"] in recovery_prompts
                   else enforce_prompt(shot["prompt"])), "stall_timeout_ms": 240000,
        "max_attempts": 3,
    } for shot in missing]})
    provider = LaoDraft(LaoOrchestratorTool(), config.get("lao_folder_id"),
                        tuple(Path(p) for p in config["artifact_roots"]))
    steps = [
        {"action": "open_browser", "args": {
            "profile_dir": browser["profile_dir"], "cdp_url": browser["cdp_url"],
            "start_url": "https://chatgpt.com/"}},
        # A long conversation that has accumulated refusals can keep refusing
        # even completely neutral prompts.  Recovery stays in CHANDAN's same
        # dedicated persistent Chrome profile but starts a clean conversation.
        {"action": "navigate", "args": {
            "url": "https://chatgpt.com/" if recovery_only else browser["chat_url"]}},
        {"action": "wait_for_any_selector", "args": {
            "selectors": ["#prompt-textarea", "[contenteditable='true']", "textarea"],
            "timeout_ms": 60000}},
        {"action": "generate_chatgpt_image_batch", "args": {
            "plan_path": str(batch_plan),
            "reference_image_path": missing[0]["reference"],
            "reference_already_attached": True,
            "output_root": str(output_root),
            "reference_settle_seconds": 12,
            "retry_backoff_seconds": 60, "poll_ms": 3000,
            "as": "batch_result"}},
    ]
    # The receipt is named by the batch's prompts, not only its steps: the steps carry the plan's path, so a rewritten
    # plan (the 2026-10-22 faceless replan) used to look like the old Stopped job and could never start.
    plan_tag = digest(batch_plan)[:12]
    result, provider_job = provider.run(
        f"Origin to Ovation - {manifest['subject']} - {missing[0]['shot_id']}-{missing[-1]['shot_id']} single chat",
        steps, {}, path / "runtime" / "providers" / f"remaining-images-single-chat-{plan_tag}.json",
        timeout=21600)
    absent = [shot["shot_id"] for shot in missing if not (Path(shot["image"]).is_file()
              and Path(shot["image"]).stat().st_size > 10000)]
    if absent:
        raise RuntimeError(f"Single-chat batch left frames missing: {', '.join(absent)}")
    for shot in missing:
        output = Path(shot["image"])
        write(path / "runtime" / "images" / f"{shot['shot_id']}.json", {
            "status": "generated", "provider": "ChatGPT via LAO single-chat batch",
            "provider_job": provider_job, "sha256": digest(output),
            "editorial_review": "pending"})
    return {"status": "generated", "count": len(missing), "provider_job": provider_job,
            "chat_policy": "single_chat"}


def run_stage(job, *, enqueue):
    payload = json.loads(job["task"])
    path = mission_path(payload)
    verify_packet(payload, path, job["agent_id"])
    agent = job["agent_id"]
    master_dir = path / "production" / "master-v1"
    write(path / "runtime" / "active.json",
          {"agent": agent, "job_id": job["id"], "status": "running"})
    if agent == "helios":
        if payload.get("stage") == "reconcile":
            if payload.get("from_agent") != "echo" or not payload.get("evidence"):
                raise ValueError("HELIOS reconciliation requires ECHO evidence")
            upload = read(path / "runtime" / "upload-receipt.json")
            manifest = read(path / "mission.json")
            if (not upload.get("video_id") or not upload.get("visibility_verified")
                    or upload.get("master_sha256") != digest(master_dir / "master.mp4")
                    or manifest["browser"].get("observed_route_requires_owner_confirmation", True)
                    or upload.get("channel_id") != manifest["browser"].get("observed_studio_channel_id")):
                raise ValueError("Upload receipt does not verify this master and intended channel")
            sys.path.insert(0, str(ROOT))
            from agent_runtime.content_calendar import ContentCalendar
            calendar = ContentCalendar(ROOT)
            calendar.complete(path.name, master_dir / "master.mp4", path / "runtime" / "editorial-qc.json")
            calendar.export()
            return {"status": "reconciled", "mission_id": path.name,
                    "upload": upload}
        sys.path.insert(0, str(ROOT))
        from agent_runtime.content_calendar import ContentCalendar
        manifest = read(path / "mission.json")
        subject_id = manifest.get("subject_id") or ("sachin-tendulkar" if path.name == "sachin-first-video" else None)
        if not subject_id or not manifest.get("subject"):
            raise ValueError("Explicit canonical subject required")
        calendar = ContentCalendar(ROOT)
        manifest["content_calendar"] = calendar.reserve(path.name, subject_id, manifest["subject"])
        write(path / "mission.json", manifest)
        calendar.export()
        if manifest.get("production_phase") == "reference_first":
            return transfer(job, path, "chandan", "produce", enqueue,
                            [path / "research" / "commission-brief.json", path / "mission.json"])
        return transfer(job, path, "chandan", "produce", enqueue,
                        [master_dir / "shot-plan.json", path / "mission.json"])
    if agent == "chandan":
        manifest = read(path / "mission.json")
        from openjarvis.one_agents.chandan_continuation import PRODUCTION, REGENERATE, run_checkpoint, validate_pack
        if payload.get("checkpoint") in {PRODUCTION, REGENERATE}:
            checkpoint_result = run_checkpoint(path, job, payload)
            if checkpoint_result is not None:
                return checkpoint_result
            manifest = read(path / "mission.json")
        if manifest.get("reference_review_required") and manifest.get("production_phase") != "reference_first":
            if not (master_dir / "shot-plan.json").is_file():
                from openjarvis.one_agents.chandan_preproduction import generate
                generate(path)
            validate_pack(path)
        if payload.get("checkpoint") in {"identity_repair_v3", "identity_exact_request_p12"}:
            from openjarvis.one_agents.chandan_identity_repair import run
            return run(path, job)
        if manifest.get("production_phase") in {"reference_first", "reference_then_produce"}:
            from openjarvis.one_agents.chandan_reference import run_reference
            reference_result = run_reference(path, job)
            if manifest["production_phase"] == "reference_first":
                return reference_result
            manifest = read(path / "mission.json")
        plan = read(master_dir / "shot-plan.json")
        # Bind packaging, opening, factual beat loops, ending and post-publish learning before expensive generation.
        from openjarvis.one_agents.origin_to_ovation_story import write_contract as write_story_contract
        metadata_path = master_dir / "editorial-metadata.json"
        metadata = read(metadata_path) if metadata_path.is_file() else {}
        # Tiny fixtures/diagnostic renders are not publishable episodes. Keep them usable while
        # enforcing the contract on every real long-form plan.
        if len(plan) >= 10:
            story_contract = write_story_contract(master_dir, plan, metadata, manifest.get("subject") or path.name, write)
            if story_contract["validation"]["status"] != "passed":
                return {"_blocked": True, "status": "story_contract_required",
                        "blocked_reason": "; ".join(story_contract["validation"]["errors"])}
        if (path / "runtime" / "identity-quarantine.json").exists():
            release_path = path / "runtime" / "identity-release.json"
            if not release_path.is_file():
                return {"_blocked": True, "status": "identity_review_required",
                        "blocked_reason": "Quarantined frames require hash-bound visual identity, anatomy and period review"}
            release = read(release_path)
            for shot in plan:
                gate = release.get("shots", {}).get(shot["shot_id"], {})
                if (gate.get("image_sha256") != digest(Path(shot["image"]))
                        or gate.get("reference_sha256") != digest(Path(shot["reference"]))
                        or not all(gate.get(k) is True for k in ("identity", "anatomy", "historical_accuracy"))):
                    return {"_blocked": True, "status": "identity_review_required",
                            "blocked_reason": "Every quarantined scene needs a matching passed visual gate"}
        handedness_contract = path / "runtime" / "post-generation-review-required.json"
        if handedness_contract.is_file():
            release_path = path / "runtime" / "handedness-release.json"
            if not release_path.is_file():
                return {"_blocked": True, "status": "handedness_review_required",
                        "blocked_reason": "Throwing-action scenes require hash-bound handedness and anatomy review"}
            release = read(release_path)
            required_shots = release.get("required_shots", [])
            if release.get("status") != "passed" or not required_shots:
                return {"_blocked": True, "status": "handedness_review_required",
                        "blocked_reason": "Handedness release is incomplete"}
            plan_by_id = {shot["shot_id"]: shot for shot in plan}
            for shot_id in required_shots:
                shot = plan_by_id.get(shot_id)
                gate = release.get("shots", {}).get(shot_id, {})
                if (shot is None or gate.get("image_sha256") != digest(Path(shot["image"]))
                        or not all(gate.get(key) is True for key in
                                   ("right_handed", "anatomy", "no_mirror"))):
                    return {"_blocked": True, "status": "handedness_review_required",
                            "blocked_reason": f"Shot {shot_id} lacks a matching passed handedness gate"}
        write(path / "runtime" / "active.json", {
            "agent": agent, "job_id": job["id"], "status": "producing_images_single_chat",
            "processed": sum(Path(s["image"]).is_file() for s in plan), "total": len(plan)})
        with building_progress(manifest.get("subject") or path.name, plan) as phase:
            image_batch_provider(path, plan)
            from openjarvis.one_agents.origin_to_ovation_faceless import scene_qa
            write(path / "runtime" / "scene-visual-qa.json", {
                "status": "review_required", "shots": {
                    shot["shot_id"]: scene_qa(Path(shot["image"]), age=shot.get("age"), era=shot.get("era"))
                    for shot in plan if Path(shot["image"]).is_file()}})
            # Generator validates the paid chapter receipts and skips valid audio.
            phase("narration")
            if sum(len(str(shot.get("narration") or "").split()) for shot in plan) > 1650:
                from openjarvis.one_agents.chandan_preproduction import tighten_narration
                tighten_narration(path)
                plan = read(master_dir / "shot-plan.json")
            subprocess.run([sys.executable, str(master_dir / "generate_narration.py")], check=True)
            from openjarvis.one_agents.chandan_narration_alignment import ensure_alignments
            ensure_alignments(master_dir)
            from openjarvis.one_agents.chandan_render import render
            phase("rendering the master")
            rendered = render(master_dir)
            write(path / "runtime" / "render-result.json", rendered)
            phase("handing the master to ARES")
            return transfer(job, path, "ares", "seo", enqueue,
                            [master_dir / "master.mp4", master_dir / "narration.txt",
                             master_dir / "technical-qc.json"])
    if agent == "ares":
        if payload.get("stage") != "seo":
            raise ValueError("ARES needs production handoff")
        plan = read(master_dir / "timed-shot-plan.json")
        import re
        from openjarvis.one_agents.chandan_render import TEMPO
        chapter_titles = [
            "The boy behind the records", "A childhood in Bombay", "Learning the game",
            "The school partnership", "First-class beginnings", "India at sixteen",
            "The first Test century", "The first ODI century", "The 1996 World Cup",
            "Sharjah, 1998", "The 2003 World Cup", "A double century in Gwalior",
            "The 2011 World Cup", "A hundred international centuries", "The final Test and legacy",
        ]
        metadata_path = master_dir / "editorial-metadata.json"
        metadata = read(metadata_path) if metadata_path.is_file() else {}
        chapter_titles = metadata.get("chapter_titles", chapter_titles)
        chapters = []
        for shot in plan:
            number = int(shot["chapter"])
            if any(c["chapter"] == number for c in chapters):
                continue
            seconds = int(float(shot["start_seconds"]) / TEMPO)
            minutes, remainder = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            stamp = f"{hours:02}:{minutes:02}:{remainder:02}" if hours else f"{minutes:02}:{remainder:02}"
            chapters.append({"chapter": number, "start_seconds": seconds,
                             "timestamp": stamp, "title": chapter_titles[number-1]})
        ledger = path / "research" / "claim-ledger.md"
        source_records = []
        for line in ledger.read_text(encoding="utf-8-sig").splitlines():
            cells = line.split("|")
            if len(cells) < 5 or not re.fullmatch(r"C\d+", cells[1].strip()):
                continue
            claim = cells[1].strip()
            # C10 is not narrated; its old award-announcement wording needs correction.
            if claim == "C10" and path.name == "sachin-first-video":
                continue
            for label, url in re.findall(r"\[([^]]+)\]\((https?://[^\s)]+)\)", cells[3]):
                record = next((r for r in source_records if r["url"] == url), None)
                if record is None:
                    record = {"label": label, "url": url, "claim_ids": []}
                    source_records.append(record)
                if claim not in record["claim_ids"]:
                    record["claim_ids"].append(claim)
        if not source_records:
            raise ValueError("ARES requires the episode's linked claim sources")
        # 2026-10-23: the episode's own title, never an earlier episode's sentence or Sachin's default.
        from openjarvis.one_agents import origin_to_ovation_titles as titles
        subject = read(path / "mission.json").get("subject", "")
        title, refused = titles.pick(titles.candidates(metadata, path.name), subject,
                                     titles.earlier_titles(ROOT / "missions", path.name))
        if title is None:
            return {"_blocked": True, "status": "title_not_its_own",
                    "blocked_reason": "No title of this episode's own: give editorial-metadata.json a title "
                                      "(or title_options) that does not repeat an earlier episode",
                    "refused": refused}
        from openjarvis.one_agents import origin_to_ovation_seo as oto_seo
        package = oto_seo.build(
            subject=subject, title=title, metadata=metadata, chapters=chapters,
            sources=source_records, voice_name=metadata.get("voice_name", "George"))
        package.update({
            "category": "Sports", "language": "en-US",
            "source_ledger": str(ledger),
            "timeline": str(master_dir / "timed-shot-plan.json"),
            "timeline_tempo": TEMPO,
            "shot_count": len(plan),
            "master_sha256": digest(master_dir / "master.mp4")})
        write(path / "runtime" / "seo.json", package)
        return transfer(job, path, "echo", "thumbnail_upload", enqueue,
                        [master_dir / "master.mp4", path / "runtime" / "seo.json"])
    if agent == "echo":
        manifest = read(path / "mission.json")
        reference = read(master_dir / "shot-plan.json")[0]["reference"]
        metadata_path = master_dir / "editorial-metadata.json"
        metadata = read(metadata_path) if metadata_path.is_file() else {}
        if metadata.get("thumbnail_concepts"):
            # One story-led concept per angle, recognisable face required and no earlier-episode copy.
            from openjarvis.one_agents import origin_to_ovation_thumbnails as T
            from openjarvis.one_agents.origin_to_ovation_faceless import FACELESS_RULES
            earlier = T.earlier_thumbnails(ROOT / "missions", path.name)
            concepts = []
            for index, concept in enumerate(metadata["thumbnail_concepts"], start=1):
                concept = dict(concept)
                concept.setdefault("name", f"concept-{index:02d}")
                image = master_dir / "thumbnails" / f"{concept['name']}.png"
                image_provider(path, {"shot_id": concept["name"], "image": str(image), "reference": reference,
                                      "prompt": f"{concept['prompt']} {FACELESS_RULES} "
                                                f"Headline text exactly: {concept['headline']}."})
                reasons = T.resemblance(image, concept["headline"], earlier)
                concepts.append({**concept, "image": str(image), "rejected": reasons})
            picked = T.choose(concepts, metadata.get("thumbnail_choice"))
            write(path / "runtime" / "thumbnail-concepts.json",
                  {"concepts": concepts, "picked": picked and picked["name"],
                   "chairman_choice": metadata.get("thumbnail_choice")})
            if picked is None:
                return {"_blocked": True, "status": "thumbnail_concepts_rejected",
                        "blocked_reason": "Every thumbnail concept repeated an earlier episode or failed packaging review",
                        "concepts": concepts}
            shutil.copy2(picked["image"], master_dir / "thumbnail.png")
            if picked.get("title"):
                # The title written for this picture sells the same story; it replaces ARES's when it is its own.
                from openjarvis.one_agents import origin_to_ovation_titles as titles
                reasons = titles.repeats(picked["title"], manifest.get("subject", ""),
                                         titles.earlier_titles(ROOT / "missions", path.name))
                seo_path = path / "runtime" / "seo.json"
                if not reasons and seo_path.is_file():
                    write(seo_path, {**read(seo_path), "title": picked["title"]})
                write(path / "runtime" / "thumbnail-title.json",
                      {"concept": picked["name"], "title": picked["title"], "used": not reasons, "refused": reasons})
        image_provider(path, {
            "shot_id": "thumbnail", "image": str(master_dir / "thumbnail.png"),
            "reference": reference,
            "prompt": metadata.get("thumbnail_prompt", "Create a premium 16:9 cinematic CGI biography thumbnail. "
                      "Show a large recognisable emotional front or three-quarter face with historically accurate equipment. "
                      "Use the episode metadata for a 2-to-4-word conflict headline; no rear silhouette or invented identity.")})
        if manifest.get("upload_policy") == "package_only_until_later_explicit_user_instruction":
            return {"status": "package_ready_upload_not_authorized", "mission_id": path.name,
                    "master": str(master_dir / "master.mp4"), "seo": str(path / "runtime" / "seo.json")}

        # An upload is never inferred from a generated thumbnail.
        from openjarvis.one_agents.chandan_release import editorial_ready
        editorial_path = path / 'runtime' / 'editorial-qc.json'
        technical_path = master_dir / 'technical-qc.json'
        if not editorial_ready(read(technical_path) if technical_path.is_file() else {},
                               read(editorial_path) if editorial_path.is_file() else {},
                               digest(master_dir / 'master.mp4')):
            return {'_blocked': True, 'status': 'editorial_review_required',
                    'reason': 'Publication handoff requires a passed editorial review bound to this master',
                    'mission_id': path.name}
        receipt = path / "runtime" / "upload-receipt.json"
        if receipt.is_file():
            upload = read(receipt)
            if upload.get("master_sha256") == digest(master_dir / "master.mp4") and upload.get("video_id"):
                return transfer(job, path, "helios", "reconcile", enqueue, [receipt])
        return {"_blocked": True, "status": "awaiting_upload_binding",
                "reason": "Verify channel identity and editorial/canonical gates before upload",
                "mission_id": path.name, "master": str(master_dir / "master.mp4")}
    raise ValueError("Unknown channel stage agent")
