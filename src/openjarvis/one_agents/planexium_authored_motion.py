"""Explicit, mission-scoped scientific illustrations; never stock aliases."""
from __future__ import annotations
import hashlib
from pathlib import Path

KIND = "authored_scientific_motion"
SCHEMA = "planexium-local-assets-v2"
APPROVAL = "Sentinel_d13517b7ba788191a81dbf04dc143cbf"
MISSION = "daily-20261026"
SPECS = {
    "12": {"scene": 6, "concept": "deep-atmospheric-ribbons", "claims": ["C2", "C5"]},
    "17": {"scene": 9, "concept": "diffuse-core-cross-section", "claims": ["C8"]},
    "18": {"scene": 9, "concept": "diffuse-boundary-detail", "claims": ["C8"]},
}
LABEL = "ILLUSTRATIVE MODEL - NOT AN OBSERVATION"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def amendment():
    return {"version": 1, "mission_id": MISSION, "approval_id": APPROVAL,
            "licensed_stock_count": 17, "authored_motion_slots": [12, 17, 18],
            "retained_stock_floor": 16, "archive_screen_fraction_max": 0.4}


def validate_accounting(root, bundle, science):
    """Allow the exact founder amendment, retaining original acquisition history."""
    motions = bundle["assets"].get("authored_motion", {})
    if bundle.get("schema") != SCHEMA:
        if motions or bundle.get("accounting_amendment"):
            raise ValueError("Authored motion requires a versioned accounting amendment")
        return {}
    if (Path(root).name != MISSION or bundle.get("accounting_amendment") != amendment()
            or set(motions) != set(SPECS) or len(bundle["assets"]["stock"]) != 20):
        raise ValueError("Authored motion is outside the approved mission accounting")
    if not {6, 9}.issubset(bundle["scenes"]):
        raise ValueError("Authored slots require their scoped scenes")
    claims = {c["id"]: c for c in science["claims"]}
    for slot, asset in motions.items():
        spec = SPECS[slot]
        scene = science["scenes"][spec["scene"] - 1]
        if (int(slot)-1 not in bundle["plan"]["scene_assets"][str(spec["scene"])]
                or scene["visual_kind"] != "graphic"
                or not set(spec["claims"]).issubset(scene["claim_ids"])):
            raise ValueError("Illustration is outside its approved science scene")
        expected = {"asset_type": KIND, "provider": "local_deterministic",
                    "illustrative": True, "label": LABEL, "concept": spec["concept"],
                    "claim_ids": spec["claims"],
                    "claim_sources": {c: claims[c]["source_id"] for c in spec["claims"]},
                    "science_sha256": sha(Path(root)/"science-plan.json"),
                    "generator_sha256": sha(__file__), "slot": int(slot)}
        if any(asset.get(k) != v for k,v in expected.items()):
            raise ValueError("Illustration provenance or source-backed claims changed")
        if asset.get("source_identity") != "planexium:" + spec["concept"]:
            raise ValueError("Illustration lacks canonical concept identity")
    return motions


def render_candidate(science_path, slot, destination):
    """Local finite illustration. No measurements, acquisition, or production writes."""
    import json
    import math
    import subprocess
    from PIL import Image, ImageDraw, ImageFont

    spec = SPECS[str(slot)]
    science_path, destination = Path(science_path), Path(destination)
    if destination.exists():
        raise FileExistsError("Retain existing candidate evidence")
    science = json.loads(science_path.read_text(encoding="utf-8"))
    claims = {c["id"]: c for c in science["claims"]}
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    font = ImageFont.truetype(str(font_path), 38)
    small = ImageFont.truetype(str(font_path), 26)
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-n", "-f", "rawvideo",
               "-pix_fmt", "rgb24", "-s", "1920x1080", "-r", "30", "-i", "pipe:0",
               "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
               "-pix_fmt", "yuv420p", "-threads", "2", str(destination)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for frame in range(603):
            t = frame / 30
            image = Image.new("RGB", (1920, 1080), "#081624")
            draw = ImageDraw.Draw(image)
            draw.text((90, 65), spec["concept"].replace("-", " ").upper(), font=font, fill="#edf2ec")
            if slot == 12:
                # Qualitative opposing flow, no velocity/depth scale or measured trajectory.
                for band in range(6):
                    y = 280 + band * 94
                    color = (90 + band*18, 135 + band*9, 172)
                    draw.rounded_rectangle((170, y, 1750, y+55), radius=24, fill=color)
                    direction = 1 if band % 2 else -1
                    for k in range(8):
                        x = 210 + ((k*210 + direction*t*42) % 1480)
                        draw.line((x-24*direction,y+28,x+24*direction,y+28),fill="#ecede7",width=4)
                        draw.polygon([(x+24*direction,y+28),(x+10*direction,y+18),(x+10*direction,y+38)],fill="#ecede7")
                draw.text((170, 875), "Conceptual ribbons beneath the visible cloud bands", font=small, fill="#b8cbd8")
            elif slot == 17:
                # Smooth conceptual cross section: no sharp core boundary or numerical radius.
                cx, cy = 960, 550
                for radius in range(330, 0, -2):
                    f = (1-radius/330)**1.4
                    color = (int(48+150*f), int(100+45*f), int(155-50*f))
                    draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),fill=color)
                angle = -0.7 + t*0.06
                x, y = cx+270*math.cos(angle), cy+270*math.sin(angle)
                draw.line((cx,cy,x,y),fill="#d8e4e8",width=3)
                draw.text((520, 910), "Diffuse central region - qualitative cross section",font=small,fill="#b8cbd8")
            else:
                # A distinct close-up abstraction explains gradual blending, not circulation data.
                for x in range(250, 1670, 3):
                    f = 1/(1+math.exp((x-960)/170))
                    color = (int(48+150*f), int(100+45*f), int(155-50*f))
                    draw.rectangle((x,300,x+3,830),fill=color)
                x = 350 + t/20.1*1200
                draw.line((x,320,x,810),fill="#d8e4e8",width=3)
                draw.text((300, 875), "Boundary detail: gradual blending, no sharply defined edge",font=small,fill="#b8cbd8")
            draw.text((90, 985), LABEL, font=small, fill="#f3dc9e")
            draw.text((90, 1025), "Qualitative schematic; shapes, colors and motion are illustrative, not measured data.",font=small,fill="#b8cbd8")
            process.stdin.write(image.tobytes())
        process.stdin.close()
        error = process.stderr.read().decode(errors="replace")
        if process.wait() != 0:
            raise RuntimeError(error)
    except BaseException:
        process.kill()
        process.wait()
        raise
    asset = {"path": str(destination.resolve()), "sha256": sha(destination),
             "asset_type": KIND, "provider": "local_deterministic", "illustrative": True,
             "label": LABEL, "concept": spec["concept"], "claim_ids": spec["claims"],
             "claim_sources": {c: claims[c]["source_id"] for c in spec["claims"]},
             "science_sha256": sha(science_path), "generator_sha256": sha(__file__),
             "font_sha256": sha(font_path), "slot": slot, "seconds": 20.1,
             "width": 1920, "height": 1080, "fps": 30, "frames": 603,
             "source_identity": "planexium:" + spec["concept"]}
    destination.with_suffix(".json").write_text(json.dumps(asset, indent=2), encoding="utf-8")
    return asset
