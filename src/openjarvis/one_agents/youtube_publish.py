"""IRIS's upload gate for Sonia Travel Vlogs.

ARES hands IRIS a finished SEO package; this module turns it into a gate a human can
approve. Nothing is uploaded until approve_and_upload() is called with the decisions
only a person can make (AI-disclosure, which thumbnail, same-day rule recheck) and a
rationale. The upload itself is always private; going public stays a Studio click.

    python -m openjarvis.one_agents.youtube_publish prepare <youtube-seo-package.json>
    python -m openjarvis.one_agents.youtube_publish approve <upload-gate.json> \
        --synthetic yes|no --thumbnail <png> --rechecked-on YYYY-MM-DD --by NAME --why "..."
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import importlib.util
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

UPLOADER_DIR = Path(os.environ.get("YATRA_UPLOADER_DIR") or r"C:\Users\pc\Documents\LAO\yatra-upload")
HEALTH_FILE = Path(os.environ.get("YATRA_YT_HEALTH") or r"E:\ONE-Suite\data\youtube\token-health.json")
POLICY_FILE = Path(os.environ.get("YATRA_YT_POLICY") or r"E:\ONE-Suite\data\youtube\upload-policy.json")
MAX_HEALTH_AGE_HOURS = 36
REQUIRED_LOCALES = ("hi",)
PUBLIC_CHECKLIST = [
    "Recheck every visa, entry-rule, fee and price claim on the official sources today",
    "Review the machine-translated Hindi title and description",
    "Open the Studio link, confirm the thumbnail and chapters, then set visibility to Public",
    "For an eligible long-form video, start YouTube's native Test & Compare with all 3 sealed thumbnails; "
    "keep candidate 1 if YouTube reports same or inconclusive",
    # YouTube disables comments on a private video, so the channel comment can only go up after this step.
    "Once it is public, post the channel comment from the SEO package (pinned_comment_draft) and pin it",
]


def media_metadata_blockers(pkg: dict[str, Any]) -> list[str]:
    """Floor 12 acceptance contract for LYRA's YouTube package."""
    blockers: list[str] = []
    chapters = list(pkg.get("chapters") or [])
    audit = pkg.get("description_audit")
    if str(pkg.get("schema_version") or "") >= "1.1":
        if not 3 <= len(chapters) <= 8:
            blockers.append(f"MEDIA metadata gate requires 3-8 grouped search chapters (found {len(chapters)})")
        if not isinstance(audit, dict):
            blockers.append("MEDIA metadata gate requires description_audit for schema 1.1+")
        elif not audit.get("ok"):
            failed = [name for name, passed in (audit.get("checks") or {}).items() if not passed]
            blockers.append("MEDIA description audit failed: " + (", ".join(failed) or "unknown check"))
        title_words = {word for word in re.findall(r"[a-z0-9]{4,}",
                       str(pkg.get("recommended_title") or "").casefold())
                       if word not in {"this", "that", "with", "from", "amid", "shorts"}}
        lead = str(pkg.get("description") or "")[:500].casefold()
        if title_words and not any(word in lead for word in title_words):
            blockers.append("MEDIA topic-integrity gate: description does not match the video title")
    provenance = pkg.get("footage_provenance")
    if pkg.get("content_format") == "youtube_short":
        if not isinstance(provenance, dict) or not provenance.get("fresh_for_this_run"):
            blockers.append("MEDIA footage gate: Short has no fresh per-run Envato provenance")
        elif int(provenance.get("unique_vertical_clips") or 0) < 4:
            blockers.append("MEDIA footage gate: Short needs at least 4 unique vertical Envato clips")
    return blockers


def required_locales(pkg: dict[str, Any]) -> tuple[str, ...]:
    """Metadata languages to translate into while preserving the source audio language."""
    if str(pkg.get("language") or "").lower() == "en":
        from openjarvis.one_agents.youtube_seo import GLOBAL_METADATA_LOCALES
        return tuple(pkg.get("localizations_required") or GLOBAL_METADATA_LOCALES)
    return tuple(pkg.get("localizations_required") or REQUIRED_LOCALES)


def load_policy() -> dict[str, Any]:
    """The channel owner's standing decisions. Auto-upload needs an explicit file; no file means a human approves."""
    if not POLICY_FILE.is_file():
        return {"auto_upload_private": False}
    return json.loads(POLICY_FILE.read_text(encoding="utf-8"))


EDIT_TOOLS_DIR = Path(os.environ.get("YATRA_EDIT_DIR") or r"C:\Users\pc\Documents\LAO\yatra-edit")
VISTA_RUNS_ROOT = Path(os.environ.get("VISTA_RUNS_ROOT") or r"C:\Users\pc\Documents\LAO\vista\runs")


def _is_vista_package(gate: dict[str, Any]) -> bool:
    """Identify VISTA-owned uploads without changing any other floor's cleanup policy."""
    try:
        return Path(str(gate.get("package") or "")).resolve().is_relative_to(VISTA_RUNS_ROOT.resolve())
    except (OSError, ValueError):
        return False


def cleanup_after_upload(gate: dict[str, Any]) -> dict[str, Any]:
    """Free the disk a finished video no longer needs, once it is verifiably on YouTube. Never fails the upload.

    yatra_cleanup does the checking (the master is in the upload ledger and the video answers on YouTube, QC has no
    FAIL, every path stays inside the video folder) and keeps the final video, narration, thumbnail and SEO. Intermediates
    go at once, the Envato clips after the policy's stock_retention_days; earlier finished videos whose retention
    has now ended are swept in the same pass."""
    if _is_vista_package(gate):
        return {
            "skipped": "automatic cleanup disabled for VISTA mission; explicit cleanup authorization required",
            "scope": "vista",
        }
    try:
        path = EDIT_TOOLS_DIR / "yatra_cleanup.py"
        if not path.is_file():
            return {"skipped": f"cleanup tool not found: {path}"}
        spec = importlib.util.spec_from_file_location("yatra_cleanup", path)
        cleanup = importlib.util.module_from_spec(spec)
        sys.modules["yatra_cleanup"] = cleanup
        spec.loader.exec_module(cleanup)
        folder = Path(gate["master"]).parent.parent
        mine = cleanup.clean(folder, apply=True, skip_quiet=True)
        # Sweeping older videos only makes sense for a real production folder; anything else (a test, a copy) must
        # never reach out and clean the live YATRA root.
        earlier = ([r for r in cleanup.sweep(apply=True) if Path(r["folder"]) != folder]
                   if cleanup._inside(folder, cleanup.ASSET_ROOT) else [])
        freed = mine.get("freed_bytes", 0) + sum(r.get("freed_bytes", 0) for r in earlier)
        return {"freed_bytes": freed,
                "this_video": {k: mine.get(k) for k in ("deleted", "freed_bytes", "stock_included", "skipped", "errors")},
                "earlier_videos_cleaned": sum(1 for r in earlier if r.get("deleted"))}
    except Exception as exc:  # noqa: BLE001 - housekeeping must never turn a good upload into a failure
        return {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def sweep_finished_videos() -> dict[str, Any]:
    """Clean every earlier video that is verifiably on YouTube, before a new run needs the disk. Never fails.

    Each folder still passes yatra_cleanup's own checks (ledger, YouTube, QC, quiet for 10 minutes), and Envato clips
    only go once their retention has ended - which, before this, only happened when another video was uploaded."""
    try:
        path = EDIT_TOOLS_DIR / "yatra_cleanup.py"
        if not path.is_file():
            return {"skipped": f"cleanup tool not found: {path}"}
        spec = importlib.util.spec_from_file_location("yatra_cleanup", path)
        cleanup = importlib.util.module_from_spec(spec)
        sys.modules["yatra_cleanup"] = cleanup
        spec.loader.exec_module(cleanup)
        receipts = cleanup.sweep(apply=True)
        return {"freed_bytes": sum(r.get("freed_bytes", 0) for r in receipts),
                "videos_cleaned": sum(1 for r in receipts if r.get("deleted")),
                "skipped": {Path(r["folder"]).name: r["skipped"] for r in receipts if r.get("skipped")}}
    except Exception as exc:  # noqa: BLE001 - housekeeping must never stop a new video
        return {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def storage_note(cleanup: dict[str, Any] | None) -> str:
    """One line for IRIS's report: what was freed, or why nothing was."""
    if not cleanup:
        return ""
    if cleanup.get("error"):
        return f"\nStorage cleanup did not run: {cleanup['error']}"
    freed = cleanup.get("freed_bytes") or 0
    if freed:
        return (f"\nStorage cleaned: {freed / 1e9:.2f} GB freed (the final video, narration, thumbnail and SEO are kept; "
                f"Envato clips go after the retention days).")
    why = (cleanup.get("this_video") or {}).get("skipped") or cleanup.get("skipped")
    return f"\nStorage cleanup skipped: {why}" if why else ""


def _load(name: str):
    """Load a module from the uploader folder (it lives with the LAO packages, not in this repo)."""
    path = UPLOADER_DIR / f"{name}.py"
    if not path.is_file():
        raise RuntimeError(f"YouTube uploader module not found: {path}")
    if str(UPLOADER_DIR) not in sys.path:
        sys.path.insert(0, str(UPLOADER_DIR))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_health_check() -> bool:
    """Run the same check the daily 09:00 task runs (refresh the token, confirm the channel and scopes) right now.

    The task cannot run while the PC is off at 09:00. On 2026-10-09 the last check was 39 h old, so the Air France
    video was finished and then blocked at the gate with a perfectly good token. The gate now checks the token
    itself instead of trusting only a stale file."""
    import subprocess
    script = UPLOADER_DIR / "youtube_token_health.py"
    if not script.is_file():
        return False
    try:
        done = subprocess.run([sys.executable, str(script)], cwd=str(UPLOADER_DIR), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=180,
                              env={**os.environ, "YATRA_YT_HEALTH": str(HEALTH_FILE), "PYTHONIOENCODING": "utf-8"})
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def token_status(now: datetime | None = None, *, recheck: bool = True) -> dict[str, Any]:
    """Read the health file; when it is missing or stale, run the check now and read it again."""
    if not HEALTH_FILE.is_file():
        if recheck and run_health_check():
            return token_status(now, recheck=False)
        return {"ok": False, "reason": "no token-health.json yet - the daily health check has not run"}
    status = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
    when = datetime.strptime(status["checked_at"], "%Y-%m-%dT%H:%M:%S%z")
    age_h = ((now or datetime.now(timezone.utc)) - when).total_seconds() / 3600
    if age_h > MAX_HEALTH_AGE_HOURS:
        if recheck:
            run_health_check()
            return token_status(None, recheck=False)
        return {"ok": False, "reason": f"last health check was {age_h:.0f}h ago (limit {MAX_HEALTH_AGE_HOURS}h)"}
    if not status.get("ok"):
        return {"ok": False, "reason": status.get("error") or "health check failed"}
    return {"ok": True, "channel": status.get("channel"), "checked_at": status["checked_at"]}


def _qc(root: Path) -> dict[str, Any]:
    path = root / "edit" / "qc-report.json"
    if not path.is_file():
        return {"ok": False, "reason": "edit/qc-report.json is missing"}
    rows = json.loads(path.read_text(encoding="utf-8"))
    failed = [r["check"] for r in rows if str(r.get("level")).upper() == "FAIL"]
    review = [r["check"] for r in rows if str(r.get("level")).upper() == "REVIEW"]
    return {"ok": not failed, "failed": failed, "review": review, "checks": len(rows)}


LOCALIZE_BUDGET_SECONDS = float(os.environ.get("ONE_LOCALIZE_BUDGET_SECONDS", "720"))


LOCALIZE_WORKERS = int(os.environ.get("ONE_LOCALIZE_WORKERS", "3"))


def ensure_localizations(package_path: Path, locales: tuple[str, ...] = REQUIRED_LOCALES, *,
                         budget_seconds: float | None = None, workers: int | None = None,
                         clock=time.monotonic) -> tuple[list[str], dict[str, str]]:
    """Translate every missing locale and store it, flagged for review.

    One language failing (the model refuses, or its answer fails validation twice) never stops the rest,
    and each success is written immediately so a crash keeps the finished ones. Languages are translated a few
    at a time; when the time budget is spent the remaining ones are left for a later run instead of overrunning
    the ARES job's watchdog. The file is re-read before every write so a language saved by another process
    (the overnight runner) is never lost."""
    started = clock()
    budget = LOCALIZE_BUDGET_SECONDS if budget_seconds is None else budget_seconds
    pkg = json.loads(package_path.read_text(encoding="utf-8"))
    todo = [loc for loc in locales if loc not in pkg.setdefault("localizations", {})]
    added: list[str] = []
    failed: dict[str, str] = {}
    if not todo:
        return added, failed
    localize = _load("localize")
    lock = threading.Lock()

    def work(locale: str) -> None:
        if clock() - started > budget:
            failed[locale] = "time budget spent; it will be translated on a later run"
            return
        for attempt in (1, 2):
            try:
                translate_package = localize.translate_package
                if "deadline" in inspect.signature(translate_package).parameters:
                    translated = translate_package(pkg, locale, deadline=started + budget)
                else:  # compatibility with older installed packages and narrow test doubles
                    translated = translate_package(pkg, locale)
                with lock:
                    fresh = json.loads(package_path.read_text(encoding="utf-8"))
                    fresh.setdefault("localizations", {})[locale] = translated
                    package_path.write_text(json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8")
                    added.append(locale)
                return
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    failed[locale] = f"{type(exc).__name__}: {str(exc)[:120]}"

    with ThreadPoolExecutor(max_workers=max(1, workers or LOCALIZE_WORKERS)) as pool:
        list(pool.map(work, todo))
    return added, failed


def prepare_gate(package_path: Path) -> dict[str, Any]:
    """Run every non-human check and write upload-gate.json beside the package."""
    package_path = Path(package_path)
    from openjarvis.one_agents.youtube_channels import SONIA

    SONIA.validate_record(json.loads(package_path.read_text(encoding="utf-8")))
    root = package_path.parent.parent
    uploader = _load("youtube_api_upload")
    warnings: list[str] = []
    blockers: list[str] = []

    editorial_hold = root / "seo" / "editorial-hold.json"
    hold_open = False
    if editorial_hold.is_file():
        try:
            hold = json.loads(editorial_hold.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            blockers.append(f"editorial hold is unreadable: {exc}")
            hold_open = True
        else:
            if str(hold.get("status") or "open").lower() != "resolved":
                hold_open = True
                reasons = [str(item).strip() for item in (hold.get("blockers") or []) if str(item).strip()]
                blockers.extend("editorial hold: " + item for item in (reasons or ["unresolved review"]))

    requested_locales = required_locales(json.loads(package_path.read_text(encoding="utf-8")))
    if hold_open:
        warnings.append("localization skipped while editorial hold is open")
    else:
        try:
            added, failed = ensure_localizations(package_path, requested_locales)
            if added:
                warnings.append(f"{len(added)} localizations ({', '.join(added)}) were machine-translated just now: "
                                "review before going public")
            if failed:
                warnings.append("not localized: " + "; ".join(f"{k} ({v})" for k, v in failed.items()))
        except Exception as exc:  # noqa: BLE001 - a missing translation must not hide the other checks
            warnings.append(f"localization not prepared: {type(exc).__name__}: {str(exc)[:160]}")

    pkg = json.loads(package_path.read_text(encoding="utf-8"))
    blockers += media_metadata_blockers(pkg)
    blockers += capture_semantic_blockers(root)
    master = Path(str(pkg.get("master") or root / "edit" / "master.mp4"))
    if not master.is_file():
        blockers.append(f"master video not found: {master}")
    try:
        _resource, notes = uploader.build_video_resource(pkg, synthetic=False, report_path=master.parent / "assembly-report.json")
        uploader.build_localizations(pkg, _resource["snippet"]["defaultLanguage"], master.parent / "assembly-report.json")
        warnings += notes
    except uploader.UploadRefused as exc:
        blockers.append(str(exc))
    missing_locales = [loc for loc in requested_locales if loc not in (pkg.get("localizations") or {})]
    if missing_locales:
        warnings.append(f"no localization for {missing_locales}")

    qc = _qc(root)
    if not qc["ok"]:
        blockers.append("master QC has failures: " + (", ".join(qc.get("failed") or []) or qc.get("reason", "")))
    elif qc["review"]:
        warnings.append("QC asked for a human look at: " + ", ".join(qc["review"]))

    token = token_status()
    if not token["ok"]:
        blockers.append("YouTube credential is not healthy: " + token["reason"])

    thumb_dir = root / "thumbnail"
    # ARES promotes exactly one experiment winner. Offering every intermediate
    # variant let autopilot select by filename instead of by the scored decision.
    canonical = thumb_dir / "final.png"
    thumbnails = [str(canonical)] if canonical.is_file() else []
    receipt_file = thumb_dir / "thumbnail-receipt.json"
    if thumbnails and receipt_file.is_file():
        # A thumbnail ChatGPT never drew is a local composite of a raw portrait photo. On 2026-10-13 all three
        # ChatGPT variants failed and the winner put "CHECK STATUS" over Sonia's face on a Bali photo for a
        # Singapore video, while the pre-upload score called it 92.7. It must never ship as the final.
        try:
            receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            receipt = {}
        if receipt.get("source") == "editorial_approval":
            if receipt.get("ok") is not True:
                blockers.append("editorial-approved thumbnail was superseded; exact selected asset is required")
                thumbnails = []
            expected = str(receipt.get("sha256") or "")
            actual = hashlib.sha256(canonical.read_bytes()).hexdigest()
            if not expected or expected != actual or Path(str(receipt.get("path") or "")).resolve() != canonical.resolve():
                blockers.append("editorial-approved thumbnail changed after ARES hash binding")
                thumbnails = []
        sources = {str(v.get("source") or "") for v in receipt.get("variants") or [] if v.get("ok")}
        if sources and sources <= {"local_fallback"}:
            blockers.append("thumbnail is a local fallback: every ChatGPT variant failed "
                            f"({'; '.join(sorted({str(v.get('fallback_reason') or '') for v in receipt.get('variants') or []}))[:160]}); "
                            "ARES must regenerate it")
            thumbnails = []
    if not thumbnails and not any(b.startswith("thumbnail is a local fallback") for b in blockers):
        if load_policy().get("allow_without_thumbnail"):
            warnings.append("no final thumbnail: YouTube will pick a frame until one is set in Studio")
        else:
            blockers.append("no final thumbnail in thumbnail/ (ARES must produce one)")

    # Preserve all three QC-passed candidates for YouTube Studio's native
    # concurrent test. The private Data API upload can set only the editorial
    # default; it cannot start or score Test & Compare.
    from openjarvis.one_agents import youtube_thumbnail_ab
    if receipt_file.is_file():
        try:
            experiment_receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
            thumbnail_ab = youtube_thumbnail_ab.build_plan(
                root, experiment_receipt, visibility="private",
                content_format=str(pkg.get("content_format") or "long_form"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            thumbnail_ab = {"status": "blocked", "blockers": [f"A/B/C plan could not be sealed: {exc}"]}
    else:
        thumbnail_ab = {"status": "blocked", "blockers": ["thumbnail experiment receipt is missing"]}

    already = None
    if master.is_file():
        already = (uploader.ledger_load().get(uploader.file_sha256(master)) or {}).get("video_id")
    status = ("already_uploaded" if already else "blocked" if blockers else "awaiting_approval")
    gate = {
        "schema": "sonia-youtube-upload-gate/1", "status": status, "prepared_at": datetime.now(timezone.utc).isoformat(),
        "package": str(package_path), "master": str(master), "title": pkg.get("recommended_title"),
        "thumbnails": thumbnails, "already_uploaded_as": already,
        "thumbnail_ab_test": thumbnail_ab,
        "blockers": blockers, "warnings": warnings, "token": token, "qc": qc,
        "decisions_required": ["synthetic_disclosure (yes|no)", "thumbnail (one of thumbnails)",
                               "rechecked_on (today's date: visa/TDAC/price facts re-verified)", "approver and rationale (10+ chars)"],
        "visibility": "private - the upload never makes a video public",
        "public_checklist": PUBLIC_CHECKLIST,
        "approve_with": (f'python -m openjarvis.one_agents.youtube_publish approve "{root / "seo" / "upload-gate.json"}" '
                         '--synthetic yes|no --thumbnail <png> --rechecked-on YYYY-MM-DD --by <name> --why "<reason>"'),
    }
    out = root / "seo" / "upload-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    gate["path"] = str(out)
    return gate


def capture_semantic_blockers(root: Path) -> list[str]:
    """Require pixel-derived semantic proof before a YATRA master can upload."""
    root = Path(root)
    capture_dir = Path(root) / "captures"
    active = [path for path in capture_dir.glob("*-capture.*")
              if path.is_file() and path.suffix.lower() in {".mkv", ".mp4", ".mov"}]
    plan_path = root / "obs-capture-plan.json"
    planned: set[str] = set()
    planned_rows: dict[str, dict[str, Any]] = {}
    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            planned_rows = {str(row.get("captureId") or row.get("capture_id") or ""): row
                            for row in (plan.get("recipes") or [])
                            if row.get("captureId") or row.get("capture_id")}
            planned = set(planned_rows)
        except (OSError, ValueError) as exc:
            return [f"OBS capture plan is unreadable: {exc}"]
    active_by_id = {re.sub(r"-capture$", "", path.stem): path for path in active}
    missing_recordings = sorted(planned - set(active_by_id))
    if missing_recordings:
        return ["OBS capture plan has no recording for: " + ", ".join(missing_recordings)]
    if not active and not planned:
        return []
    receipt_path = capture_dir / "capture-semantic-qc.json"
    if not receipt_path.is_file():
        return ["OBS capture semantic receipt is missing; rerun YATRA capture integrity before upload"]
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"OBS capture semantic receipt is unreadable: {exc}"]
    if receipt.get("schema") != "yatra-capture-semantic-qc/1" or not receipt.get("ok"):
        return ["OBS capture semantic QC failed: " + str(receipt.get("detail") or "invalid receipt")]
    passed_rows = {str(item.get("capture_id") or ""): item
                   for item in receipt.get("semantic_receipts") or [] if item.get("ok")}
    expected = set(active_by_id) | planned
    passed = set(passed_rows)
    missing = sorted(expected - passed)
    if missing:
        return ["OBS capture semantic receipt does not cover: " + ", ".join(missing)]
    stale: list[str] = []
    for capture_id in sorted(expected):
        path = active_by_id.get(capture_id)
        row = passed_rows.get(capture_id) or {}
        if not path:
            stale.append(capture_id)
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        recipe = planned_rows.get(capture_id) or {}
        evidence = recipe.get("semanticEvidence") or recipe.get("semantic_evidence") or {}
        contract = {
            "capture_id": capture_id,
            "source_url": str(recipe.get("sourceUrl") or ""),
            "topic": str(recipe.get("topic") or ""),
            "semantic_evidence": evidence,
        }
        contract_digest = hashlib.sha256(json.dumps(
            contract, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        if (row.get("media_sha256") != digest or row.get("media_size") != path.stat().st_size
                or row.get("semantic_contract_sha256") != contract_digest):
            stale.append(capture_id)
    if stale:
        return ["OBS capture semantic receipt is stale for: " + ", ".join(stale)]
    return []


def approve_and_upload(gate_path: Path, *, synthetic: str, thumbnail: str | None, rechecked_on: str | None,
                       approver: str, rationale: str, today: date | None = None, standing_policy: bool = False) -> dict[str, Any]:
    """The decision step. A person supplies every decision; a standing policy supplies the same ones
    from the owner's policy file. Either way the upload is private - the same-day fact recheck
    belongs to the later go-public step, so it is only demanded when a person approves by hand."""
    gate_path = Path(gate_path)
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    from openjarvis.one_agents.youtube_channels import SONIA

    SONIA.validate_record(json.loads(Path(gate["package"]).read_text(encoding="utf-8")))
    if gate.get("status") not in ("awaiting_approval", "upload_failed"):
        raise ValueError(f"gate is {gate.get('status')!r}, not awaiting approval"
                         + (f": {'; '.join(gate.get('blockers') or [])}" if gate.get("blockers") else ""))
    if synthetic not in ("yes", "no"):
        raise ValueError("synthetic must be 'yes' or 'no' - the AI-disclosure choice is never defaulted")
    if not approver.strip() or len(rationale.strip()) < 10:
        raise ValueError("an approver and a rationale of 10+ characters are required")
    if not standing_policy:
        if rechecked_on != (today or date.today()).isoformat():
            raise ValueError("rechecked_on must be today's date: volatile travel facts must be re-verified the day of upload")
        if not thumbnail or thumbnail not in gate.get("thumbnails", []) or not Path(thumbnail).is_file():
            raise ValueError("thumbnail must be one of the gate's thumbnails")
    elif thumbnail and (thumbnail not in gate.get("thumbnails", []) or not Path(thumbnail).is_file()):
        raise ValueError("thumbnail must be one of the gate's thumbnails")
    token = token_status()
    if not token["ok"]:
        raise ValueError("YouTube credential is not healthy: " + token["reason"])

    uploader = _load("youtube_api_upload")
    try:
        # Captions are part of the upload, not an optional later repair. Build
        # them from FABULA's measured narration and attach the track as soon as
        # the private video exists.
        from openjarvis.one_agents import youtube_distribution
        subtitle = youtube_distribution.build_srt(Path(gate["package"]))
        language = youtube_distribution.spoken_language(
            json.loads(Path(gate["package"]).read_text(encoding="utf-8")))
        report = uploader.run(Path(gate["package"]), video=Path(gate["master"]),
                              thumbnail=Path(thumbnail) if thumbnail else None, synthetic=synthetic, execute=True,
                              caption=subtitle, caption_language=language)
    except Exception as exc:
        gate.update(status="upload_failed", last_error=f"{type(exc).__name__}: {str(exc)[:300]}")
        gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    gate.update(status="uploaded_private", video_id=report.get("video_id"), studio_url=report.get("studio_url"),
                delivery_verification=report.get("delivery_verification"),
                approved_by=approver.strip(), approval_rationale=rationale.strip(), synthetic_disclosure=synthetic,
                thumbnail_used=thumbnail, rechecked_on=rechecked_on, standing_policy=standing_policy,
                subtitle=str(subtitle), subtitle_language=language,
                uploaded_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                next_step="Review in Studio, then set visibility to Public by hand.")
    if isinstance(gate.get("thumbnail_ab_test"), dict) and gate["thumbnail_ab_test"].get("path"):
        from openjarvis.one_agents import youtube_thumbnail_ab
        gate["thumbnail_ab_test"] = youtube_thumbnail_ab.mark_private_upload(
            gate["thumbnail_ab_test"], video_id=report.get("video_id"), studio_url=report.get("studio_url"))
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    gate["cleanup"] = cleanup_after_upload(gate)
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    return gate


def autopilot_upload(package_path: Path) -> dict[str, Any]:
    """Prepare the gate and, when the owner's standing policy allows it, upload privately without a click."""
    gate = prepare_gate(Path(package_path))
    policy = load_policy()
    if gate["status"] != "awaiting_approval" or not policy.get("auto_upload_private"):
        return gate
    if policy.get("synthetic_disclosure") not in ("yes", "no"):
        gate.update(status="blocked", blockers=gate["blockers"] + ["upload-policy.json has no synthetic_disclosure yes|no"])
        return gate
    thumbnail = gate["thumbnails"][0] if gate["thumbnails"] else None
    return approve_and_upload(
        Path(gate["path"]), synthetic=policy["synthetic_disclosure"], thumbnail=thumbnail, rechecked_on=None,
        approver=f"standing policy ({policy.get('set_by', 'channel owner')}, {policy.get('set_on', 'undated')})",
        rationale="Private-only upload under the channel owner's standing policy; going public stays manual.",
        standing_policy=True)


def summarize(gate: dict[str, Any]) -> str:
    """One paragraph for IRIS's delivery report."""
    if not gate:
        return ""
    if gate.get("status") == "awaiting_approval":
        warn = f" Warnings: {'; '.join(gate['warnings'])}." if gate.get("warnings") else ""
        return ("YouTube upload gate is ready and waiting for your approval (private upload only)." + warn +
                f"\nApprove with: {gate.get('approve_with', '')}")
    if gate.get("status") == "blocked":
        return "YouTube upload gate is blocked: " + "; ".join(gate.get("blockers") or ["unknown reason"])
    if gate.get("status") == "already_uploaded":
        return f"This cut is already on YouTube as {gate.get('already_uploaded_as')} (private)."
    if gate.get("status") == "uploaded_private":
        todo = "\n".join(f"  {i}. {item}" for i, item in enumerate(gate.get("public_checklist") or PUBLIC_CHECKLIST, 1))
        warn = f"\nNotes: {'; '.join(gate['warnings'])}." if gate.get("warnings") else ""
        freed = (gate.get("cleanup") or {}).get("freed_bytes") or 0
        tidy = (f"\nStorage cleaned: {freed / 1e9:.2f} GB freed (the final video, narration, thumbnail and SEO are kept; "
                f"Envato clips are removed after the retention days)." if freed else "")
        return (f"The private YouTube draft is up: {gate.get('studio_url')}{warn}{tidy}\n"
                f"Before you make it public:\n{todo}")
    if gate.get("status") == "upload_failed":
        return f"The YouTube upload failed and can be retried: {gate.get('last_error') or gate.get('error', '')}"
    return f"YouTube upload gate: {gate.get('status', 'unavailable')} {gate.get('error', '')}".strip()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare"); p.add_argument("package", type=Path)
    a = sub.add_parser("approve"); a.add_argument("gate", type=Path)
    a.add_argument("--synthetic", required=True); a.add_argument("--thumbnail", required=True)
    a.add_argument("--rechecked-on", required=True); a.add_argument("--by", required=True); a.add_argument("--why", required=True)
    args = ap.parse_args()
    if args.cmd == "prepare":
        print(json.dumps(prepare_gate(args.package), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(approve_and_upload(args.gate, synthetic=args.synthetic, thumbnail=args.thumbnail,
                                            rechecked_on=args.rechecked_on, approver=args.by, rationale=args.why),
                         ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
