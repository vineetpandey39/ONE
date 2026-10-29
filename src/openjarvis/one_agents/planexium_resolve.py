"""Mission-owned Resolve/Fusion finishing. No publishing or silent fallback.

The worker invokes this file with the installed MCP virtual environment. The
stdio client talks to the real Resolve bridge; secrets remain in its own config.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Progress is written by a parent process while Resolve reports through a
    # child.  A shared ``render-progress.tmp`` makes concurrent/retried jobs
    # overwrite one another, and Windows indexers/readers may briefly deny the
    # final replace.  Give every write its own sibling and retry only that
    # bounded transient condition.
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
        for attempt in range(8):
            try:
                os.replace(temp, path)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        temp.unlink(missing_ok=True)


def isolated_environment(settings):
    # ONE may inject its own PYTHONPATH and HOME for its worker. Neither those
    # Python packages nor its credentials belong in the Resolve MCP process.
    allowed = {"SYSTEMROOT","SYSTEMDRIVE","WINDIR","TEMP","TMP","PATH","USERPROFILE","APPDATA",
               "LOCALAPPDATA","PROGRAMDATA","COMSPEC","PATHEXT","USERNAME","USERDOMAIN",
               "ALLUSERSPROFILE", "USERDOMAIN_ROAMINGPROFILE", "PROGRAMFILES",
               "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES",
               "COMMONPROGRAMFILES(X86)", "COMMONPROGRAMW6432", "OS",
               "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER",
               "PROCESSOR_LEVEL", "PROCESSOR_REVISION", "COMPUTERNAME", "SESSIONNAME",
               "PUBLIC", "DRIVERDATA", "LOGONSERVER"}
    env = {k:v for k,v in os.environ.items() if k.upper() in allowed}
    env.update(DAVINCI_RESOLVE_BRIDGE="1", PYTHONUTF8="1")
    if settings.get("bridge_config"):
        env["DAVINCI_RESOLVE_BRIDGE_CONFIG"] = settings["bridge_config"]
    return env


def capacity_state(request, directory):
    """Measure system/pagefile and render-destination capacity independently."""
    system_path = Path(request.get("system_reserve_path") or directory)
    destination_path = Path(request.get("destination_reserve_path") or directory)
    system = shutil.disk_usage(system_path)
    destination = shutil.disk_usage(destination_path)
    destination_floor = max(
        int(request.get("destination_minimum_free_bytes") or 0),
        int(destination.total * float(request.get("destination_minimum_free_fraction") or 0)),
    ) + int(request.get("estimated_remaining_output_bytes") or 0)
    state = {
        "system_path": str(system_path), "system_free_bytes": system.free,
        "system_minimum_free_bytes": int(request.get("minimum_free_bytes") or 0),
        "destination_path": str(destination_path),
        "destination_free_bytes": destination.free,
        "destination_minimum_free_bytes": destination_floor,
    }
    minimum_commit = int(request.get("minimum_commit_headroom_bytes") or 0)
    if minimum_commit:
        import ctypes
        from ctypes import wintypes
        class PerformanceInformation(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in (
                "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal",
                "PhysicalAvailable", "SystemCache", "KernelTotal", "KernelPaged",
                "KernelNonpaged", "PageSize")] + [(name, wintypes.DWORD) for name in (
                "HandleCount", "ProcessCount", "ThreadCount")]
        info = PerformanceInformation()
        info.cb = ctypes.sizeof(info)
        if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
            raise OSError("GetPerformanceInfo failed")
        state.update(commit_free_bytes=(info.CommitLimit-info.CommitTotal)*info.PageSize,
                     minimum_commit_headroom_bytes=minimum_commit)
    return state


def capacity_block(state, *, start_headroom=0):
    required = state["system_minimum_free_bytes"] + int(start_headroom)
    if required and state["system_free_bytes"] < required:
        return (f"system/pagefile reserve: {state['system_free_bytes']} free bytes is below "
                f"{required} required")
    if (state["destination_minimum_free_bytes"]
            and state["destination_free_bytes"] < state["destination_minimum_free_bytes"]):
        return (f"render destination reserve: {state['destination_free_bytes']} free bytes is below "
                f"{state['destination_minimum_free_bytes']} required")
    if (state.get("minimum_commit_headroom_bytes")
            and state.get("commit_free_bytes", 0) < state["minimum_commit_headroom_bytes"]):
        return (f"system commit reserve: {state.get('commit_free_bytes', 0)} free bytes is below "
                f"{state['minimum_commit_headroom_bytes']} required")
    return ""


def probe(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams",
        "-show_format", "-of", "json", str(path)], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def validate_output(path, frames, *, require_audio=True):
    data = probe(path)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    if ((video["width"], video["height"]) != (1920, 1080)
            or video["avg_frame_rate"] != "30/1"
            or int(video["nb_frames"]) != frames or (require_audio and audio is None)
            or abs(float(data["format"]["duration"]) - frames / 30) > .15):
        raise RuntimeError("Resolve output failed resolution/frame/audio/duration validation")
    return data


# These are typography layouts, not asserted scientific geometry.
LAYOUTS = {
    "travel-dossier": (.28, .22, .043, (.51, .83, .89)),
    "cinematic-clean": (.50, .22, .048, (.94, .95, 1)),
    "editorial-punch": (.30, .70, .052, (1, .75, .43)),
    "kinetic-type": (.50, .27, .060, (1, .92, .74)),
    "motion-lab": (.70, .23, .041, (.49, .87, .95)),
}


def composition(picture, frames, shots, family, *, allow_identity=False):
    """Native titles plus a narration-bound, qualitative moon-origin diagram."""
    if family not in LAYOUTS or frames < 1:
        raise ValueError("Known weekday format and positive frame budget required")
    nodes = []
    def inp(key, value=None, expr=None, source=None, mask=False):
        if source:
            return f'{key}=Input{{SourceOp="{source}",Source="{"Mask" if mask else "Output"}"}},'
        if expr is not None:
            return f"{key}=Input{{Expression={json.dumps(expr)}}},"
        return f"{key}=Input{{Value={json.dumps(value)}}},"
    def node(name, kind, inputs):
        nodes.append(f'{name}={kind}{{Inputs={{{"".join(inputs)}}}}},')
    filename = json.dumps(Path(picture).as_posix())
    nodes.append(f'''Source=Loader{{Clips={{Clip{{ID="Clip1",Filename={filename},
        FormatID="QuickTimeMovies",StartFrame=0,Length={frames},LengthSetManually=true,
        TrimIn=0,TrimOut={frames-1},GlobalStart=0,GlobalEnd={frames-1}}}}},
        Inputs={{ClipTimeStart=Input{{Value=0}},ClipTimeEnd=Input{{Value={frames-1}}},
        GlobalIn=Input{{Value=0}},GlobalOut=Input{{Value={frames-1}}},Loop=Input{{Value=0}}}}}},''')
    last = "Source"
    def merge(name, expression):
        nonlocal last
        merged = f"Merge{len(nodes)}"
        node(merged, "Merge", [inp("Background", source=last), inp("Foreground", source=name),
                               inp("Blend", expr=expression)])
        last = merged
    dimensions = [inp("UseFrameFormatSettings", 0), inp("Width", 1920), inp("Height", 1080)]
    x, y, size, color = LAYOUTS[family]
    beats = []
    for index, shot in enumerate(shots):
        if shot.get("fusion_diagram") == "moon_origins" and shot["kind"] != "primary":
            import math
            start, count = int(shot["start_frame"]), int(shot["frames"])
            end = start + count
            if start < 0 or end > frames or count < 120:
                raise ValueError("Origin diagram needs a valid four-second shot")
            gate = f"iif(time>={start} and time<{end},min(1,max(0,(time-{start})/12))*min(1,max(0,({end}-time)/12)),0)"
            prefix = f"Origins{index}"
            node(prefix+"PanelMask", "RectangleMask", [
                inp("MaskWidth", 1920), inp("MaskHeight", 1080),
                inp("Center", expr="Point(.5,.5)"), inp("Width", .9), inp("Height", .68)])
            node(prefix+"Panel", "Background", dimensions + [
                inp("TopLeftRed", .015), inp("TopLeftGreen", .03), inp("TopLeftBlue", .05),
                inp("TopLeftAlpha", .94), inp("EffectMask", source=prefix+"PanelMask", mask=True)])
            merge(prefix+"Panel", gate)
            def disk(suffix, cx, cy, width, height, rgb, border=0):
                name = prefix+suffix
                node(name+"Mask", "EllipseMask", [
                    inp("MaskWidth", 1920), inp("MaskHeight", 1080),
                    inp("Center", expr=f"Point({cx},{cy})"), inp("Width", width), inp("Height", height),
                    inp("Solid", 0 if border else 1), inp("BorderWidth", border), inp("SoftEdge", .002)])
                node(name, "Background", dimensions + [
                    inp("TopLeftRed", rgb[0]), inp("TopLeftGreen", rgb[1]), inp("TopLeftBlue", rgb[2]),
                    inp("EffectMask", source=name+"Mask", mask=True)])
                merge(name, gate)
            for side, cx in [("Left", .28), ("Right", .72)]:
                disk(side+"Orbit", cx, .51, .32, .22, (.3,.5,.6), .0015)
                disk(side+"Mars", cx, .51, .115, .115, (.8,.27,.1))
                node(prefix+side+"Label", "TextPlus", dimensions + [
                    inp("StyledText", "CAPTURED ASTEROID?" if side == "Left" else "IMPACT DEBRIS?"),
                    inp("Font", "Bahnschrift"), inp("Style", "Regular"), inp("Size", .029),
                    inp("Center", expr=f"Point({cx},.28)")])
                merge(prefix+side+"Label", gate)
            disk("Moon", f".28+.16*cos((time-{start})*.026)",
                 f".51+.11*sin((time-{start})*.026)", .014, .014, (.7,.88,.94))
            for i in range(16):
                theta = i*2*math.pi/16
                disk(f"Debris{i}", f".72+(.07+.09*min(1,max(0,(time-{start})/{count*.7})))*cos({theta}+(time-{start})*.012)",
                     f".51+(.05+.06*min(1,max(0,(time-{start})/{count*.7})))*sin({theta}+(time-{start})*.012)",
                     .004, .004, (1,.65,.3))
            beats.append({"start_frame":start, "frames":count, "diagram":"moon_origins",
                          "meaning":"Qualitative competing hypotheses, not simulated orbital measurements"})
        text = str(shot.get("callout") or "").strip()
        if not text or shot["kind"] == "primary" or shot.get("science_overlay"):
            continue
        start, count = int(shot["start_frame"]), int(shot["frames"])
        end = start + count
        if start < 0 or end > frames or count < 15:
            raise ValueError("Fusion beat exceeds measured picture")
        # Keep director-authored copy intact, wrapped for a mobile-readable plate.
        import textwrap
        lines = textwrap.wrap(text, 24)
        if len(lines) > 3:
            raise ValueError("Fusion title exceeds three readable lines; repair director copy")
        fade = f"iif(time>={start} and time<{end},min(1,max(0,(time-{start})/10))*min(1,max(0,({end}-time)/10)),0)"
        move = f"Point({x},{y}-.025*max(0,1-(time-{start})/16))"
        prefix = f"Beat{index}"
        node(prefix+"Mask", "RectangleMask", [
            inp("MaskWidth", 1920), inp("MaskHeight", 1080),
            inp("Center", expr=move), inp("Width", .58), inp("Height", .08+.06*len(lines)),
            inp("CornerRadius", .025), inp("SoftEdge", .005)])
        node(prefix+"Plate", "Background", dimensions + [
            inp("TopLeftRed", .015), inp("TopLeftGreen", .025), inp("TopLeftBlue", .045),
            inp("TopLeftAlpha", .78), inp("EffectMask", source=prefix+"Mask", mask=True)])
        merge(prefix+"Plate", fade)
        node(prefix+"Text", "TextPlus", dimensions + [
            inp("StyledText", "\n".join(lines)), inp("Font", "Bahnschrift"),
            inp("Style", "Regular"), inp("Size", size), inp("Center", expr=move),
            inp("Red1", color[0]), inp("Green1", color[1]), inp("Blue1", color[2])])
        merge(prefix+"Text", fade)
        node(prefix+"RuleMask", "RectangleMask", [
            inp("MaskWidth", 1920), inp("MaskHeight", 1080),
            inp("Center", expr=f"Point({x},{y-.055-.03*len(lines)})"),
            inp("Width", expr=f".40*min(1,max(0,(time-{start})/20))"), inp("Height", .0025)])
        node(prefix+"Rule", "Background", dimensions + [
            inp("TopLeftRed", color[0]), inp("TopLeftGreen", color[1]), inp("TopLeftBlue", color[2]),
            inp("EffectMask", source=prefix+"RuleMask", mask=True)])
        merge(prefix+"Rule", fade)
        beats.append({"start_frame": start, "frames": count, "text": text, "format": family})
    if not beats and not allow_identity:
        raise ValueError("No eligible director beats for native Fusion; no fake success")
    node("MediaOut1", "MediaOut", [inp("Index", 0), inp("Input", source=last)])
    return (f"Composition{{GlobalStart=0,GlobalEnd={frames-1},RenderStart=0,RenderEnd={frames-1},"
            "Tools=ordered(){"+ "\n".join(nodes) + "}}"), beats


def scene_partitions(shots, frames):
    """Return exact, gap-free scene ranges in the global picture timebase."""
    ordered = sorted(shots, key=lambda row: int(row["start_frame"]))
    if not ordered or int(ordered[0]["start_frame"]) != 0:
        raise ValueError("Segmented Resolve requires picture coverage from frame zero")
    partitions = []
    cursor = 0
    for scene in sorted({int(row["scene"]) for row in ordered}):
        rows = [row for row in ordered if int(row["scene"]) == scene]
        start = int(rows[0]["start_frame"])
        if start != cursor:
            raise ValueError("Segmented Resolve scene ranges contain a gap or overlap")
        for row in rows:
            if int(row["start_frame"]) != cursor:
                raise ValueError("Segmented Resolve shots are not contiguous")
            cursor += int(row["frames"])
        partitions.append({"scene": scene, "start_frame": start,
                           "frames": cursor-start, "shots": rows})
    if cursor != int(frames):
        raise ValueError("Segmented Resolve ranges do not cover the measured picture")
    return partitions


def resolve_lock_path(request):
    """All PLANEXIUM Resolve modes share one machine-level ownership lock."""
    explicit = request.get("machine_lock_path")
    return Path(explicit) if explicit else Path(request["directory"]).parent/"resolve.lock"


@contextmanager
def machine_lock(path):
    """OS releases this lock even if a worker dies. Never delete another lease."""
    import msvcrt
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"\0"); handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("Resolve is owned by another PLANEXIUM finishing job") from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class MCP:
    def __init__(self, session, events):
        self.session, self.events = session, Path(events)

    async def call(self, tool, action, **params):
        reply = await self.session.call_tool(tool, {"action": action, "params": params})
        data = reply.structuredContent
        if data is None:
            data = json.loads(next(c.text for c in reply.content if c.type == "text"))
        if isinstance(data, dict) and "result" in data:
            data = data["result"]
        ok = (isinstance(data, dict) and not reply.isError and not data.get("error")
              and data.get("success") is not False
              and data.get("_operation", {}).get("status") not in {"failed", "error", "blocked"})
        with self.events.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"at": time.time(), "tool": tool, "action": action, "ok": ok})+"\n")
        if not ok:
            # Do not propagate opaque MCP objects, credentials or arbitrary tool dumps.
            raise RuntimeError(f"Resolve MCP rejected {tool}.{action}; checkpoint retained")
        return data


async def execute(request, client):
    directory = Path(request["directory"])
    state_path = directory/"owner.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    project = request["project"]
    await client.call("resolve_control", "get_version")
    current = await client.call("project_manager", "get_current")
    rendering = (await client.call("render", "is_rendering"))["rendering"]
    if rendering and (current.get("name") != project or not state.get("job_id")):
        raise RuntimeError("Resolve is rendering another or unowned job; left untouched")
    if current.get("name") and current["name"] != project:
        if not current["name"].startswith("PLANEXIUM_"):
            raise RuntimeError("Resolve has another user's project open; left untouched")
        await client.call("project_manager", "save")
    if state.get("phase") == "submitting" and not state.get("job_id"):
        raise RuntimeError("Render submission outcome uncertain; inspect queue before any new submission")
    if current.get("name") != project:
        if state.get("created"):
            await client.call("project_manager", "load", name=project)
        else:
            # State before creation makes a partial transaction diagnosable.
            write(state_path, {**state, "phase": "creating", "project": project})
            await client.call("project_manager", "create", name=project)
            state.update(created=True, project=project)
            write(state_path, state)
    if not state.get("job_id"):
        if state.get("phase") in {"creating", "assembling"}:
            # A transient Resolve API refusal can occur immediately after a
            # project is created.  Resume only when live MCP evidence proves
            # that assembly never crossed either duplicate-producing boundary:
            # no timeline and no imported media.  Anything else remains
            # fail-closed for manual reconciliation.
            summary = await client.call("project_settings", "project_summary",
                                        include_clips=True, clip_limit=1)
            pool = summary.get("media_pool") or {}
            if int(summary.get("timeline_count") or 0) != 0 or int(pool.get("clip_count") or 0) != 0:
                raise RuntimeError("Partial project assembly needs reconciliation; no duplicate timeline created")
            state["phase"] = "created"
            write(state_path, state)
        state.update(created=True, phase="assembling")
        write(state_path, state)
        for key, value in [("timelineFrameRate", "30"), ("timelineResolutionWidth", "1920"),
                           ("timelineResolutionHeight", "1080")]:
            await client.call("project_settings", "set_setting", name=key, value=value)
        await client.call("media_pool", "import_media", paths=[request["picture"]])
        clips = (await client.call("folder", "get_clips"))["clips"]
        clip = next(c for c in clips if c["name"] == Path(request["picture"]).name)
        await client.call("media_pool", "create_timeline_from_clips",
                          name="PLANEXIUM Final", clip_ids=[clip["id"]])
        await client.call("timeline_item_fusion", "import_comp", path=request["composition"])
        names = await client.call("timeline_item_fusion", "get_comp_names")
        comp_names = names.get("names") or names.get("comps") or names.get("comp_names")
        if not comp_names:
            raise RuntimeError("Imported Fusion composition is not visible")
        await client.call("timeline_item_fusion", "load_comp", name=comp_names[-1])
        target = {"track_type": "video", "track_index": 1, "item_index": 0}
        # Resolve 21.0.3 may silently apply a 1000-frame Loader window on import.
        for key, value in [("ClipTimeStart", 0), ("ClipTimeEnd", request["frames"]-1),
                           ("GlobalIn", 0), ("GlobalOut", request["frames"]-1), ("Loop", 0)]:
            await client.call("fusion_comp", "set_input", timeline_item=target,
                              tool_name="Source", input_name=key, value=value)
        start = await client.call("fusion_comp", "get_input", timeline_item=target,
                                  tool_name="Source", input_name="ClipTimeStart")
        if float(start["value"] or 0) != 0:
            raise RuntimeError("Fusion source trim readback failed")
        await client.call("project_manager", "save")
        await client.call("render", "set_mode", mode=1)
        await client.call("render", "set_format_and_codec", format="mp4", codec="H264")
        timeline = await client.call("timeline", "get_current")
        timeline_start = int(timeline["start_frame"])
        segment_start = int(request.get("segment_start_frame") or 0)
        segment_frames = int(request.get("segment_frames") or request["frames"])
        await client.call("render", "set_settings", settings={
            "SelectAllFrames": False, "MarkIn": timeline_start+segment_start,
            "MarkOut": timeline_start+segment_start+segment_frames-1,
            "ExportAudio": bool(request.get("export_audio", True)), "ExportVideo": True,
            "TargetDir": str(directory),
            "CustomName": str(request.get("custom_name") or "resolve-master")})
        state["phase"] = "submitting"; write(state_path, state)
        state["job_id"] = (await client.call("render", "add_job"))["job_id"]
        state["phase"] = "queued"; write(state_path, state)
    start_headroom = int(request.get("start_headroom_bytes") or 0)
    try:
        capacity = capacity_state(request, directory)
    except OSError as exc:
        raise RuntimeError("Resolve capacity hold before render start: capacity telemetry unavailable") from exc
    blocked = capacity_block(capacity, start_headroom=start_headroom)
    if blocked:
        raise RuntimeError(f"Resolve capacity hold before render start: {blocked}")
    status = await client.call("render", "get_job_status", job_id=state["job_id"])
    if status["JobStatus"] in {"Ready", "Cancelled"}:
        await client.call("render", "start", job_ids=[state["job_id"]], interactive=False)
    deadline = time.monotonic()+request.get("timeout", 14400)
    while True:
        status = await client.call("render", "get_job_status", job_id=state["job_id"])
        write(directory/"progress.json", {"status": status["JobStatus"],
            "percent": status.get("CompletionPercentage", 0), "job_id": state["job_id"]})
        if status["JobStatus"] == "Complete":
            break
        if status["JobStatus"] not in {"Rendering", "Ready"}:
            raise RuntimeError("Resolve job failed/stopped; retained its exact job ID")
        try:
            capacity = capacity_state(request, directory)
            blocked = capacity_block(capacity)
        except OSError as exc:
            capacity = {"telemetry_error": type(exc).__name__}
            blocked = "capacity telemetry unavailable during owned render"
        if blocked:
            await client.call("render", "stop")
            stopped = await client.call("render", "is_rendering")
            saved = await client.call("project_manager", "save")
            write(directory / "capacity-hold.json", {
                "schema": "planexium-resolve-capacity-hold-v1",
                "job_id": state["job_id"], **capacity, "reason": blocked,
                "rendering_after_stop": stopped["rendering"],
                "project_saved": bool(saved.get("success")),
            })
            if stopped["rendering"]:
                raise RuntimeError("Resolve capacity hold could not verify a safe stop")
            if not saved.get("success"):
                raise RuntimeError("Resolve capacity hold could not verify the owned project save")
            raise RuntimeError(f"Resolve capacity hold stopped the owned render: {blocked}")
        if time.monotonic() > deadline:
            raise TimeoutError("Resolve job still in flight; resume this job, never duplicate it")
        await asyncio.sleep(5)
    await client.call("project_manager", "save")
    await client.call("project_manager", "export_project", name=project,
                      path=str(directory/"project.drp"))
    state["phase"] = "rendered"; write(state_path, state)


async def release_owned(request, client):
    """Save and release only the project named by this segment request."""
    current = await client.call("project_manager", "get_current")
    if current.get("name") != request["project"]:
        raise RuntimeError("Resolve segment release refused an unexpected current project")
    await client.call("project_manager", "save")
    closed = await client.call("project_manager", "close")
    if closed.get("success") is False:
        raise RuntimeError("Resolve did not verify the owned segment project close")
    await client.call("resolve_control", "quit")
    await asyncio.to_thread(wait_for_resolve_exit)


def wait_for_resolve_exit(timeout=90):
    """Do not let a following segment race an acknowledged-but-live Resolve."""
    import psutil
    deadline = time.monotonic()+timeout
    while any((process.info.get("name") or "").casefold() == "resolve.exe"
              for process in psutil.process_iter(["name"])):
        if time.monotonic() > deadline:
            raise RuntimeError("Resolve quit was acknowledged but process exit was not verified")
        time.sleep(.5)


async def release_owned_if_idle(request, client):
    """Best-effort failure cleanup; never close an active or foreign project."""
    current = await client.call("project_manager", "get_current")
    if current.get("name") != request["project"]:
        return False
    if (await client.call("render", "is_rendering"))["rendering"]:
        return False
    await client.call("project_manager", "save")
    await client.call("project_manager", "close")
    await client.call("resolve_control", "quit")
    await asyncio.to_thread(wait_for_resolve_exit)
    return True


async def worker(request):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    server = Path(request["server"])
    params = StdioServerParameters(command=request["python"], args=[str(server)],
        cwd=str(server.parent.parent),
        env=isolated_environment(request))
    with machine_lock(resolve_lock_path(request)):
        # This module is also executed as a file by the isolated MCP Python.
        if __package__:
            from .planexium_resolve_startup import ensure_ready
        else:
            from planexium_resolve_startup import ensure_ready
        await asyncio.to_thread(ensure_ready, request)
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                client = MCP(session, Path(request["directory"])/"mcp-events.jsonl")
                if request.get("preflight"):
                    await client.call("resolve_control", "get_version")
                    current = await client.call("project_manager", "get_current")
                    if current.get("name") and not current["name"].startswith("PLANEXIUM_"):
                        raise RuntimeError("Another Resolve project is open; leave it untouched")
                else:
                    try:
                        await execute(request, client)
                    except BaseException:
                        if request.get("release_after"):
                            try:
                                released = await release_owned_if_idle(request, client)
                                write(Path(request["directory"])/"release.json",
                                      {"released_after_failure":released})
                            except Exception as release_error:
                                write(Path(request["directory"])/"release.json",
                                      {"released_after_failure":False,
                                       "error":type(release_error).__name__})
                        raise
                    if request.get("release_after"):
                        await release_owned(request, client)


def preflight(root, settings):
    """Recover a closed Resolve, then verify MCP before expensive preparation."""
    directory = Path(settings["work_root"])/"preflight"
    directory.mkdir(parents=True, exist_ok=True)
    request = {**settings, "directory": str(directory), "preflight": True}
    path = directory/"request.json"
    write(path, request)
    with (Path(root)/"edit/resolve-preflight.log").open("a", encoding="utf-8") as log:
        result = subprocess.run([settings["python"], str(Path(__file__).resolve()), str(path)],
            stdout=log, stderr=subprocess.STDOUT, timeout=300, env=isolated_environment(settings))
    if result.returncode:
        raise RuntimeError("Resolve startup/preflight blocked; inspect startup-health.json and resume the mission")


def _run_segment_worker(python, request_path, log_path, progress_path, root, scene):
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    with Path(log_path).open("a", encoding="utf-8") as log:
        child = subprocess.Popen([str(python), str(Path(__file__).resolve()), str(request_path)],
                                 stdout=log, stderr=subprocess.STDOUT,
                                 env=isolated_environment(request))
        while child.poll() is None:
            detail_path = Path(request["directory"])/"progress.json"
            detail = json.loads(detail_path.read_text()) if detail_path.exists() else {"status":"connecting"}
            write(progress_path, {"status":"resolve_fusion_segment", "scene":scene,
                "detail":f"Resolve/Fusion scene {scene}: {detail['status']} ({detail.get('percent',0)}%)"})
            time.sleep(3)
        if child.returncode:
            raise RuntimeError(f"Resolve/Fusion scene {scene} blocked; exact segment receipt retained")


def _video_signature(path):
    video = next(s for s in probe(path)["streams"] if s["codec_type"] == "video")
    return {key: video.get(key) for key in (
        "codec_name", "codec_tag_string", "profile", "width", "height", "pix_fmt", "level",
        "avg_frame_rate", "time_base", "color_range", "color_space", "color_transfer",
        "color_primaries", "extradata_size")}


def segment_seed_valid(seed, picture, composition_path, start, frames):
    source = Path(seed.get("output") or "")
    proof_comp = source.with_name("PLANEXIUM.comp")
    proof_picture = source.with_name("prepared.mp4")
    composition_matches = seed.get("composition_sha256") == sha(composition_path)
    if (not composition_matches and proof_comp.is_file() and proof_picture.is_file()
            and seed.get("composition_sha256") == sha(proof_comp)
            and seed.get("source_sha256") == sha(proof_picture)):
        composition_matches = (_canonical_seed_comp(proof_comp, proof_picture)
                               == _canonical_seed_comp(composition_path, picture))
    return (seed.get("source_sha256") == sha(picture)
        and int(seed.get("start_frame", -1)) == int(start)
        and int(seed.get("frames", -1)) == int(frames)
        and composition_matches
        and source.is_file() and seed.get("output_sha256") == sha(source))


def _canonical_seed_comp(comp_path, picture_path):
    text = Path(comp_path).read_text(encoding="utf-8").replace("\r\n", "\n")
    source = Path(picture_path).as_posix()
    if source not in text:
        raise ValueError("Composition does not bind its verified source picture")
    text = text.replace(source, "VERIFIED_SOURCE")
    # Preserve graph topology with a one-to-one definition-order mapping. Only
    # tool definitions and SourceOp references are rewritten; free text,
    # expressions and timing numbers remain byte-significant.
    token = r'(?:Beat\d+(?:RuleMask|Mask|Plate|Text|Rule)|Merge\d+)'
    definitions = re.findall(rf'({token})=', text)
    if len(definitions) != len(set(definitions)):
        raise ValueError("Composition contains duplicate tool identifiers")
    mapping = {name: f"Tool{index:03d}" for index, name in enumerate(definitions)}
    references = re.findall(rf'SourceOp="({token})"', text)
    if any(name not in mapping for name in references):
        raise ValueError("Composition contains an unresolved SourceOp reference")
    text = re.sub(rf'({token})=', lambda m: mapping[m.group(1)] + "=", text)
    return re.sub(rf'SourceOp="({token})"',
                  lambda m: f'SourceOp="{mapping[m.group(1)]}"', text)


def finish_segmented(root, settings, shots, family):
    """Render scene-filtered Fusion projects sequentially, then mux audio once."""
    required = ("minimum_free_bytes", "system_reserve_path",
                "destination_minimum_free_bytes", "destination_minimum_free_fraction",
                "minimum_commit_headroom_bytes", "segmented_work_root",
                "segmented_output_reserve_bytes", "final_copy_reserve_bytes")
    missing = [key for key in required if settings.get(key) in (None, "")]
    if missing:
        raise RuntimeError("Segmented Resolve guard configuration is incomplete: "+", ".join(missing))
    root, work = Path(root), Path(root)/"edit"
    picture, soundtrack = work/"master.mp4", work/"soundtrack.m4a"
    data = probe(picture)
    frames = int(next(s for s in data["streams"] if s["codec_type"] == "video")["nb_frames"])
    partitions = scene_partitions(shots, frames)
    server, python = Path(settings["server"]), Path(settings["python"])
    if not server.is_file() or not python.is_file() or not soundtrack.is_file():
        raise RuntimeError("Segmented Resolve inputs are incomplete; no fallback")
    signature = hashlib.sha256(json.dumps({"picture":sha(picture), "shots":shots,
        "family":family, "code":sha(__file__), "server":sha(server), "mode":"scene-filtered-v1"},
        sort_keys=True).encode()).hexdigest()
    base = Path(settings["segmented_work_root"])/signature[:20]
    base.mkdir(parents=True, exist_ok=True)
    prepared = base/"prepared.mp4"
    if not prepared.exists(): shutil.copy2(picture, prepared)
    if sha(prepared) != sha(picture):
        raise RuntimeError("Segmented Resolve staging integrity mismatch")
    seed_path = work/"resolve-segment-seeds.json"
    seeds = json.loads(seed_path.read_text(encoding="utf-8")).get("segments", []) if seed_path.exists() else []
    outputs, all_beats, receipts = [], [], []
    for part in partitions:
        scene, start, count = part["scene"], part["start_frame"], part["frames"]
        directory = base/f"scene-{scene:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        output = directory/f"scene-{scene:02d}.mp4"
        receipt_path = directory/"segment-receipt.json"
        prior = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
        if (output.exists() and prior.get("signature") == signature
                and prior.get("sha256") == sha(output) and prior.get("frames") == count):
            outputs.append(output); all_beats.extend(prior.get("beats") or []); receipts.append(prior)
            continue
        comp, beats = composition(prepared, frames, part["shots"], family, allow_identity=True)
        comp_path = directory/"PLANEXIUM.comp"
        comp_path.write_text(comp, encoding="utf-8")
        seed = next((row for row in seeds if int(row.get("scene", -1)) == scene), None)
        if seed:
            source = Path(seed["output"])
            if not segment_seed_valid(seed, prepared, comp_path, start, count):
                raise RuntimeError(f"Resolve seed lineage mismatch for scene {scene}; no implicit rerender")
            validate_output(source, count, require_audio=False)
            shutil.copy2(source, output)
            row = {"schema":"planexium-resolve-segment-v1", "signature":signature,
                   "scene":scene, "start_frame":start, "frames":count, "sha256":sha(output),
                   "beats":beats, "identity":not bool(beats), "seeded":True,
                   "seed_receipt":str(seed_path)}
            write(receipt_path, row)
            outputs.append(output); all_beats.extend(beats); receipts.append(row)
            continue
        request = {"directory":str(directory), "picture":str(prepared),
            "composition":str(comp_path), "frames":frames, "segment_start_frame":start,
            "segment_frames":count, "custom_name":output.stem, "export_audio":False,
            "release_after":True, "project":f"PLANEXIUM_{signature[:12]}_S{scene:02d}",
            "machine_lock_path":str(Path(settings["work_root"])/"resolve.lock"),
            "server":str(server), "python":str(python), "timeout":settings.get("timeout",14400),
            "minimum_free_bytes":settings["minimum_free_bytes"],
            "start_headroom_bytes":settings.get("segmented_start_headroom_bytes",
                                                  settings.get("start_headroom_bytes",0)),
            "minimum_commit_headroom_bytes":settings["minimum_commit_headroom_bytes"],
            "system_reserve_path":settings["system_reserve_path"],
            "destination_reserve_path":str(base),
            "destination_minimum_free_bytes":settings["destination_minimum_free_bytes"],
            "destination_minimum_free_fraction":settings["destination_minimum_free_fraction"],
            "estimated_remaining_output_bytes":max(
                int(picture.stat().st_size*count/frames*2),
                int(settings["segmented_output_reserve_bytes"]))}
        for optional in ("bridge_config", "autostart", "work_root"):
            if settings.get(optional) is not None: request[optional] = settings[optional]
        request_path = directory/"request.json"; write(request_path, request)
        _run_segment_worker(python, request_path, work/"resolve-segmented.log",
                            work/"render-progress.json", root, scene)
        validate_output(output, count, require_audio=False)
        row = {"schema":"planexium-resolve-segment-v1", "signature":signature,
               "scene":scene, "start_frame":start, "frames":count, "sha256":sha(output),
               "beats":beats, "identity":not bool(beats),
               "job_id":json.loads((directory/"owner.json").read_text())["job_id"]}
        write(receipt_path, row)
        outputs.append(output); all_beats.extend(beats); receipts.append(row)
    signatures = [_video_signature(path) for path in outputs]
    if len({json.dumps(row, sort_keys=True) for row in signatures}) != 1:
        raise RuntimeError("Resolve segments are not stream-copy compatible; retained without re-encode")
    assembly_need = picture.stat().st_size*2 + int(settings["segmented_output_reserve_bytes"])
    if shutil.disk_usage(base).free < assembly_need:
        raise RuntimeError("Segmented Resolve assembly capacity hold; segment outputs retained")
    listing = base/"concat.txt"
    listing.write_text("\n".join("file '"+p.as_posix().replace("'","'\\''")+"'" for p in outputs),
                       encoding="utf-8")
    video = base/"segmented-video.mp4"
    subprocess.run(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",str(listing),
                    "-c","copy",str(video)], check=True)
    validate_output(video, frames, require_audio=False)
    assembled = base/"resolve-master.mp4"
    subprocess.run(["ffmpeg","-y","-v","error","-i",str(video),"-i",str(soundtrack),
                    "-map","0:v:0","-map","1:a:0","-c","copy","-frames:v",str(frames),
                    "-movflags","+faststart",str(assembled)], check=True)
    validate_output(assembled, frames)
    final_need = assembled.stat().st_size + int(settings["final_copy_reserve_bytes"])
    if shutil.disk_usage(work).free < final_need:
        raise RuntimeError("Segmented Resolve final-copy capacity hold; assembled master retained")
    destination = work/"resolve-master.mp4"; shutil.copy2(assembled, destination)
    destination.replace(picture)
    receipt_dir = work/"resolve-segments"; receipt_dir.mkdir(exist_ok=True)
    for path in base.glob("scene-*/project.drp"):
        shutil.copy2(path, receipt_dir/f"{path.parent.name}.drp")
    write(work/"resolve-receipt.json", {"backend":"resolve_fusion_segmented",
        "signature":signature, "master_sha256":sha(picture), "frames":frames,
        "segments":receipts, "native_fusion_beats":all_beats,
        "weekday_format":family, "public_publish_authorized":False})


def finish(root, settings, shots, family):
    """Called inside the existing owned render child, before final whole-file QC."""
    if settings.get("segmented"):
        return finish_segmented(root, settings, shots, family)
    root = Path(root)
    work = root/"edit"
    picture = work/"master.mp4"
    data = probe(picture)
    frames = int(next(s for s in data["streams"] if s["codec_type"] == "video")["nb_frames"])
    server, python = Path(settings["server"]), Path(settings["python"])
    if not server.is_file() or not python.is_file():
        raise RuntimeError("Configured Resolve MCP installation is unavailable; no fallback")
    signature = hashlib.sha256(json.dumps({"picture": sha(picture), "shots": shots,
        "family": family, "code": sha(__file__), "server": sha(server)}, sort_keys=True).encode()).hexdigest()
    directory = Path(settings["work_root"])/signature[:20]
    directory.mkdir(parents=True, exist_ok=True)
    prepared = directory/"prepared.mp4"
    if not prepared.exists():
        shutil.copy2(picture, prepared)
    if sha(prepared) != sha(picture):
        raise RuntimeError("Resolve staging integrity mismatch")
    comp, beats = composition(prepared, frames, shots, family)
    comp_path = directory/"PLANEXIUM.comp"
    comp_path.write_text(comp, encoding="utf-8")
    request = {"directory": str(directory), "picture": str(prepared), "composition": str(comp_path),
        "frames": frames, "project": "PLANEXIUM_"+signature[:20], "server": str(server),
        "python": str(python), "timeout": settings.get("timeout", 14400),
        "minimum_free_bytes": settings.get("minimum_free_bytes", 0),
        "start_headroom_bytes": settings.get("start_headroom_bytes", 0),
        "system_reserve_path": settings.get("system_reserve_path", "C:/"),
        "destination_reserve_path": settings.get("destination_reserve_path", str(directory)),
        "destination_minimum_free_bytes": settings.get("destination_minimum_free_bytes", 0),
        "destination_minimum_free_fraction": settings.get("destination_minimum_free_fraction", 0),
        "estimated_remaining_output_bytes": max(picture.stat().st_size * 4, 1_073_741_824)}
    if settings.get("bridge_config"):
        request["bridge_config"]=settings["bridge_config"]
    if settings.get("autostart"):
        request["autostart"] = settings["autostart"]
        request["work_root"] = settings["work_root"]
    request_path = directory/"request.json"; write(request_path, request)
    with (work/"resolve-mcp.log").open("a", encoding="utf-8") as log:
        child = subprocess.Popen([str(python), str(Path(__file__).resolve()), str(request_path)],
                                 stdout=log, stderr=subprocess.STDOUT, env=isolated_environment(settings))
        while child.poll() is None:
            path = directory/"progress.json"
            detail = json.loads(path.read_text()) if path.exists() else {"status": "connecting"}
            write(work/"render-progress.json", {"status": "resolve_fusion", "detail":
                f"Resolve/Fusion: {detail['status']} ({detail.get('percent', 0)}%)"})
            time.sleep(3)
        if child.returncode:
            raise RuntimeError("Resolve/Fusion finishing blocked; see resolve-mcp.log and retained owner receipt")
    rendered = directory/"resolve-master.mp4"
    validate_output(rendered, frames)
    # Keep source preparation and the Resolve result separate for retry/integrity.
    destination = work/"resolve-master.mp4"
    shutil.copy2(rendered, destination)
    destination.replace(picture)
    shutil.copy2(directory/"project.drp", work/"resolve-project.drp")
    shutil.copy2(comp_path, work/"resolve.comp")
    write(work/"resolve-receipt.json", {"backend": "resolve_fusion", "signature": signature,
        "job_id": json.loads((directory/"owner.json").read_text())["job_id"],
        "master_sha256": sha(picture), "frames": frames, "native_fusion_beats": beats,
        "weekday_format": family, "public_publish_authorized": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("--bootstrap", action="store_true",
                        help="Read channel config and only start/check Resolve; never produce/upload")
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    if args.bootstrap:
        request = request["resolve"]
        directory = Path(request["work_root"])/"bootstrap"
        directory.mkdir(parents=True, exist_ok=True)
        request = {**request, "directory": str(directory), "preflight": True}
    asyncio.run(worker(request))
