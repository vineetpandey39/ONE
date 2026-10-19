"""LinkedIn Authority v2 plumbing: ARES picks the story, HERALD writes, gates, renders and publishes it.

The decisions live in floors/floor_03_growth/lib (tech_radar, linkedin_v2,
carousel_render). This file is only the plumbing that needs ONE's runtime:
the LAO tool, stages, the vault and the queue. It never imports runtime.py;
the runtime hands in what it owns.

Safety shape, in the order it matters
  1. Nothing is published unless the quality gate passed AND the scheduler's
     fire receipt granted publish authority AND the channel is in "auto" mode.
  2. Any failure BEFORE the publish job starts falls back to the v1 post, so a
     bad day for v2 costs nothing: the slot still posts.
  3. Once the publish job has started there is no fallback. The outcome is
     unknown (it may have posted), and a second post would be worse than none.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from openjarvis.one_agents import floors_bridge, stages

DRAFT_PROCESS = "LinkedIn v2 - Draft"
PUBLISH_PROCESS = "LinkedIn v2 - Publish"
TERMINAL = {"Successful", "Failed", "Stopped", "Cancelled", "Faulted"}
FLOOR = "floor_03_growth"


class Libs:
    def __init__(self) -> None:
        self.radar = floors_bridge.load(FLOOR, "tech_radar")
        self.v2 = floors_bridge.load(FLOOR, "linkedin_v2")
        self.render = floors_bridge.load(FLOOR, "carousel_render")  # None when Pillow is missing

    @property
    def ready(self) -> bool:
        return self.radar is not None and self.v2 is not None


def libs() -> Libs | None:
    bundle = Libs()
    return bundle if bundle.ready else None


def agent_dir(home: Path) -> Path:
    path = home / "agent_outputs" / "linkedin"
    path.mkdir(parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------------------- ARES side

def plan(*, weekday: int, fetch: Callable[[str], bytes], prior_titles: list[str], home: Path,
         job_id: str) -> dict[str, Any] | None:
    """Choose today's lane, format and story. None means v2 is off or cannot run,
    and the caller keeps the v1 flow."""
    bundle = libs()
    if bundle is None:
        return None
    config = bundle.v2.load_v2_config()
    if not config.get("enabled"):
        return None
    lane = bundle.radar.lane_for(weekday)
    fmt = bundle.v2.format_for(weekday, config)
    if fmt == "carousel" and bundle.render is None:
        fmt = "text"  # no Pillow in this interpreter: degrade the format, not the day
    base = agent_dir(home)
    recent = bundle.v2.recent_titles(bundle.v2.load_ledger(base / "ledger.json")) + list(prior_titles)
    choice = bundle.radar.choose(fetch, lane, recent)
    story = choice.get("picked")
    if not story:
        return None
    radar_path = base / f"{job_id}-radar.json"
    radar_path.write_text(json.dumps(choice, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {"story": story, "lane": lane, "lane_label": choice["lane_label"], "format": fmt,
            "story_source": choice["source"], "runners_up": choice["runners_up"], "radar_path": str(radar_path),
            "publish_mode": config.get("publish_mode", "auto")}


# --------------------------------------------------------------------------- LAO helpers

def _find_artifact(roots: tuple[Path, ...], lao_job: str, filename: str) -> Path | None:
    for root in roots:
        for folder in ("artifacts", "artifacts-02", "artifacts-studio"):
            candidate = root / folder / lao_job / filename
            if candidate.is_file() and candidate.stat().st_size > 2:
                return candidate
    return None


def _poll(tool: Any, process: str, lao_job: str, *, max_wait: float, poll: float, sleep: Callable[[float], None],
          heartbeat: Callable[[], None] | None = None) -> tuple[str, dict[str, Any]]:
    status, last, waited = "Pending", {}, 0.0
    while waited < max_wait:
        sleep(poll)
        waited += poll
        if heartbeat:
            heartbeat()
        probe = tool.execute(action="status", process_name=process, scope="production", job_id=lao_job)
        if not probe.success:
            continue
        last = probe.metadata or {}
        status = str((last.get("job") or {}).get("status") or status)
        if status in TERMINAL:
            break
    return status, last


def run_draft(tool: Any, prompt: str, roots: tuple[Path, ...], *, max_wait: float, poll: float,
              sleep: Callable[[float], None]) -> dict[str, Any]:
    started = tool.execute(action="start", mode="publish", process_name=DRAFT_PROCESS, scope="production",
                           confirm_publish=True,
                           input_args={"prompt": prompt, "chatgptCredentialAssetName": "chatgptLogin"})
    if not started.success:
        return {"status": "refused", "lao_job": "", "raw": "", "error": str(started.content)[:300]}
    lao_job = str(((started.metadata or {}).get("job") or {}).get("id") or "")
    if not lao_job:
        return {"status": "no_job", "lao_job": "", "raw": "", "error": "LAO returned no job id"}
    status, _ = _poll(tool, DRAFT_PROCESS, lao_job, max_wait=max_wait, poll=poll, sleep=sleep)
    raw = ""
    if status == "Successful":
        found = _find_artifact(roots, lao_job, "linkedin_v2_draft.json")
        if found:
            try:
                raw = str(json.loads(found.read_text(encoding="utf-8"))[0].get("output") or "")
            except (OSError, ValueError, IndexError, AttributeError):
                raw = ""
    return {"status": status, "lao_job": lao_job, "raw": raw, "error": "" if raw else f"no draft artifact ({status})"}


def _publish_args(draft: dict[str, Any], story: dict[str, Any], rendered: dict[str, Any] | None) -> dict[str, str]:
    base = {"postText": draft["caption"], "hashtags": draft.get("hashtags", "")}
    if rendered:
        title = str((draft.get("slides") or [{}])[0].get("title") or story.get("title") or "")[:100]
        return {**base, "documentPath": rendered["pdf"], "documentTitle": title}
    return {**base, "textOnly": "1"}


# --------------------------------------------------------------------------- HERALD side

def produce(*, v2_payload: dict[str, Any], job_id: str, tool: Any, home: Path, roots: tuple[Path, ...],
            max_wait: float = 420.0, poll: float = 10.0, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Write -> gate -> render, regenerating on rejection. Never publishes."""
    bundle = libs()
    if bundle is None:
        return {"status": "fallback", "reason": "LinkedIn v2 floor modules are unavailable"}
    config = bundle.v2.load_v2_config()
    story, fmt = v2_payload["story"], v2_payload["format"]
    lane_label = v2_payload.get("lane_label", "")
    base = agent_dir(home)
    out_dir = base / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = bundle.v2.load_ledger(base / "ledger.json")
    openers = [str(r.get("opener", "")) for r in rows[-8:] if r.get("opener")]
    attempts = 1 + int(config.get("max_regenerations", 2))
    fix: list[str] | None = None
    problems: list[str] = []
    for attempt in range(1, attempts + 1):
        stages.set_stage("herald", stages.EXECUTING, f"Writing the {fmt} in ChatGPT (attempt {attempt}/{attempts})")
        prompt = bundle.v2.writer_prompt(story, lane_label, fmt, avoid_openers=openers, fix=fix)
        result = run_draft(tool, prompt, roots, max_wait=max_wait, poll=poll, sleep=sleep)
        (out_dir / f"attempt-{attempt}-raw.txt").write_text(result.get("raw", ""), encoding="utf-8")
        if not result["raw"]:
            problems = [f"the ChatGPT draft job gave nothing ({result['status']}: {result.get('error', '')})"]
            fix = None
            continue
        draft = bundle.v2.parse_draft(result["raw"], fmt)
        verdict = bundle.v2.gate(draft, story, rows)
        problems = list(verdict["problems"])
        rendered = None
        if not problems and fmt == "carousel":
            rendered = bundle.render.render(draft["slides"], out_dir, name="carousel")
            problems = list(rendered["problems"])
        (out_dir / f"attempt-{attempt}-verdict.json").write_text(
            json.dumps({"problems": problems, "warnings": verdict["warnings"]}, indent=2), encoding="utf-8")
        if not problems:
            (out_dir / "draft.json").write_text(
                json.dumps({"story": story, "draft": draft, "verdict": verdict}, ensure_ascii=False, indent=2,
                           default=str), encoding="utf-8")
            return {"status": "ready", "draft": draft, "verdict": verdict, "rendered": rendered,
                    "attempts": attempt, "out_dir": str(out_dir), "draft_job": result["lao_job"]}
        fix = problems
    return {"status": "fallback", "reason": "; ".join(problems)[:400], "problems": problems, "out_dir": str(out_dir)}


def publish(*, ready: dict[str, Any], v2_payload: dict[str, Any], tool: Any, attach: Callable[[str], None],
            heartbeat: Callable[[], None], roots: tuple[Path, ...], max_wait: float = 720.0, poll: float = 10.0,
            sleep: Callable[[float], None] = time.sleep, dry_run: bool = False) -> dict[str, Any]:
    story, draft, rendered = v2_payload["story"], ready["draft"], ready.get("rendered")
    args = _publish_args(draft, story, rendered)
    if dry_run:
        args["dryRun"] = "true"
    started = tool.execute(action="start", mode="publish", process_name=PUBLISH_PROCESS, scope="production",
                           confirm_publish=True, input_args=args)
    if not started.success:
        return {"status": "not_started", "error": str(started.content)[:300]}
    lao_job = str(((started.metadata or {}).get("job") or {}).get("id") or "")
    if not lao_job:
        return {"status": "not_started", "error": "LAO returned no job id for the publish run"}
    attach(lao_job)
    return finish_publish(lao_job=lao_job, tool=tool, heartbeat=heartbeat, roots=roots, max_wait=max_wait,
                          poll=poll, sleep=sleep)


def finish_publish(*, lao_job: str, tool: Any, heartbeat: Callable[[], None], roots: tuple[Path, ...],
                   max_wait: float = 720.0, poll: float = 10.0,
                   sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    # HERALD's outer job watchdog is 45 minutes: 3 drafts x 420s + this 720s stays inside it.
    status, last = _poll(tool, PUBLISH_PROCESS, lao_job, max_wait=max_wait, poll=poll, sleep=sleep, heartbeat=heartbeat)
    if status != "Successful":
        # The job log is where "Unknown workflow action" shows up; it decides whether anything could have posted.
        try:
            probe = tool.execute(action="status", process_name=PUBLISH_PROCESS, scope="production", job_id=lao_job,
                                 include_logs=True)
            if probe.success:
                last = probe.metadata or last
        except Exception:  # noqa: BLE001 - the verdict below then simply stays "failed, outcome unknown"
            pass
    receipt: dict[str, Any] = {}
    found = _find_artifact(roots, lao_job, "linkedin_v2_receipt.json")
    if found:
        try:
            receipt = json.loads(found.read_text(encoding="utf-8"))[0]
        except (OSError, ValueError, IndexError):
            receipt = {}
    unknown_action = "Unknown workflow action" in json.dumps(last, default=str)
    return {"status": "published" if status == "Successful" else "failed", "lao_status": status,
            "lao_job": lao_job, "receipt": receipt, "unknown_action": unknown_action}


def record(*, home: Path, v2_payload: dict[str, Any], draft: dict[str, Any], published: bool, lao_job: str = "") -> None:
    """Remember what went out so the radar never repeats it and openers vary."""
    bundle = libs()
    if bundle is None:
        return
    story = v2_payload["story"]
    first = (draft.get("caption", "").splitlines() or [""])[0]
    bundle.v2.append_ledger(
        agent_dir(home) / "ledger.json",
        {"story_title": story.get("title", ""), "opener": first[:140], "format": draft.get("format"),
         "lane": v2_payload.get("lane"), "evergreen": bool(story.get("evergreen")), "published": published,
         "lao_job": lao_job},
        keep_days=int(bundle.v2.load_v2_config().get("ledger_days", 45)))


def digest(*, v2_payload: dict[str, Any], draft: dict[str, Any], verdict: dict[str, Any], published: bool,
           receipt: str = "", fallback: str = "") -> str:
    bundle = libs()
    if bundle is None:
        return ""
    return bundle.v2.digest(v2_payload["story"], draft, verdict, lane_label=v2_payload.get("lane_label", ""),
                            published=published, receipt=receipt, fallback=fallback)
