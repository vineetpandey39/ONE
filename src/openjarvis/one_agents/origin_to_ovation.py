"""Origin to Ovation's resumable, channel-scoped Floor 12 pipeline."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("E:/ONE-SUITE/data/youtube/origin_to_ovation")
BRAND = "origin_to_ovation"


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
    receipt = enqueue(target, json.dumps(packet), mode="execute",
                      dedupe_key=f"{BRAND}:{path.name}:{stage}:{revision}")
    write(path / "runtime" / f"handoff-{job['agent_id']}-{target}.json",
          {**packet, "to_agent": target, "job_id": receipt["id"]})
    return {"status": "handed_off", "next_job": receipt["id"], "to_agent": target,
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
        {"action": "navigate", "args": {"url": "https://chatgpt.com/"}},
        {"action": "click_first", "args": {
            "selectors": ["[data-testid='create-new-chat-button']", "a[href='/']"],
            "timeout_ms": 30000}},
        {"action": "wait_for_any_selector", "args": {
            "selectors": ["#prompt-textarea", "[contenteditable='true']", "textarea"],
            "timeout_ms": 60000, "as": "composer"}},
        {"action": "generate_and_download_chatgpt_image", "args": {
            "prompt": shot["prompt"],
            "reference_image_path": shot["reference"],
            "reference_settle_seconds": 12,
            "filename": output.name, "max_attempts": 2,
            "stall_timeout_ms": 240000, "as": "image_path"}},
    ]
    result, provider_job = provider.run(
        f"Origin to Ovation - Sachin First Video - {shot['shot_id']}", steps, {},
        path / "runtime" / "providers" / f"{shot['shot_id']}.json",
        timeout=1500)
    source = provider.artifact(result, provider_job, output.name)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)
    receipt = {"status": "generated", "provider": "ChatGPT via LAO",
               "provider_job": provider_job, "sha256": digest(output),
               "editorial_review": "pending"}
    write(path / "runtime" / "images" / f"{shot['shot_id']}.json", receipt)
    return receipt


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
        ContentCalendar(ROOT).reserve(path.name, "sachin-tendulkar", "Sachin Tendulkar")
        return transfer(job, path, "chandan", "produce", enqueue,
                        [master_dir / "shot-plan.json", path / "mission.json"])
    if agent == "chandan":
        plan = read(master_dir / "shot-plan.json")
        for index, shot in enumerate(plan):
            write(path / "runtime" / "active.json", {
                "agent": agent, "job_id": job["id"], "status": "producing_images",
                "shot": shot["shot_id"], "processed": index, "total": len(plan)})
            image_provider(path, shot)
        # Generator validates the paid chapter receipts and skips valid audio.
        subprocess.run([sys.executable, str(master_dir / "generate_narration.py")], check=True)
        from openjarvis.one_agents.chandan_render import render
        rendered = render(master_dir)
        write(path / "runtime" / "render-result.json", rendered)
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
            if claim == "C10":
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
        description = (
            "From a boy in Bombay to a World Cup winner: the journey of Sachin Tendulkar. "
            "Explore his early training, international debut, defining innings and legacy.\n\n"
            "Original CGI illustrations reconstruct the story; these are not archival recordings. "
            "Third-person narration by George via ElevenLabs. No athlete voice clone or invented dialogue.\n\n"
            "CHAPTERS\n" + "\n".join(c["timestamp"] + " " + c["title"] for c in chapters) +
            "\n\nSOURCES\n" + "\n".join(r["url"] for r in source_records) +
            "\n\nWhich sporting journey should we explore next? Subscribe to Origin to Ovation for more biographies.")
        if len(description) > 5000:
            raise ValueError("SEO description exceeds YouTube's 5000-character limit")
        package = {
            "title": "Sachin Tendulkar: The Boy Behind 100 International Centuries",
            "description": description,
            "category": "Sports", "language": "en-US",
            "tags": ["Sachin Tendulkar", "cricket biography", "Origin to Ovation",
                     "Sachin journey", "cricket history"],
            "chapters": chapters, "sources": source_records,
            "source_ledger": str(ledger),
            "timeline": str(master_dir / "timed-shot-plan.json"),
            "timeline_tempo": TEMPO,
            "shot_count": len(plan),
            "master_sha256": digest(master_dir / "master.mp4")}
        write(path / "runtime" / "seo.json", package)
        return transfer(job, path, "echo", "thumbnail_upload", enqueue,
                        [master_dir / "master.mp4", path / "runtime" / "seo.json"])
    if agent == "echo":
        reference = read(master_dir / "shot-plan.json")[0]["reference"]
        image_provider(path, {
            "shot_id": "thumbnail", "image": str(master_dir / "thumbnail.png"),
            "reference": reference,
            "prompt": "Create a premium 16:9 YouTube biography thumbnail in photoreal cinematic CGI. "
                      "Use attached Sachin age-stage reference for consistent stylized identity. "
                      "Adult Sachin determined closeup on right, childhood cricketer smaller on left, "
                      "warm Bombay practice ground transitioning to lit international stadium. "
                      "Strong simple visual contrast, no collage grid, anatomically sound. "
                      "Large readable headline only: THE BOY BEHIND THE LEGEND."})
        # An upload is never inferred from a generated thumbnail.
        receipt = path / "runtime" / "upload-receipt.json"
        if receipt.is_file():
            upload = read(receipt)
            if upload.get("master_sha256") == digest(master_dir / "master.mp4") and upload.get("video_id"):
                return transfer(job, path, "helios", "reconcile", enqueue, [receipt])
        return {"_blocked": True, "status": "awaiting_upload_binding",
                "reason": "Verify channel identity and editorial/canonical gates before upload",
                "mission_id": path.name, "master": str(master_dir / "master.mp4")}
    raise ValueError("Unknown channel stage agent")
