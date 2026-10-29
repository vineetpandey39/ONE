"""One-run, checkpoint-linked PLANEXIUM Resolve diagnostic supervisor."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

import psutil


GIB = 1024 ** 3


class PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong)] + [
        (name, ctypes.c_size_t) for name in (
            "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal",
            "PhysicalAvailable", "SystemCache", "KernelTotal", "KernelPaged",
            "KernelNonpaged", "PageSize")
    ] + [(name, ctypes.c_ulong) for name in ("HandleCount", "ProcessCount", "ThreadCount")]


def system_commit() -> tuple[int, int]:
    info = PERFORMANCE_INFORMATION()
    info.cb = ctypes.sizeof(info)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        raise OSError("GetPerformanceInfo failed")
    return info.CommitTotal * info.PageSize, info.CommitLimit * info.PageSize


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def resolve_process() -> psutil.Process:
    matches = [process for process in psutil.process_iter(["name"])
               if (process.info.get("name") or "").casefold() == "resolve.exe"]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one Resolve process, found {len(matches)}")
    return matches[0]


def telemetry(process: psutil.Process, destination: Path, project, job_id: str) -> dict:
    memory = process.memory_info()
    swap = psutil.swap_memory()
    commit_used, commit_limit = system_commit()
    status = project.GetRenderJobStatus(job_id) or {}
    pagefile = Path("C:/pagefile.sys")
    return {
        "at_epoch": time.time(), "job_id": job_id,
        "render_status": status.get("JobStatus"),
        "render_percent": status.get("CompletionPercentage", 0),
        "c_free_bytes": shutil.disk_usage("C:/").free,
        "f_free_bytes": shutil.disk_usage(destination).free,
        "pagefile_allocated_bytes": pagefile.stat().st_size,
        "pagefile_swap_total_bytes": swap.total,
        "pagefile_swap_used_bytes": swap.used,
        "pagefile_swap_free_bytes": swap.free,
        "system_commit_used_bytes": commit_used,
        "system_commit_limit_bytes": commit_limit,
        "system_commit_free_bytes": commit_limit - commit_used,
        "resolve_private_bytes": memory.private,
        "resolve_working_set_bytes": memory.rss,
    }


def alarm(sample: dict, destination_floor: int) -> str:
    if sample["c_free_bytes"] < 58 * GIB:
        return "C free space crossed the 58 GiB early-stop margin"
    if sample["f_free_bytes"] < destination_floor:
        return "F render destination crossed its reserve"
    if sample["system_commit_free_bytes"] < 8 * GIB:
        return "system commit/pagefile headroom fell below 8 GiB"
    if sample["resolve_private_bytes"] > 30 * GIB:
        return "Resolve private commitment exceeded 30 GiB"
    return ""


def close_owned(resolve, manager, project) -> None:
    if project.IsRenderingInProgress():
        project.StopRendering()
        time.sleep(2)
    if project.IsRenderingInProgress():
        raise RuntimeError("Resolve did not confirm the owned render stopped")
    if not manager.SaveProject():
        raise RuntimeError("Resolve did not confirm the owned project save")
    if not manager.CloseProject(project):
        raise RuntimeError("Resolve did not close the owned project")
    current = manager.GetCurrentProject()
    if current:
        folder = current.GetMediaPool().GetRootFolder()
        empty = (current.GetName() == "Untitled Project" and current.GetTimelineCount() == 0
                 and not folder.GetClipList() and not folder.GetSubFolderList())
        if not empty:
            raise RuntimeError("Resolve opened a non-empty unrelated project after close")
    resolve.Quit()


def run(args, _locked=False) -> int:
    root = args.mission_root.resolve()
    destination = args.destination.resolve()
    state_path = root / "edit/resolve-supervised-attempt.json"
    if state_path.exists():
        raise RuntimeError("Supervised attempt receipt already exists; reconcile it instead of retrying")
    settings = json.loads((root / "edit/resolve-settings.json").read_text(encoding="utf-8"))
    if not _locked:
        from openjarvis.one_agents.planexium_resolve import machine_lock
        with machine_lock(Path(settings["work_root"]).parent / "resolve.lock"):
            return run(args, _locked=True)
    evidence = json.loads((root / "edit/resolve-capacity-evidence.json").read_text(encoding="utf-8"))
    export = root / "edit/resolve-capacity-hold.drp"
    if sha(export) != evidence["project_export"]["sha256"]:
        raise RuntimeError("Saved project export hash changed")
    if psutil.pid_exists(args.owner_pid):
        raise RuntimeError("Previous render owner unexpectedly remains alive")
    if any((process.info.get("name") or "").casefold() == "resolve.exe"
           for process in psutil.process_iter(["name"])):
        raise RuntimeError("Resolve is already running; ownership is uncertain")

    config = json.loads(args.config.read_text(encoding="utf-8"))["resolve"]
    system_start_required = int(config["minimum_free_bytes"]) + int(config["start_headroom_bytes"])
    c_free = shutil.disk_usage("C:/").free
    # This is the explicitly approved one-run estimate exception.  It never
    # weakens the 54 GiB hard reserve or any persisted production setting.
    exception = c_free < system_start_required
    if c_free < 58 * GIB:
        raise RuntimeError("C drive lacks the supervised attempt's early-stop margin")
    destination.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(destination)
    output_budget = max(evidence["base_master"]["bytes"] * 4, GIB)
    destination_floor = max(20 * GIB, int(usage.total * .10)) + output_budget
    if usage.free < destination_floor:
        raise RuntimeError("F destination lacks its reserve plus output budget")

    os.environ["DAVINCI_RESOLVE_BRIDGE_CONFIG"] = settings["bridge_config"]
    server_root = str(Path(settings["server"]).parent.parent)
    if server_root not in sys.path:
        sys.path.insert(0, server_root)
    from openjarvis.one_agents.planexium_resolve_startup import ensure_ready
    ensure_ready(settings)
    from src.utils.resolve_bridge_client import connect
    resolve = connect(require_enabled=False, timeout=5)
    manager = resolve.GetProjectManager()
    project = manager.LoadProject(args.project)
    if not project or project.GetName() != args.project or project.IsRenderingInProgress():
        raise RuntimeError("Saved owned project could not be loaded idle")
    jobs = project.GetRenderJobList() or []
    old = next((job for job in jobs if job.get("JobId") == args.old_job), None)
    if not old or (project.GetRenderJobStatus(args.old_job) or {}).get("JobStatus") != "Cancelled":
        raise RuntimeError("Cancelled predecessor render job is unavailable")
    state = {
        "schema": "planexium-resolve-supervised-attempt-v1", "mission_id": root.name,
        "project": args.project, "predecessor_job_id": args.old_job,
        "predecessor_retained": True, "destination": str(destination),
        "system_start_required_bytes": system_start_required,
        "system_start_free_bytes": c_free, "one_run_estimate_exception": exception,
        "hard_reserve_bytes": 54 * GIB, "early_stop_bytes": 58 * GIB,
        "destination_floor_bytes": destination_floor, "phase": "submitting",
        "attempt_count": 1, "public_publish_authorized": False,
    }
    write(state_path, state)
    if not project.SetCurrentRenderFormatAndCodec("mp4", "H264"):
        raise RuntimeError("Resolve refused format/codec for the successor")
    settings_ok = project.SetRenderSettings({
        "SelectAllFrames": False, "MarkIn": int(old["MarkIn"]), "MarkOut": int(old["MarkOut"]),
        "ExportAudio": True, "ExportVideo": True, "TargetDir": str(destination),
        "CustomName": "resolve-master-successor",
    })
    if not settings_ok:
        raise RuntimeError("Resolve refused the F-target render settings")
    successor = project.AddRenderJob()
    if not successor:
        raise RuntimeError("Resolve successor submission outcome is uncertain; no retry")
    state.update(successor_job_id=successor, phase="queued")
    write(state_path, state)
    successor_row = next((job for job in (project.GetRenderJobList() or [])
                          if job.get("JobId") == successor), None)
    if (not successor_row or Path(successor_row.get("TargetDir") or "").resolve()
            != destination):
        raise RuntimeError("Resolve successor TargetDir readback did not match F destination")
    if not manager.SaveProject():
        raise RuntimeError("Resolve successor lineage was not saved")
    log_path = root / "edit/resolve-supervised-telemetry.jsonl"
    try:
        process = resolve_process()
        preflight = telemetry(process, destination, project, successor)
    except Exception:
        close_owned(resolve, manager, project)
        raise
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({**preflight, "phase": "prestart"}) + "\n")
    preflight_alarm = alarm(preflight, destination_floor)
    if preflight_alarm:
        state.update(phase="held", outcome=preflight_alarm, project_saved=True)
        write(state_path, state)
        close_owned(resolve, manager, project)
        return 2
    outcome = "start outcome uncertain"
    started = False
    try:
        if not project.StartRendering([successor], False):
            raise RuntimeError("Resolve refused the exact successor start; no retry")
        started = True
        state["phase"] = "rendering"; write(state_path, state)
        while True:
            try:
                sample = telemetry(process, destination, project, successor)
                with log_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(sample) + "\n")
            except Exception as exc:
                outcome = f"telemetry unavailable: {type(exc).__name__}"
                break
            status = sample["render_status"]
            if status == "Complete":
                outcome = "complete"
                break
            if status not in {"Rendering", "Ready"}:
                outcome = f"unexpected render status: {status}"
                break
            outcome = alarm(sample, destination_floor)
            if outcome:
                break
            time.sleep(5)
    finally:
        if started and outcome != "complete" and project.IsRenderingInProgress():
            project.StopRendering(); time.sleep(2)
        saved = bool(manager.SaveProject())
        final_status = project.GetRenderJobStatus(successor) or {}
        state.update(phase="complete" if outcome == "complete" else "held",
                     outcome=outcome, final_status=final_status, project_saved=saved)
        write(state_path, state)
        if not saved or (outcome != "complete" and project.IsRenderingInProgress()):
            raise RuntimeError("Supervisor could not verify safe owned-project hold")
        manager.ExportProject(args.project, str(root / "edit/resolve-supervised-attempt.drp"))
        close_owned(resolve, manager, project)
    return 0 if outcome == "complete" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mission-root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--old-job", required=True)
    parser.add_argument("--owner-pid", type=int, required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
