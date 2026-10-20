"""ARES-owned science metadata and a fail-closed PLANEXIUM upload boundary."""
import hashlib
import json
import re
from pathlib import Path
from datetime import datetime, timezone

from openjarvis.one_agents.youtube_channels import PLANEXIUM
from openjarvis.one_agents.youtube_seo import description_audit, ollama_json, _valid_tags


def ares_json(prompt, payload):
    """Use the stronger installed local model for scientific editorial wording."""
    from openjarvis.one_agents import local_llm
    available = local_llm.installed()
    for model in ("qwen3:8b", "qwen3.5:9b"):
        if model in available:
            return local_llm.chat_json(model, prompt, payload, temperature=0.1, num_ctx=8192, timeout=900)
    return ollama_json(prompt, payload)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metadata_hash(package):
    return hashlib.sha256(json.dumps({k: package.get(k) for k in
        ("recommended_title", "description", "tags", "primary_query")},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def require_seo(package):
    if package.get("brand") != "planexium":
        return
    audit = description_audit(package.get("description", ""),
                              package.get("primary_query", ""), package.get("tags", []), PLANEXIUM)
    audit["checks"]["valid_title"] = 1 <= len(package.get("recommended_title", "")) <= 100
    audit["checks"]["tag_budget_under_500"] = audit["tag_budget_chars"] <= 500
    audit["checks"]["ares_owned"] = package.get("seo_owner") == "ARES"
    audit["checks"]["metadata_unchanged_since_audit"] = (
        package.get("seo_metadata_sha256") == metadata_hash(package))
    audit["ok"] = all(audit["checks"].values())
    if not audit["ok"]:
        failed = [k for k, v in audit["checks"].items() if not v]
        raise ValueError("PLANEXIUM SEO audit failed: " + ", ".join(failed))
    return audit


def generate(package, science, *, job_id, llm=ollama_json, editorial_feedback=None):
    prompt = (
        "You are ARES, the SEO agent for The Planexium science YouTube channel. "
        "Return JSON: title (string), primary_query (string), opening (string), "
        "tags (JSON array of strings), hashtags (JSON array of exactly 3 strings). "
        "Use only the supplied science/script; distinguish simulated Mars on Earth from actual Mars. "
        "Title max 100 characters, compelling but factual; complement the existing thumbnail hook. "
        "primary_query: a natural search phrase of 2-6 words. "
        "opening: 2 short useful paragraphs, include the exact natural primary_query and 'this video' "
        "within the first 200 characters. No fabricated keyword volumes, rankings, or trending claims. "
        "tags: 15-25 distinct relevant search phrases, total YouTube tag budget 200-450 characters "
        "(spaces/commas count); no isolated words such as days/crew/nears, no unrelated topics. "
        "hashtags: exactly 3 relevant hashtags. Keep all scientific quantities source-grounded. "
        "Do not claim the crew are physically on Mars. Return plain Unicode, no mojibake.")
    prompt += (
        " Research being conducted is not a proven result: do not write 'proves', 'proving', "
        "'findings show' or claim psychological effects unless the input explicitly reports results. "
        "Describe research aims as studying/testing/exploring. Avoid markdown asterisks in YouTube text. "
        "Use 'simulated Mars' rather than 'Mars Sim'. Prefer concrete mission/topic searches over "
        "generic or speculative psychological-effects keywords. Never invent comparisons, flight times, "
        "results or crew qualifications. Call analog participants 'crew members', not astronauts. "
        "Follow editorial_feedback when supplied.")
    errors = None
    for attempt in range(2):
        out = llm(prompt, {"science": {"video_title": science.get("video_title"),
                                      "claims": science.get("claims", [])},
                          "current_title": package["recommended_title"],
                          "thumbnail_hook": package.get("thumbnail_strategy", {}).get("concepts", [{}])[0].get("text"),
                          "editorial_feedback": editorial_feedback,
                          "previous_validation_error": errors})
        try:
            result = dict(package)
            title = str(out["title"]).strip()
            opening = str(out["opening"]).strip()
            if re.search(r"\b(proves?|proving|findings show)\b", opening, re.I):
                raise ValueError("Description must distinguish research aims from established results")
            opening = opening.replace("**", "")
            query = " ".join(str(out["primary_query"]).split())
            if not query or len(query) > 80:
                raise ValueError("Primary query must be a concise natural search phrase")
            if query.casefold() not in opening[:200].casefold():
                opening = query + ": " + opening
            hashtags = out["hashtags"]
            if isinstance(hashtags, str):
                hashtags = re.findall(r"#[A-Za-z][A-Za-z0-9_]+", hashtags)
            if isinstance(hashtags, list):
                hashtags = ["#"+re.sub(r"\s+", "", str(h).strip().lstrip("#"))
                            for h in hashtags]
            tags = out["tags"]
            if isinstance(tags, str):
                tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
            if (not isinstance(hashtags, list) or len(set(hashtags)) != 3
                    or any(not re.fullmatch(r"#[A-Za-z][A-Za-z0-9_]{1,29}", h) for h in hashtags)):
                raise ValueError("Exactly three valid distinct hashtags required")
            if any(x in title+opening for x in ("â€", "\ufffd")):
                raise ValueError("Invalid text encoding")
            old = package["description"]
            if "CHAPTERS\n" not in old:
                raise ValueError("Measured chapters missing")
            tail = "CHAPTERS\n"+old.split("CHAPTERS\n", 1)[1]
            tail = re.sub(r"(?<!\w)#[A-Za-z0-9_]+", "", tail).strip()
            result.update(recommended_title=title, primary_query=query,
                          description=opening+"\n\n"+tail+"\n\n"+" ".join(hashtags),
                          tags=_valid_tags(tags, limit=450), hashtags=hashtags, seo_owner="ARES",
                          seo_job_id=job_id, metadata_source="ares_model",
                          public_publish_authorized=False)
            result.update(owner="ARES", handoff="PLANEXIUM -> ARES SEO audit -> human upload review")
            result["seo_metadata_sha256"] = metadata_hash(result)
            result["description_audit"] = require_seo(result)
            return result
        except (ValueError, KeyError, TypeError) as exc:
            errors = str(exc)
    raise ValueError("ARES could not produce passing SEO: "+str(errors))


def run_job(job):
    try:
        return _run_job(job)
    except Exception as exc:
        from openjarvis.one_agents.planexium import load_config, context_for, _write
        payload = json.loads(job["task"])
        if payload.get("brand") == "planexium" and payload.get("stage") == "seo":
            ctx = context_for(payload["mission_id"], load_config())
            health_path = ctx.root/"production-health.json"
            health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else {}
            health.update(status="seo_failed", stage="seo", seo_owner="ARES", seo_job_id=job["id"],
                          seo_audit_passed=False, production_complete=False,
                          error_class=type(exc).__name__, updated_at=datetime.now(timezone.utc).isoformat())
            _write(health_path, health)
            ledger_path = ctx.root.parent/"production-ledger.json"
            if ledger_path.exists():
                ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
                if ctx.mission_id in ledger:
                    ledger[ctx.mission_id]["status"] = "seo_failed"
                    _write(ledger_path, ledger)
        raise


def _run_job(job):
    from openjarvis.one_agents.planexium import load_config, context_for, _write
    payload = json.loads(job["task"])
    if payload.get("brand") != "planexium" or payload.get("stage") != "seo":
        raise ValueError("ARES requires explicit PLANEXIUM SEO handoff")
    ctx = context_for(payload["mission_id"], load_config())
    root = ctx.root
    package_path = root/"seo/youtube-seo-package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    gate_path = root/"review-gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if digest(package["master"]) != gate["master_sha256"]:
        raise ValueError("Master differs from reviewed video")
    science = json.loads((root/"science-plan.json").read_text(encoding="utf-8"))
    revision = payload.get("revision", "")
    if revision and not re.fullmatch(r"[a-z0-9-]{1,40}", revision):
        raise ValueError("Invalid SEO revision")
    seo_dir = root/"seo"/revision if revision else root/"seo"
    target = seo_dir/"ares-seo-package.json"
    receipt_path = seo_dir/"ares-receipt.json"
    if target.exists() and receipt_path.exists():
        result = json.loads(target.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt["master_sha256"] != digest(package["master"]) or receipt["package_sha256"] != digest(target):
            raise ValueError("Existing ARES receipt changed")
        require_seo(result)
    else:
        attempts = []
        def model_with_evidence(prompt, data):
            candidate = ares_json(prompt, data)
            attempts.append(candidate)
            _write(seo_dir/"ares-model-attempts.json", {"job_id": job["id"], "attempts": attempts})
            return candidate
        result = generate(package, science, job_id=job["id"],
                          editorial_feedback=payload.get("editorial_feedback"), llm=model_with_evidence)
        _write(target, result)
        _write(receipt_path, {"agent": "ARES", "job_id": job["id"],
                             "master_sha256": digest(package["master"]),
                             "package_sha256": digest(target), "audit": require_seo(result)})
    gate.update(package=str(target), package_sha256=digest(target), seo_owner="ARES",
                seo_audit_passed=True, status="awaiting_human_review")
    _write(gate_path, gate)
    checkpoint = root/"checkpoints/package.json"
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        saved["files"]["review-gate.json"] = digest(gate_path)
        saved["files"][target.relative_to(root).as_posix()] = digest(target)
        saved["result"].update(output=str(target), seo_job_id=job["id"])
        _write(checkpoint, saved)
    health_path = root/"production-health.json"
    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else {}
    health.update(status="uploaded_private" if health.get("uploaded") else "awaiting_review",
                  seo_owner="ARES", seo_job_id=job["id"], seo_audit_passed=True,
                  public_publish_authorized=False, production_complete=True,
                  current_stage="seo", blocked_reason=None, error_class=None,
                  updated_at=datetime.now(timezone.utc).isoformat())
    _write(health_path, health)
    ledger_path = root.parent/"production-ledger.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        if ctx.mission_id in ledger:
            ledger[ctx.mission_id]["status"] = health["status"] if health.get("uploaded") else "review_ready"
            _write(ledger_path, ledger)
    return {"agent": "ARES", "mission_id": ctx.mission_id, "status": "seo_passed",
            "output": str(target), "published": False, "audit": require_seo(result)}
