"""Science assembly using the installed editor's public functions in a child process."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

# 80811d7 rendered identical raw scenes; this revision changes only assembly
# normalization. Admit its cache only when every original recipe/hash matches.
COMPATIBLE_RAW_RENDERER = "eb064ebad5c61649b1d87cb6a4c4e7b4934c2abf9c022ef5bdb0cbad711fb7cf"


def normalize_scene(source: Path, seconds: float, command) -> Path:
    frames = round(seconds * 30)
    target = source.with_name(source.stem + '-normalized.mp4')
    signature = hashlib.sha256(source.read_bytes()).hexdigest() + ':' + str(frames)
    receipt = target.with_suffix('.json')
    prior = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
    if target.exists() and prior.get('signature') == signature and prior.get('sha256') == hashlib.sha256(target.read_bytes()).hexdigest():
        return target
    command(['ffmpeg', '-y', '-v', 'error', '-i', str(source), '-an',
        '-vf', 'fps=30,tpad=stop_mode=clone:stop_duration=1,setpts=N/(30*TB)',
        '-frames:v', str(frames), '-r', '30', '-fps_mode', 'cfr',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', str(target)])
    receipt.write_text(json.dumps({'signature': signature, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}), encoding='utf-8')
    return target


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError("Installed production component unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _command(args):
    result = subprocess.run(args, check=True, capture_output=True, text=True, timeout=7200)
    return result


def _layer(text: str, out: Path, *, y: int, size=48):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", size)
    words, line, rows = text.split(), "", []
    for word in words:
        if draw.textlength((line + " " + word).strip(), font=font) > 1640 and line:
            rows.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    rows.append(line)
    if len(rows) > 3:
        raise ValueError("On-screen science text exceeds readable layout; shorten it")
    for i, row in enumerate(rows):
        draw.text((110, y + i * (size + 15)), row, font=font, fill=(245, 247, 250, 255),
                  stroke_width=3, stroke_fill=(0, 0, 0, 230))
    image.save(out)


def render(root: Path, tools: Path, *, motion_format: str | None = None, resolve_settings=None) -> dict:
    if (root / 'cinematic-plan.json').exists():
        if resolve_settings:
            from openjarvis.one_agents.planexium_resolve import preflight
            preflight(root, resolve_settings)
        from openjarvis.one_agents.planexium_cinematic import render as cinematic_render
        return cinematic_render(root, tools, resolve_settings=resolve_settings)
    if resolve_settings:
        raise ValueError("Resolve/Fusion requires the finite cinematic storyboard")
    # Flat imports in the installed editor are isolated to this CLI process.
    sys.path.insert(0, str(tools))
    assembly = _load(tools / "assemble.py", "planexium_shared_assembly")
    qc = _load(tools / "qc.py", "planexium_shared_qc")
    graphics = _load(tools / "render_graphics.py", "planexium_shared_graphics")
    assembly.sfx.CACHE = root / "edit" / "sfx-cache"
    plan = json.loads((root / "science-plan.json").read_text(encoding="utf-8"))
    narration_path = root / "narration" / "narration.segments.json"
    narration = json.loads(narration_path.read_text(encoding="utf-8"))
    assets = json.loads((root / "media-manifest.json").read_text(encoding="utf-8"))["scenes"]
    work = root / "edit"
    work.mkdir(parents=True, exist_ok=True)
    # Explicit mission-local visual repairs preserve original acquisition evidence.
    repair = root / "visual-repair.json"
    if repair.exists():
        replacement = json.loads(repair.read_text(encoding="utf-8"))
        for number, media in replacement["scenes"].items():
            if number not in assets or not media.get("assets"):
                raise ValueError("Visual repair references an unknown or empty scene")
            for asset in media["assets"]:
                path = Path(asset["path"]).resolve()
                if not path.is_relative_to(root.resolve()) or not path.is_file():
                    raise ValueError("Visual repair asset is outside its mission")
                if hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
                    raise ValueError("Visual repair asset integrity mismatch")
            assets[number] = media
        (work / "render-media-manifest.json").write_text(json.dumps({"scenes": assets}, indent=2), encoding="utf-8")
    cuts, timing = [], []
    from openjarvis.one_agents.youtube_motion import KineticDirector, assignment, library_hash

    copy_path = root / "motion-copy.json"
    authored_copy = json.loads(copy_path.read_text(encoding="utf-8")) if copy_path.exists() else {}
    for i, scene in enumerate(plan["scenes"], 1):
        if str(i) in authored_copy:
            scene["motion_copy"] = authored_copy[str(i)]
    selected = assignment(root, override=motion_format)
    with KineticDirector(root, brand="The Planexium", selected=selected) as director:
        for i, (scene, voice) in enumerate(zip(plan["scenes"], narration["segments"], strict=True), 1):
            progress=work / "render-progress.json"
            temporary=progress.with_suffix('.tmp')
            temporary.write_text(json.dumps({'scene':i,'total_scenes':len(plan['scenes']),'status':'rendering'}),encoding='utf-8')
            temporary.replace(progress)
            seconds = float(voice["seconds"])
            out = work / f"scene-{i:03d}.mp4"
            media = assets[str(i)]
            recipe = {"scene": scene, "media": media, "voice": voice,
                "format": selected, "library": library_hash(),
                "renderer": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
            signature = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
            compatible = hashlib.sha256(json.dumps({**recipe, 'renderer': COMPATIBLE_RAW_RENDERER}, sort_keys=True).encode()).hexdigest()
            stamp = out.with_suffix(".receipt.json")
            prior = json.loads(stamp.read_text(encoding="utf-8")) if stamp.exists() else {}
            reusable = out.exists() and prior.get("signature") in {signature, compatible} and prior.get("sha256") == hashlib.sha256(out.read_bytes()).hexdigest()
            if reusable:
                normalized = normalize_scene(out, seconds, _command)
                timing.append({**prior["timing"], 'video_seconds': assembly.probe_seconds(normalized)})
                director.receipts.extend(prior["direction_beats"])
                cuts.append(normalized)
                continue
            first_beat = len(director.receipts)
            count = director.scene(scene, media, number=i, seconds=seconds, out=out, command=_command)
            timing.append({"scene_id": str(i), "voice_seconds": seconds,
                           "video_seconds": assembly.probe_seconds(out), "kind": "director", "unique_shots": count})
            stamp.write_text(json.dumps({"signature": signature, "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                "timing": timing[-1], "direction_beats": director.receipts[first_beat:]}, indent=2), encoding="utf-8")
            normalized = normalize_scene(out, seconds, _command)
            timing[-1]['video_seconds'] = assembly.probe_seconds(normalized)
            cuts.append(normalized)
            print(f"Motion V3 scene {i}: {count} beats, {seconds:.2f}s", flush=True)
        director.save_receipt()
    concat = work / "picture-concat.txt"
    # Paths are our own validated mission paths. FFmpeg concat escaping is
    # independent of shell escaping; no shell is used.
    concat.write_text("\n".join("file '" + p.as_posix().replace("'", "'\\''") + "'" for p in cuts), encoding="utf-8")
    picture = work / "picture.mp4"
    _command(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(picture)])
    # Existing concat_narration explicitly encodes AAC. Its container must be
    # M4A, even though source segments are local PCM WAV files.
    wav = work / "narration.m4a"
    assembly.concat_narration(narration_path, wav)
    soundtrack = assembly.build_soundtrack(wav, [r["start"] for r in narration["segments"]][1:], [], work)
    master = work / "master.mp4"
    _command(["ffmpeg", "-y", "-v", "error", "-i", str(picture), "-i", str(soundtrack),
              "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", "loudnorm=I=-16:TP=-1.5:LRA=9",
              "-c:a", "aac", "-b:a", "192k", "-t", str(narration["total_seconds"]), "-movflags", "+faststart", str(master)])
    report = qc.Report()
    duration = qc.check_streams(master, report)
    qc.check_sync(master, narration_path, duration, report)
    qc.check_black(master, report)
    qc.check_silence(master, report)
    qc.check_loudness(master, report)
    report.add("PASS" if all(abs(r["voice_seconds"] - r["video_seconds"]) < 0.1 for r in timing) else "FAIL",
               "per-scene sync", "Scene cuts measured against local narration")
    report.add("REVIEW", "science and imagery rights", "Primary-source receipts retained; human semantic/rights review required")
    rows = [{"level": level, "check": check, "detail": detail} for level, check, detail in report.rows]
    (work / "qc-report.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (work / "assembly-report.json").write_text(json.dumps({"scene_timing": timing,
        "narration_backend": narration["backend"], "master": str(master), "shared_editor": "installed assemble.py functions",
        "human_review_required": True}, indent=2), encoding="utf-8")
    if report.failed:
        raise RuntimeError("Science master failed technical QC; no upload permitted")
    (work / "render-progress.json").write_text(json.dumps({"scene": len(plan["scenes"]),
        "total_scenes": len(plan["scenes"]), "status": "qc_passed"}), encoding="utf-8")
    return {"master": str(master), "seconds": duration, "qc": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--format", choices=("travel-dossier", "cinematic-clean", "editorial-punch", "kinetic-type", "motion-lab"))
    parser.add_argument("--job-signature")
    parser.add_argument("--resolve-settings", type=Path)
    args = parser.parse_args()
    resolve_settings = json.loads(args.resolve_settings.read_text(encoding='utf-8')) if args.resolve_settings else None
    if args.resolve_settings is None:
        # The resident ONE worker may have imported an older parent pipeline.
        # Render children always start from current disk code, so adopt the
        # selected backend here too without restarting unrelated live agents.
        from openjarvis.one_agents.planexium import load_config, _write
        backend_path = args.root / 'render-backend.json'
        if backend_path.exists():
            backend = json.loads(backend_path.read_text(encoding='utf-8'))
        else:
            config = load_config()
            backend = {'backend': config.get('render_backend', 'legacy'),
                       'resolve': config.get('resolve'), 'legacy_parent_request': True}
            _write(backend_path, backend)
        if backend['backend'] == 'resolve_fusion':
            resolve_settings = backend.get('resolve')
            if not resolve_settings:
                raise ValueError('Resolve/Fusion settings missing; no fallback')
    try:
        result = render(args.root.resolve(), args.tools.resolve(), motion_format=args.format,
            resolve_settings=resolve_settings)
    except Exception:
        progress = args.root.resolve() / 'edit/render-progress.json'
        state = json.loads(progress.read_text(encoding='utf-8')) if progress.exists() else {}
        progress.write_text(json.dumps({**state, 'status': 'failed'}), encoding='utf-8')
        raise
    if args.job_signature:
        root=args.root.resolve()
        receipt={'signature':args.job_signature,'files':{name:hashlib.sha256((root/name).read_bytes()).hexdigest()
            for name in ['edit/master.mp4','edit/qc-report.json']}}
        target=root/'edit/render-complete.json';temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(receipt,indent=2),encoding='utf-8');temporary.replace(target)
    print(json.dumps({"status": "qc_passed", "seconds": result["seconds"]}))
