"""PLANEXIUM bindings to existing LAO actions; no installs or provider calls on import."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import zipfile
from contextlib import nullcontext
from contextlib import contextmanager
from pathlib import Path

from openjarvis.one_agents.youtube_production import resource_lease

BUILD_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _marked_json(text: str, begin: str, end: str):
    """Decode a marked JSON response, tolerating prose and markdown fences."""
    text = str(text or "")
    if begin in text:
        text = text.split(begin, 1)[1]
    if end in text:
        text = text.split(end, 1)[0]
    text = text.strip().strip("`").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text, re.I)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some providers add a short sentence inside the markers. Restrict
        # recovery to one complete object and let schema validation reject it.
        start = text.find("{")
        finish = text.rfind("}")
        if start < 0 or finish < start:
            raise
        return json.loads(text[start:finish + 1])


def stock_search(description: str) -> tuple[str, str, list[str]]:
    """Translate an authored visual brief into literal catalog search terms."""
    positive = re.split(r",|\bno\b", description, maxsplit=1, flags=re.I)[0]
    stop = {"generic", "empty", "a", "an", "the", "on", "of", "with", "before", "after", "in"}
    words = [w.casefold() for w in re.findall(r"[A-Za-z]+", positive) if w.casefold() not in stop]
    if not words:
        raise ValueError("Stock brief has no positive search subject")
    query = " ".join(words[:6])
    subject = next((w for w in ("sunrise", "astronaut", "rocket", "planet", "galaxy", "moon", "mars", "earth", "sky", "horizon") if w in words), words[0])
    negatives = []
    # Generic sky matches previously admitted a seagull/beach wildlife shot.
    # Astronomy establishing briefs must reject wildlife-led stock results.
    if subject in {"sky", "horizon", "sunrise"}:
        negatives.extend(["seagull", "bird", "wildlife", "animal"])
    for phrase in re.findall(r"\bno\s+([^,;.]+)", description, re.I):
        negatives.extend(w.casefold() for w in re.findall(r"[A-Za-z]+", phrase)
                         if w.casefold() in {"rocket", "spacecraft", "launch", "astronaut", "people", "person", "text"})
    return query, subject, sorted(set(negatives))


class LaoDraft:
    """Resumable one-off use of existing actions. Never creates a production package."""
    def __init__(self, tool, folder_id: str, artifact_roots: tuple[Path, ...]):
        self.tool, self.folder_id, self.artifact_roots = tool, folder_id, artifact_roots

    def run(self, name: str, steps: list[dict], inputs: dict, receipt: Path, *, timeout=3600, sleep=time.sleep) -> tuple[dict, str]:
        request_hash = fingerprint({"steps": steps, "inputs": inputs})
        prior = json.loads(receipt.read_text(encoding="utf-8")) if receipt.exists() else {}
        if prior and prior.get("request_hash") != request_hash:
            raise ValueError("Provider checkpoint differs; targeted repair required")
        job_id = prior.get("job_id")
        if not job_id:
            started = self.tool.execute(action="run_draft", draft_name=name, steps=steps,
                                        input_args=inputs, folder_id=self.folder_id,
                                        preserve_workflow=name.startswith("planexium-"))
            if not started.success:
                raise RuntimeError("LAO refused the channel-scoped draft; inspect its redacted operational log")
            payload = started.metadata or json.loads(started.content)
            job_id = (payload.get("job") or {}).get("id")
            if not job_id:
                raise RuntimeError("LAO returned no durable job receipt")
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(json.dumps({"job_id": job_id, "request_hash": request_hash}), encoding="utf-8")
        deadline = time.monotonic() + timeout
        last_status = None
        while time.monotonic() < deadline:
            probe = self.tool.execute(action="status", job_id=job_id, process_name="")
            if not probe.success:
                sleep(3)
                continue
            payload = probe.metadata or json.loads(probe.content)
            job = payload.get("job") or {}
            status = job.get("status")
            if status != last_status:
                callback = getattr(self, "on_wait" if status in {"Pending","Queued","Claimed"} else "on_progress", None)
                if callback:callback(f"{name}: provider {status}; job {str(job_id)[:8]}")
                last_status = status
            if status == "Successful":
                return job.get("output_result") or {}, job_id
            if status in {"Failed", "Stopped", "Cancelled", "Faulted", "Retried"}:
                from openjarvis.one_agents.chandan_control import ProviderTerminalError
                reason = str(job.get("error_message") or ("Stopped by operator/editorial control" if status in {"Stopped", "Cancelled"} else "Provider gave no error detail"))
                saved = {**prior, "job_id": job_id, "request_hash": request_hash,
                         "terminal_status": status, "provider_error": reason}
                receipt.write_text(json.dumps(saved, indent=2), encoding="utf-8")
                raise ProviderTerminalError(job_id, status, reason)
            sleep(3)
        raise TimeoutError("LAO draft remains in flight; retry resumes its saved job instead of starting another")

    def subject_rejected(self, receipt: Path) -> bool:
        """Only a confirmed pre-download rejection/unavailable preview may advance.

        A missing catalog preview is scoped to the selected Envato result, not
        the authored scene or the production.  Advancing to the next bounded
        candidate is therefore safe; download/authentication failures still
        stop the mission so the governor never creates a paid duplicate.
        """
        if not receipt.is_file():
            return False
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        response = self.tool.execute(action="status", job_id=saved["job_id"], process_name="")
        if not response.success:
            return False
        payload = response.metadata or json.loads(response.content)
        job = payload.get("job") or {}
        error = str(job.get("error_message") or "")
        return (job.get("status") == "Failed" and (
            ("Timed out waiting for selectors" in error and "idp-title" in error and ":has-text(" in error)
            or "Rejected asset: forbidden visual keyword(s)" in error
            or ("Rejected asset: visual subject " in error and " absent from " in error)
            or ("Rejected asset: destination phrase " in error and " absent from " in error)
            or "Rejected asset: preview does not confidently support selected-item metadata and subject" in error
            or "Asset preview unavailable" in error
            or ("started no download within 60s" in error
                and "account most likely already holds this asset" in error)))

    def transient_pre_download_failure(self, receipt: Path) -> bool:
        """One bounded retry for browser evidence capture that failed before any download action."""
        if not receipt.is_file():
            return False
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        error = str(saved.get("provider_error") or "")
        lowered = error.casefold()
        return (saved.get("terminal_status") == "Failed"
                and ("locator.screenshot: timeout" in lowered or "taking element screenshot" in lowered)
                and not any(term in lowered for term in ("download", "sign in", "authentication", "payment")))

    def artifact(self, outputs: dict, job_id: str, filename: str) -> Path:
        # Reuse the same artifact lookup as current Sonia production. Never
        # inspect unrelated browser profiles or credential files.
        from openjarvis.one_agents.ares_thumbnail import _find_artifact

        direct = outputs.get("image_path") or outputs.get("downloaded_asset") or outputs.get("capture_video")
        if isinstance(direct, str):
            p = Path(direct)
            if p.is_file() and any(p.resolve().is_relative_to(root.resolve()) for root in self.artifact_roots):
                return p
        found = _find_artifact(self.artifact_roots, job_id, filename)
        if not found:
            raise FileNotFoundError("Robot artifact is not available locally; retain the provider checkpoint")
        return Path(found)


def production_home() -> Path:
    # The shared worker deliberately overrides HOME for isolation. Windows'
    # operator profile remains USERPROFILE; persistent browsers live there.
    return Path(os.environ.get("USERPROFILE") or Path.home())


def provider_browser(context, lane="chatgpt", *, profile_root=None) -> dict:
    # Fixed per-channel identities match LAO's existing browser ownership registry.
    ports = {"chatgpt": 9340, "envato": 9341, "capture": 9342}
    urls = {"chatgpt": "https://chatgpt.com/", "envato": "https://app.envato.com/", "capture": "about:blank"}
    if context.channel.brand != "planexium" or lane not in ports:
        raise ValueError("Unknown channel browser identity")
    return {"profile_dir": ((Path(profile_root) if profile_root else production_home() / ".lao" / "browser-sessions") / f"planexium-{lane}").as_posix(),
            "cdp_url": f"http://127.0.0.1:{ports[lane]}", "start_url": urls[lane]}


def _login_steps(asset: str, context, profile_root=None) -> list[dict]:
    return [{"action": "open_browser", "args": provider_browser(context, profile_root=profile_root)},
            {"action": "navigate", "args": {"url": "https://chatgpt.com/"}},
            {"action": "wait_for_any_selector", "args": {
                "selectors": ["#prompt-textarea", "[contenteditable='true']", "textarea"],
                "timeout_ms": 60000, "as": "chatgpt_ready"}}]


class ChatGPTAdapter:
    def __init__(self, draft: LaoDraft, context, *, asset="chatgptLogin", queue=None, provider_lock=None, profile_root=None):
        self.draft, self.context, self.asset = draft, context, asset
        self.queue, self.provider_lock, self.profile_root = queue, provider_lock, profile_root

    def lease(self):
        return envato_lease(self.provider_lock, self.queue, self.context.mission_id) if self.provider_lock else nullcontext()

    def _marked_output(self, name, steps, receipt, key, begin, end):
        # A package without a usable output alias can finish successfully with
        # an empty output_result. Preserve its immutable receipt and repair it
        # once through the corrected package manifest.
        out, _ = self.draft.run(name, steps, {}, receipt)
        raw = out.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            repaired = receipt.with_name(f"{receipt.stem}-output-v2{receipt.suffix}")
            out, _ = self.draft.run(name, steps, {}, repaired)
            raw = out.get(key)
        return _marked_json(raw, begin, end)

    def write(self, prompt: str) -> dict:
        steps = _login_steps(self.asset, self.context, self.profile_root) + [{"action": "ask_chatgpt", "args": {
            "prompt": prompt, "expected_markers": ["BEGIN_PLANEXIUM_JSON", "END_PLANEXIUM_JSON"],
            "timeout_ms": 240000, "as": "science_script"}}]
        receipt = self.context.artifact("receipts/writer.json")
        with self.lease():
            return self._marked_output("planexium-science-script", steps, receipt, "science_script",
                                       "BEGIN_PLANEXIUM_JSON", "END_PLANEXIUM_JSON")

    def direct(self, science, voice):
        from openjarvis.one_agents.planexium_direction import motion_prompt
        steps = _login_steps(self.asset, self.context, self.profile_root) + [{"action": "ask_chatgpt", "args": {
            "prompt": motion_prompt(science, voice), "expected_markers": ["BEGIN_PLANEXIUM_MOTION_JSON", "END_PLANEXIUM_MOTION_JSON"],
            "timeout_ms": 360000, "as": "motion_copy"}}]
        out, _ = self.draft.run("planexium-science-script-motion", steps, {},
                               self.context.artifact("receipts/motion-director.json"))
        return _marked_json(out.get("motion_copy"), "BEGIN_PLANEXIUM_MOTION_JSON", "END_PLANEXIUM_MOTION_JSON")

    def editorial(self, science):
        prompt=('Act as a factual space documentary editor. Return JSON between BEGIN_PLANEXIUM_EDIT and END_PLANEXIUM_EDIT. '
            'Schema: {"music_query":"cinematic instrumental no vocals ...","stock_requests":[{"query":"2-5 catalog search words",'
            '"subject":"one literal word that must appear in a relevant asset title","title":"episode title","blocked_keywords":["cartoon","wildlife"]}]}. '
            'Give 16-24 diverse, topic-relevant Envato footage/animation briefs for an 8-12 minute film. Prefer concrete visual subjects: astronaut, rover, '
            'planet, observatory, mission hardware, actual environments. No abstract typography or text cards. '
            'Stock is illustrative, not evidence of the documented mission; do not rely on on-screen provider labels. '
            'Use visible, catalog-searchable nouns rather than inferred actions: laptop for email, treadmill for exercise, '
            'suit for spacesuit. The query must contain a second concrete context word; avoid generic person or abstract '
            'research as the only context. For Earth analog missions, use ordinary laboratory, crop and exercise imagery '
            'instead of astronaut costumes in cities or fantasy Mars colonies. Put costume, comedy, humor and urban '
            'in blocked_keywords for astronaut training briefs. Never imply that generic footage is the actual crew. '
            'Also include scene_assets: an object mapping EVERY 1-based scene number string to 0-3 relevant ZERO-based stock_requests indexes; use an empty list only when official evidence imagery is essential. Each stock index belongs to at most one scene. '
            'Also include scene_visuals mapping EVERY scene number to 1-3 DIFFERENT concise NASA archive image search queries, each directly relevant to that scene narration. NASA imagery is supporting evidence and must not dominate the cut. Avoid multiple near-identical views. '
            'Assign every stock index exactly once and do not reuse it across scenes: choose the most relevant scene for each clip. '
            'Also include packaging: {claim_ids:[supported claim IDs],focus_scene:1-based scene number,viewer_question:string,description_opening:two source-grounded sentences that explain the hook,titles:[three titles],concepts:[three objects with name,text,left_usp,composition,visual_direction]}. '
            'Choose the strongest unusual visual or scientific question in THIS episode, not a generic ISS/planet illustration. '
            'Titles and thumbnail text must complement rather than repeat each other; create specific curiosity that the narration actually resolves. '
            'Thumbnail text 1-4 words. Author three genuinely different subjects/compositions: phenomenon close-up, contextual relationship, and a distinct explanation question. '
            'Every thumbnail text must contain at least one literal non-generic word from a proposed title or the focus scene screen_text, so title and image promise visibly match. '
            'Color, crop and styling alone are not different concepts. Do not invent events, findings, scale, urgency or audience CTR predictions. '
            'Order concepts and titles by editorial preference, provisional until audience testing. '
            'Music must suit the subject and have no vocals. Use the script, not unrelated space filler. SCRIPT: '+json.dumps(science))
        feedback=self.context.media_root.parent/'packaging-feedback.json'
        if feedback.exists():
            data=json.loads(feedback.read_text(encoding='utf-8'))
            prompt+='\nUSER-REPORTED PACKAGING OBSERVATIONS (small samples are not causal evidence): '+json.dumps(data)
        steps=_login_steps(self.asset,self.context,self.profile_root)+[{'action':'ask_chatgpt','args':{
            'prompt':prompt,'expected_markers':['BEGIN_PLANEXIUM_EDIT','END_PLANEXIUM_EDIT'],
            'timeout_ms':360000,'as':'editorial_plan'}}]
        out,_=self.draft.run('planexium-science-script-editorial',steps,{},self.context.artifact('receipts/editorial.json'))
        result=_marked_json(out.get('editorial_plan'), 'BEGIN_PLANEXIUM_EDIT', 'END_PLANEXIUM_EDIT')
        if not isinstance(result.get('music_query'),str) or not 16<=len(result.get('stock_requests',[]))<=24:
            raise ValueError('Editorial plan needs music and 16-24 relevant footage briefs')
        for request in result['stock_requests']:
            if not all(isinstance(request.get(k),str) and request[k].strip() for k in ['query','subject']):
                raise ValueError('Editorial footage brief missing query/subject')
            request['title']=science['video_title']
            request['blocked_keywords']=list(set(request.get('blocked_keywords',[])+['seagull','wildlife','cartoon']))
        result['revision']='motion-rich-v3'
        result['visual_policy']={'target_minutes':[8,12],'stock_clips':[16,24],
            'stock_per_scene':3,'archive_shot_ratio_max':0.40,'envato_failure_threshold':10,
            'fallback_providers':['Pexels','Pixabay']}
        mapping=result.get('scene_assets',{})
        if set(mapping)!={str(i) for i in range(1,len(science['scenes'])+1)} or any(
            not isinstance(v,list) or len(v)>3 or any(type(i) is not int or not 0<=i<len(result['stock_requests']) for i in v)
            for v in mapping.values()):raise ValueError('Editorial plan lacks a valid per-scene footage mapping')
        assigned=[i for indexes in mapping.values() for i in indexes]
        if len(assigned)!=len(set(assigned)):
            raise ValueError('An illustrative stock clip cannot be assigned to multiple scenes')
        if set(assigned)!=set(range(len(result['stock_requests']))):
            raise ValueError('Every requested stock clip must be assigned to exactly one scene')
        from openjarvis.one_agents.planexium_packaging import repair_thumbnail_hooks, validate_packaging
        result['packaging'] = repair_thumbnail_hooks(result.get('packaging'), science)
        validate_packaging(result.get('packaging'),science)
        visuals=result.get('scene_visuals',{})
        if set(visuals)!=set(mapping) or any(not isinstance(v,list) or not 1<=len(v)<=3 or any(not isinstance(q,str) or not q.strip() for q in v) for v in visuals.values()):
            raise ValueError('Editorial plan requires distinct per-scene archive queries')
        return result

    def image(self, *, prompt: str, output: Path, brand: str) -> dict:
        if brand != "planexium":
            raise ValueError("Wrong channel for this image adapter")
        filename = f"planexium-{self.context.mission_id}-{output.parent.name}.png"
        legacy_receipt = output.parent / "provider.json"
        legacy = json.loads(legacy_receipt.read_text(encoding="utf-8")) if legacy_receipt.exists() else {}
        # A request hash is part of the durable LAO checkpoint. Resume an old
        # in-flight/successful request exactly as authored; only the confirmed
        # pre-artifact timeout repaired here may advance to a versioned request.
        legacy_error = str(legacy.get("provider_error") or "")
        repairable_timeout = (legacy.get("terminal_status") == "Failed"
                              and "Timed out waiting for generated image src" in legacy_error)
        legacy_request = bool(legacy) and not repairable_timeout
        marker = f"PLANEXIUM-{self.context.mission_id}-{output.parent.name}"
        image_args = {"prompt": prompt, "filename": filename, "max_attempts": 2, "as": "image_path"}
        receipt = legacy_receipt
        if not legacy_request:
            image_args.update({
                "prompt": f"{prompt}\nRequest marker: {marker}",
                "request_marker": marker,
                "strict_fresh_turn": True,
                "stall_timeout_ms": 300000,
            })
            receipt = output.parent / "provider-v2.json"
        steps = _login_steps(self.asset, self.context, self.profile_root) + [
            {"action": "generate_and_download_chatgpt_image", "args": image_args}]
        with self.lease():
            out, job = self.draft.run("planexium-original-thumbnail", steps, {}, receipt)
        source = self.draft.artifact(out, job, filename)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output)
        return {"ok": True, "path": str(output), "job_id": job, "portrait_used": False}


def busy_floor(queue: Path) -> bool:
    if not queue.is_file():
        raise FileNotFoundError("Shared queue unavailable; browser occupancy cannot be established")
    with sqlite3.connect(queue.as_uri() + "?mode=ro", uri=True) as db:
        return bool(db.execute(
            "SELECT 1 FROM jobs WHERE agent_id IN ('yatra','vista','fabula','lyra','muse','kairos','herald','scribe') "
            "AND mode != 'watch' AND status IN ('running','queued') LIMIT 1").fetchone())


@contextmanager
def envato_lease(path: Path, queue: Path, mission: str, *, wait_seconds=0, on_wait=None):
    """Honor the existing VISTA/YATRA provider lock format, without stale deletion."""
    owner = f"PLANEXIUM {os.getpid()} {mission}"
    deadline = time.monotonic() + wait_seconds
    while True:
        resumed = path.exists() and path.read_text(encoding="utf-8") == owner
        if resumed:break
        if busy_floor(queue) or path.exists():
            if not wait_seconds:
                raise RuntimeError("Shared production busy or provider leased; defer Envato")
            if time.monotonic() >= deadline:
                raise TimeoutError("Shared provider wait exceeded its bound; checkpoints retained")
            if on_wait:on_wait("Waiting for shared footage provider; other agents retain ownership")
            time.sleep(3)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as handle:handle.write(owner)
            break
        except FileExistsError:
            if not wait_seconds:raise RuntimeError("Envato provider is leased; defer this stage") from None
    release = True
    try:
        yield
    except TimeoutError:
        # The remote robot can still be acting. Preserve ownership until the
        # saved job is resumed and reaches a terminal status; never overlap it.
        release = False
        raise
    finally:
        if release and path.exists() and path.read_text(encoding="utf-8") == owner:
            path.unlink()


def probe_stock(path: Path) -> dict:
    import subprocess
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True, timeout=60)
    data = json.loads(result.stdout)
    video = next((s for s in data["streams"] if s.get("codec_type") == "video"), {})
    seconds = float(data.get("format", {}).get("duration") or 0)
    if (video.get("width"), video.get("height")) != (1920, 1080) or seconds <= 0:
        raise ValueError("Acquired stock must be measured 1920x1080 with positive duration")
    return {"seconds": seconds, "width": 1920, "height": 1080}


def materialize_stock_download(path: Path) -> Path:
    """Extract Envato's single-video ZIP while preserving the source archive."""
    path = Path(path)
    if not path.is_file():
        return path
    with path.open("rb") as handle:
        signature = handle.read(4)
    if signature != b"PK\x03\x04":
        return path
    with zipfile.ZipFile(path) as archive:
        members = []
        for info in archive.infolist():
            member = Path(info.filename.replace("\\", "/"))
            if info.is_dir():
                continue
            if member.is_absolute() or ".." in member.parts:
                raise ValueError("Envato archive contains an unsafe member path")
            if member.suffix.casefold() in {".mp4", ".mov", ".m4v"}:
                members.append(info)
        if len(members) != 1:
            raise ValueError("Envato archive must contain exactly one video rendition")
        member = members[0]
        if member.file_size <= 0 or member.file_size > 4 * 1024 * 1024 * 1024:
            raise ValueError("Envato archive video size is invalid")
        temporary = path.with_name(f".{path.name}.extracting")
        with archive.open(member) as source, temporary.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
    archive_path = path.with_suffix(path.suffix + ".download.zip")
    if not archive_path.exists():
        path.replace(archive_path)
    else:
        path.unlink()
    temporary.replace(path)
    return path


def stock_context(request):
    """Bind two independent facts from the authored science stock brief.

    The installed evidence action names its first field 'destination', but
    checks selected metadata for two independent terms. Science supplies a
    visual context, never invents a geographical destination.
    """
    subject = str(request["subject"]).casefold()
    stop = {"a","an","the","of","in","with","and","generic","cinematic","close","up",
            "dramatic","beautiful","footage","video"}
    context = next((w for w in re.findall(r"[A-Za-z]+", request["query"])
                    if w.casefold() != subject and w.casefold() not in stop), None)
    if not context:
        raise ValueError("Science stock brief needs independent context and subject evidence")
    return context


def concrete_stock_brief(request):
    """Turn known inferred-action searches into visible, non-costume subjects."""
    request = {**request, "blocked_keywords": list(request.get("blocked_keywords", []))}
    subject = request["subject"].casefold().strip()
    query = request["query"].casefold()
    if subject in {"email", "emailing"}:
        request.update(query="hands typing laptop", subject="laptop")
    elif subject == "exercise" and "astronaut" in query:
        request.update(query="woman treadmill exercise", subject="treadmill")
        request["blocked_keywords"] += ["astronaut", "spacesuit", "costume", "comedy", "humor"]
    elif subject == "spacesuit":
        request.update(query="astronaut suit display", subject="suit")
    elif subject == "airfoil":
        # Envato commonly describes a visible airfoil as an aircraft wing.
        # Keep the aerodynamic context, but require the concrete object that
        # can actually be verified in metadata and preview frames.
        request.update(query="aircraft wing aerodynamics", subject="wing")
    elif subject == "cupola":
        # Catalog stemming turns "cupola" into cupcake results, while valid
        # ISS-window footage is normally titled as a space-station window or
        # Earth view.  Require those visible objects, not an astronaut who is
        # optional to the authored establishing shot.
        request.update(query="space station window earth", subject="window")
        request["blocked_keywords"] += ["cupcake", "cake", "frosting", "bakery"]
    elif subject == "laboratory" and "engineer" in query:
        # A laboratory is background context; the authored shot asks for the
        # person doing the aerospace work.  Requiring "engineer" rejects an
        # empty generic lab without demanding that every valid title say lab.
        request.update(query="aerospace engineer laboratory", subject="engineer")
    elif subject == "computer" and "simulation" in query:
        # The authored action is visible digital modelling, not any generic
        # computer.  Envato often describes the honest shot as a 3D/digital
        # rendering rather than using the abstract word "simulation".  Bind
        # both independently visible facts so an office laptop alone cannot
        # pass, while an engineer inspecting a digital rendering can.
        request.update(query="digital rendering computer", subject="rendering")
    if "astronaut" in request["query"].casefold():
        request["blocked_keywords"] += ["costume", "comedy", "humor", "urban", "city", "sneakers"]
    return request


def verified_stock_subject(title, subject, outputs):
    if subject.casefold() in title.casefold():
        return True
    proof = outputs.get("asset_subject_verified") or {}
    verdict = proof.get("preview_verdict") or {}
    return bool(proof.get("policy") == "selected-metadata-preview-fast-v2"
        and proof.get("accepted") is True and proof.get("title") == title
        and str(proof.get("subject", "")).casefold() == subject.casefold()
        and subject.casefold() in str(proof.get("description", "")).casefold()
        and len(proof.get("preview_sha256", [])) >= 2
        and verdict.get("subject_match") is True
        and all(verdict.get(k) is False for k in ("unusable", "uncertain", "contradiction")))


class EnvatoAdapter:
    def __init__(self, draft: LaoDraft, workflow: Path, context, queue: Path, provider_lock: Path, *, wait_seconds=0,
                 profile_root=None, failure_limit=10, free_stock=None):
        self.draft, self.workflow, self.context = draft, workflow, context
        self.queue, self.provider_lock, self.wait_seconds, self.profile_root = queue, provider_lock, wait_seconds, profile_root
        self.failure_limit, self.free_stock = int(failure_limit), free_stock or self._yatra_free_stock

    def _yatra_free_stock(self, request, index, output_root):
        """Reuse YATRA's vetted Pexels/Pixabay client after an Envato brief is genuinely exhausted."""
        import importlib.util
        helper_root = self.workflow.parent
        helper_path = helper_root / "stuck_shot.py"
        acquire_path = helper_root / "acquire_scenes.py"
        if not helper_path.is_file() or not acquire_path.is_file():
            raise RuntimeError("YATRA free-stock fallback is unavailable")
        if str(helper_root) not in sys.path:
            sys.path.insert(0, str(helper_root))
        spec = importlib.util.spec_from_file_location("stuck_shot", helper_path)
        helper = importlib.util.module_from_spec(spec); sys.modules["stuck_shot"] = helper; spec.loader.exec_module(helper)
        spec = importlib.util.spec_from_file_location("planexium_yatra_acquire", acquire_path)
        acquire = importlib.util.module_from_spec(spec); spec.loader.exec_module(acquire)
        folder = Path(output_root) / f"scene-{index}"
        folder.mkdir(parents=True, exist_ok=True)
        blocked = ["fantasy", "surreal", "alien", *request.get("blocked_keywords", [])]
        for name, key_fn, asset_name, search, prefix, download in (
            ("Pexels", helper.pexels_key, helper.PEXELS_ASSET, helper.pexels_search,
             helper.PEXELS_PREFIX, helper.pexels_download),
            ("Pixabay", helper.pixabay_key, helper.PIXABAY_ASSET, helper.pixabay_search,
             helper.PIXABAY_PREFIX, helper.pixabay_download)):
            key = key_fn(acquire.resolve_vault_asset)
            if not key:
                continue
            for query in dict.fromkeys((request["query"], request["subject"])):
                try:
                    hits = search(key, query)
                except Exception:
                    continue
                picked = helper.pixabay_pick(hits, request["subject"], helper.used_ids(output_root, prefix), blocked, 3.0)
                if not picked:
                    continue
                hit, subject_named = picked
                path = download(hit, folder, output_root, query, subject_named)
                measured = probe_stock(path)
                return {"provider": name, "path": str(path), "job_id": None, "query": request["query"],
                    "title": str(hit.get("tags") or request["subject"]), "catalog_query": query,
                    "illustrative": True, "rights_review_required": True, "subject_evidence": subject_named,
                    "source_url": str(hit.get("pageURL") or ""), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    **measured}
        raise RuntimeError(f"Envato failed {self.failure_limit} quality-reviewed candidates and no usable Pexels/Pixabay fallback was available")

    def accepted(self, index, request):
        saved = self.context.artifact(f"acquired/stock-{index}.json")
        signature = fingerprint(request)
        if saved.is_file():
            value = json.loads(saved.read_text(encoding="utf-8"))
            if value["request_hash"] != signature:
                raise ValueError("Accepted stock brief changed; targeted repair required")
            row = value["asset"]
            path = Path(row["path"]).resolve()
            if (not path.is_relative_to(self.context.root.resolve()) or not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]):
                raise ValueError("Accepted stock checkpoint changed")
            return row, value["candidate"]
        # Migrate only a real successful download from this mission's old
        # receipts. Verify job inputs, title, file identity and measured format.
        if not hasattr(self.draft, "tool"):
            return None
        for receipt in sorted(self.context.artifact("receipts").glob(f"envato-{index}*.json")):
            old = json.loads(receipt.read_text(encoding="utf-8"))
            if not old.get("job_id"):continue
            response = self.draft.tool.execute(action="status", job_id=old["job_id"], process_name="")
            if not response.success:continue
            payload = response.metadata or json.loads(response.content)
            job = payload.get("job") or {}; args = job.get("input_args") or {}; out = job.get("output_result") or {}
            title = str(out.get("selected_asset_title") or "")
            blocked = ["fantasy", "surreal", "alien", *request.get("blocked_keywords", [])]
            if (job.get("status") != "Successful" or args.get("envatoQuery") != request["query"]
                    or str(args.get("sceneId")) != str(index) or request["subject"].casefold() not in title.casefold()
                    or any(word.casefold() in title.casefold() for word in blocked)):
                continue
            path = self.context.root / f"scene-{index}" / f"planexium-scene-{index}.mp4"
            if not path.is_file():continue
            row = {"provider": "Envato", "path": str(path), "job_id": old["job_id"], "query": request["query"],
                "title": title, "illustrative": True, "rights_review_required": True,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **probe_stock(path)}
            candidate = int(args["resultIndex"])
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text(json.dumps({"request_hash": signature, "asset": row, "candidate": candidate}, indent=2), encoding="utf-8")
            return row, candidate
        return None

    def __call__(self, *, brand, mission_id, output_root, requests) -> dict:
        import yaml

        if brand != "planexium" or Path(output_root) != self.context.root:
            raise ValueError("Envato channel output identity mismatch")
        workflow = yaml.safe_load(self.workflow.read_text(encoding="utf-8"))
        # Use the latest accepted selectors/actions, not a stale copied workflow.
        steps = workflow["steps"]
        requires_context = any(s.get("action") == "assert_destination_subject" for s in steps)
        for step in steps:
            if step.get("action") == "open_browser":
                step.setdefault("args", {}).update(provider_browser(self.context, "envato", profile_root=self.profile_root))
            if step.get("action") == "download_file":
                step["args"]["dest_dir"] = "{{input.outputRoot}}/scene-{{input.sceneId}}"
                step["args"]["filename"] = "planexium-scene-{{input.sceneId}}.mp4"
                step["args"]["keep_original_name"] = False
        receipts, hashes, query_positions, titles = [], set(), {}, []
        with envato_lease(self.provider_lock, self.queue, mission_id, wait_seconds=self.wait_seconds, on_wait=getattr(self.draft,"on_wait",None)):
            for index, original_request in enumerate(requests, 1):
                request = original_request
                query = str(request["query"])
                accepted = self.accepted(index, request)
                if accepted:
                    row, candidate = accepted
                    if row["sha256"] in hashes:raise ValueError("Accepted stock would duplicate an existing source")
                    hashes.add(row["sha256"]);titles.append(row["title"]);receipts.append(row)
                    query_positions[query] = max(query_positions.get(query, 0), candidate)
                    continue
                request = concrete_stock_brief(original_request)
                query = request["query"]
                first_candidate = query_positions.get(query, 0) + 1
                from urllib.parse import quote_plus

                inputs = {"sceneId": str(index), "envatoQuery": query, "envatoQueryUrl": quote_plus(query),
                          "fallbackQuery": query, "videoTitle": request["title"], "downloadFormat": "1080P",
                          "assetFolder": mission_id, "resultIndex": str(first_candidate),
                          "requiredTitleKeyword": stock_context(request) if requires_context else request["subject"],
                          "alternateTitleKeyword": request["subject"], "locationMatch": False, "subjectMatch": True,
                          "regionalContext": False, "regionalContextLabel": "", "orientation": "Horizontal",
                          "requiredResolution": "1920 x 1080", "previouslyDownloadedTitles": list(titles),
                          "blockedTitleKeywords": ["fantasy", "surreal", "alien", *request.get("blocked_keywords", [])], "enablePaidDownload": True,
                          "outputRoot": str(output_root)}
                import copy
                asset_steps = copy.deepcopy(steps)
                for step in asset_steps:
                    # Envato has used both /search/stock-video/... and
                    # /stock-video/... result routes.  The shared workflow
                    # keeps its conservative selectors; PLANEXIUM adds the
                    # current generic route in-memory so a catalogue redesign
                    # cannot leave a daily run parked on an obsolete selector.
                    if (step.get("action") == "wait_for_any_selector"
                            and step.get("args", {}).get("as") == "envato_results_ready"):
                        selectors = step["args"].setdefault("selectors", [])
                        current = "a[href*='/stock-video/']"
                        if current not in selectors:
                            selectors.append(current)
                    if step.get("action") == "assert_text_absent":
                        key = str(step.get("args", {}).get("forbidden", ""))
                        if key == "{{input.blockedTitleKeywords}}":step["args"]["forbidden"] = inputs["blockedTitleKeywords"]
                        if key == "{{input.previouslyDownloadedTitles}}":step["args"]["forbidden"] = inputs["previouslyDownloadedTitles"]
                fallback_row = None
                for candidate in range(first_candidate, first_candidate + self.failure_limit):
                    fallback = candidate >= first_candidate + max(1, self.failure_limit // 2)
                    catalog_query = str(request["subject"]) if fallback else query
                    inputs["envatoQuery"] = catalog_query
                    inputs["envatoQueryUrl"] = quote_plus(catalog_query)
                    inputs["resultIndex"] = str(candidate - first_candidate - max(1, self.failure_limit // 2) + 1 if fallback else candidate)
                    # v5 binds the receipt namespace to the concrete-subject
                    # policy above.  A v3 failed job was launched with a
                    # materially different brief; trying to attach it to the
                    # repaired request correctly trips LaoDraft's hash gate,
                    # but must not strand the mission forever.  Accepted
                    # downloads remain in acquired/ and are still reused.
                    receipt = self.context.artifact(f"receipts/envato-v5-{index}.json" if candidate == first_candidate
                        else f"receipts/envato-v5-{index}-candidate-{candidate}.json")
                    try:
                        out, job = self.draft.run("planexium-envato", asset_steps, inputs, receipt, timeout=10800)
                        query_positions[query] = candidate
                        break
                    except RuntimeError:
                        if getattr(self.draft, "transient_pre_download_failure", lambda _receipt: False)(receipt):
                            retry_receipt = self.context.artifact(
                                f"receipts/envato-v5-{index}-candidate-{candidate}-browser-retry.json")
                            out, job = self.draft.run("planexium-envato", asset_steps, inputs, retry_receipt, timeout=10800)
                            query_positions[query] = candidate
                            break
                        if not self.draft.subject_rejected(receipt):
                            raise
                        if candidate == first_candidate + self.failure_limit - 1:
                            fallback_row = self.free_stock(request, index, Path(output_root))
                            break
                        # The failed candidate ended before any paid/download step.
                        # Keep its receipt; the next distinct result gets its own job.

                if fallback_row is not None:
                    if fallback_row["sha256"] in hashes:
                        raise ValueError("Free-stock fallback returned a duplicate source")
                    hashes.add(fallback_row["sha256"]); titles.append(fallback_row["title"])
                    saved = self.context.artifact(f"acquired/stock-{index}.json")
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    saved.write_text(json.dumps({"request_hash": fingerprint(original_request), "asset": fallback_row,
                        "effective_brief": request, "candidate": self.failure_limit, "fallback_after_envato_failures": self.failure_limit}, indent=2), encoding="utf-8")
                    receipts.append(fallback_row)
                    continue
                path = Path(output_root) / f"scene-{index}" / f"planexium-scene-{index}.mp4"
                if not path.is_file():
                    source = self.draft.artifact(out, job, path.name)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, path)
                path = materialize_stock_download(path)
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
                if sha in hashes:
                    raise ValueError("Envato returned a duplicate source; preserve receipts for targeted repair")
                hashes.add(sha)
                title = str(out.get("selected_asset_title") or "").strip()
                if not title or not verified_stock_subject(title, request["subject"], out):
                    raise ValueError("Provider success lacks a verified selected-asset subject title")
                if any(str(word).casefold() in title.casefold() for word in inputs["blockedTitleKeywords"]):
                    raise ValueError("Selected asset contains a forbidden visual keyword")
                titles.append(title)
                row = {"provider": "Envato", "path": str(path), "job_id": job, "query": query,
                       "title": str(out.get("selected_asset_title") or ""), "catalog_query": catalog_query, "illustrative": True,
                       "rights_review_required": True, "subject_evidence": out.get("asset_subject_verified"),
                       "sha256": sha, **probe_stock(path)}
                saved = self.context.artifact(f"acquired/stock-{index}.json")
                saved.parent.mkdir(parents=True, exist_ok=True)
                saved.write_text(json.dumps({"request_hash": fingerprint(original_request), "asset": row,
                                             "effective_brief": request,
                                             "candidate": candidate}, indent=2), encoding="utf-8")
                receipts.append(row)
        return {"ok": True, "assets": receipts}


class OBSAdapter:
    def __init__(self, draft: LaoDraft, workflow: Path, context, queue: Path, leases: Path, *, prepare_video=False, wait_seconds=0, profile_root=None):
        self.draft, self.workflow, self.context = draft, workflow, context
        self.queue, self.leases, self.prepare_video, self.wait_seconds, self.profile_root = queue, leases, prepare_video, wait_seconds, profile_root

    def ensure_source(self):
        """Idempotent channel-owned scene setup through the installed OBS API helper."""
        obs = self.connect_obs()
        try:
            self.setup_owned_scene(obs)
        finally:
            obs.close()

    def connect_obs(self):
        import importlib.util
        import subprocess

        path = next((root / "obs_ws.py" for root in self.draft.artifact_roots if (root / "obs_ws.py").is_file()), None)
        if path is None:
            raise RuntimeError("Installed OBS websocket helper is unavailable")
        spec = importlib.util.spec_from_file_location("planexium_obs_transport", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            obs = module.connect_default()
        except OSError:
            executable = Path("C:/Program Files/obs-studio/bin/64bit/obs64.exe")
            if not executable.is_file():
                raise RuntimeError("Existing OBS installation is unavailable")
            subprocess.Popen([str(executable), "--disable-shutdown-check", "--minimize-to-tray"],
                cwd=executable.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 90
            while True:
                try:
                    obs = module.connect_default()
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("OBS did not become available")
                    time.sleep(3)
        return obs

    @staticmethod
    def setup_owned_scene(obs):
        scene, source = "PLANEXIUM Capture", "PLANEXIUM Capture Chrome"
        if obs.request("GetRecordStatus").get("outputActive"):
            raise RuntimeError("OBS is recording; defer setup instead of changing its program")
        scenes = obs.request("GetSceneList")["scenes"]
        if not any(row["sceneName"] == scene for row in scenes):
            obs.request("CreateScene", {"sceneName": scene})
        inputs = obs.request("GetInputList")["inputs"]
        if not any(row["inputName"] == source for row in inputs):
            obs.request("CreateInput", {"sceneName": scene, "inputName": source,
                "inputKind": "window_capture", "inputSettings": {"capture_method": 2, "client_area": False},
                "sceneItemEnabled": True})
        else:
            items = obs.request("GetSceneItemList", {"sceneName": scene})["sceneItems"]
            if not any(row["sourceName"] == source for row in items):
                raise RuntimeError("PLANEXIUM input exists outside its owned scene; inspect before modifying")

    def __call__(self, *, brand, mission_id, output_root, scenes) -> dict:
        import yaml

        if brand != "planexium":raise RuntimeError("Wrong channel for OBS")
        deadline=time.monotonic()+self.wait_seconds
        while busy_floor(self.queue):
            if not self.wait_seconds:raise RuntimeError("Shared production busy; defer OBS")
            if time.monotonic()>=deadline:raise TimeoutError("Shared OBS wait exceeded its bound")
            if getattr(self.draft,"on_wait",None):self.draft.on_wait("Waiting for shared OBS capture; other agents retain ownership")
            time.sleep(3)
        workflow = yaml.safe_load(self.workflow.read_text(encoding="utf-8"))
        steps = workflow["steps"]
        source_name = "PLANEXIUM Capture Chrome"
        marker = f"PLANEXIUM-CAPTURE-{mission_id}"
        for step in steps:
            args = step.get("args", {})
            if step.get("action") == "open_browser":
                args.update(provider_browser(self.context, "capture", profile_root=self.profile_root))
            if step.get("action") == "obs_bind_window":
                args["source"] = source_name
                args["scene"] = "PLANEXIUM Capture"
                args["window_marker"] = marker
            if step.get("action") == "navigate" and str(args.get("url", "")).startswith("data:"):
                args["url"] = f"data:text/html,<title>{marker}</title><body></body>"
            if step.get("action") == "obs_record_sequence":
                args["source"] = source_name
        results = []
        with resource_lease(self.leases, "obs"):
            for i, scene in enumerate(scenes, 1):
                video = None
                if self.prepare_video:
                    from openjarvis.one_agents.space_research import embedded_video
                    video = embedded_video(scene["url"])
                preparation = ([{"click": ".hds-video-container .vjs-big-play-button", "settle": 0.4},
                                {"click": ".hds-video-container .vjs-fullscreen-control", "settle": 0.4}]
                               if video else [])
                capture_seconds = 24.0 if video else scene.get("seconds", 12)
                capture_key = fingerprint({"url": scene["url"], "seconds": capture_seconds,
                                           "moves": scene.get("moves", []), "preparation": preparation, "version": 3})
                cached = self.context.artifact(f"captures/source-{capture_key}.json")
                if cached.exists():
                    saved = json.loads(cached.read_text(encoding="utf-8"))
                    path = Path(saved["capture"]["path"]).resolve()
                    if (not path.is_relative_to(self.context.root.resolve()) or not path.is_file()
                            or hashlib.sha256(path.read_bytes()).hexdigest() != saved["sha256"]):
                        raise ValueError("Cached OBS evidence changed; targeted repair required")
                    results.append({**saved["capture"], "reused_capture": True})
                    continue
                if video:
                    from openjarvis.one_agents.planexium_obs import capture_video
                    scene_id = str(scene.get("id") or i)
                    if not scene_id.isdigit():
                        raise ValueError("Capture scene ID must be numeric")
                    target = Path(output_root) / f"planexium-{mission_id}-{scene_id}-native-v3.mkv"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    obs = self.connect_obs()
                    try:
                        row = capture_video(obs, video, target, capture_seconds, probe=probe_stock)
                    finally:
                        obs.close()
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    cached.write_text(json.dumps({"capture": row, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}, indent=2), encoding="utf-8")
                    results.append(row)
                    continue
                self.ensure_source()
                scene_id = str(scene.get("id") or i)
                if not scene_id.isdigit():
                    raise ValueError("Capture scene ID must be numeric")
                capture = f"planexium-{mission_id}-{scene_id}" + ("-player-v2" if video else "")
                inputs = {"captureId": capture, "topic": scene["title"], "sourceUrl": scene["url"],
                          "targetSeconds": str(capture_seconds), "prepareMoves": "[]",
                          "recordMoves": json.dumps(scene.get("moves", [])), "videoTitle": scene["title"]}
                # Draft substitution interpolates inputs as strings. Movement actions
                # require native arrays; bind these per capture before submitting.
                import copy
                capture_steps = copy.deepcopy(steps)
                for step in capture_steps:
                    if step.get("action") in {"run_moves", "obs_record_sequence"}:
                        step.setdefault("args", {})["moves"] = (scene.get("moves", [])
                            if step["action"] == "obs_record_sequence" else preparation)
                # Overlays were cleared before player preparation. A second
                # overlay pass after playback would consume the whole timelapse.
                prepared_index = next((n for n,s in enumerate(capture_steps) if s.get("action")=="run_moves"), -1)
                if video and prepared_index >= 0:
                    capture_steps = [s for n,s in enumerate(capture_steps)
                                     if not (n > prepared_index and s.get("action")=="dismiss_overlays")]
                receipt_name = f"obs-{scene_id}-player-v2.json" if video else f"obs-{scene_id}.json"
                out, job = self.draft.run("planexium-official-capture", capture_steps, inputs,
                                          self.context.artifact("receipts/" + receipt_name))
                recorded = out.get("capture_video")
                reported_path = recorded.get("path") if isinstance(recorded, dict) else recorded
                # Installed OBS writes outside robot artifacts. Admit only this
                # exact channel/mission filename within its known capture root.
                expected = (self.workflow.parent.parent / "yatra-captures" / (capture + "-capture.mkv")).resolve()
                if reported_path and Path(reported_path).resolve() == expected and expected.is_file():
                    source = expected
                else:
                    source = self.draft.artifact(out, job, capture + "-capture.mkv")
                target = Path(output_root) / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                row = {"path": str(target), "source_url": scene["url"], "job_id": job,
                       "framing": "full-screen primary-source video" if video else "source document", "seconds": capture_seconds,
                       "source_video": video, "rights_review_required": True}
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps({"capture": row, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}, indent=2), encoding="utf-8")
                results.append(row)
        return {"ok": True, "captures": results}
