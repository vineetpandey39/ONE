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
import shutil
import subprocess
import time


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temp.replace(path)


def probe(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams",
        "-show_format", "-of", "json", str(path)], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def validate_output(path, frames):
    data = probe(path)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    if ((video["width"], video["height"]) != (1920, 1080)
            or video["avg_frame_rate"] != "30/1"
            or int(video["nb_frames"]) != frames or audio is None
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


def composition(picture, frames, shots, family):
    """Native editable Fusion titles, animated plate/rule and orbital motif."""
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
        text = str(shot.get("callout") or "").strip()
        if not text or shot["kind"] == "primary" or shot.get("science_overlay"):
            continue
        start, count = int(shot["start_frame"]), int(shot["frames"])
        end = start + count
        if start < 0 or end > frames or count < 15:
            raise ValueError("Fusion beat exceeds measured picture")
        # Keep director-authored copy intact, wrapped for a mobile-readable plate.
        import textwrap
        lines = textwrap.wrap(text, 30)
        if len(lines) > 3:
            raise ValueError("Fusion title exceeds three readable lines; repair director copy")
        fade = f"iif(time>={start} and time<{end},min(1,max(0,(time-{start})/10))*min(1,max(0,({end}-time)/10)),0)"
        move = f"Point({x},{y}-.025*max(0,1-(time-{start})/16))"
        prefix = f"Beat{index}"
        node(prefix+"Mask", "RectangleMask", [
            inp("MaskWidth", 1920), inp("MaskHeight", 1080),
            inp("Center", expr=move), inp("Width", .54), inp("Height", .08+.06*len(lines)),
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
    if not beats:
        raise ValueError("No eligible director beats for native Fusion; no fake success")
    node("MediaOut1", "MediaOut", [inp("Index", 0), inp("Input", source=last)])
    return (f"Composition{{GlobalStart=0,GlobalEnd={frames-1},RenderStart=0,RenderEnd={frames-1},"
            "Tools=ordered(){"+ "\n".join(nodes) + "}}"), beats


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
            raise RuntimeError("Partial project assembly needs reconciliation; no duplicate timeline created")
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
        await client.call("render", "set_settings", settings={
            "SelectAllFrames": True, "ExportAudio": True, "ExportVideo": True,
            "TargetDir": str(directory), "CustomName": "resolve-master"})
        state["phase"] = "submitting"; write(state_path, state)
        state["job_id"] = (await client.call("render", "add_job"))["job_id"]
        state["phase"] = "queued"; write(state_path, state)
    status = await client.call("render", "get_job_status", job_id=state["job_id"])
    if status["JobStatus"] == "Ready":
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
        if time.monotonic() > deadline:
            raise TimeoutError("Resolve job still in flight; resume this job, never duplicate it")
        await asyncio.sleep(5)
    await client.call("project_manager", "save")
    await client.call("project_manager", "export_project", name=project,
                      path=str(directory/"project.drp"))
    state["phase"] = "rendered"; write(state_path, state)


async def worker(request):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    server = Path(request["server"])
    params = StdioServerParameters(command=request["python"], args=[str(server)],
        cwd=str(server.parent.parent),
        env={**os.environ, "DAVINCI_RESOLVE_BRIDGE": "1", "PYTHONUTF8": "1"})
    with machine_lock(Path(request["directory"]).parent/"resolve.lock"):
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                await execute(request, MCP(session, Path(request["directory"])/"mcp-events.jsonl"))


def finish(root, settings, shots, family):
    """Called inside the existing owned render child, before final whole-file QC."""
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
        "python": str(python), "timeout": settings.get("timeout", 14400)}
    request_path = directory/"request.json"; write(request_path, request)
    with (work/"resolve-mcp.log").open("a", encoding="utf-8") as log:
        child = subprocess.Popen([str(python), str(Path(__file__).resolve()), str(request_path)],
                                 stdout=log, stderr=subprocess.STDOUT)
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
    args = parser.parse_args()
    asyncio.run(worker(json.loads(args.request.read_text(encoding="utf-8"))))
