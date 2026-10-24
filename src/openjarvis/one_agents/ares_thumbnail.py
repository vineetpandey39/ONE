"""ARES's autonomous Sonia thumbnail: portrait -> ChatGPT background (LAO) -> exact hook text -> 1280x720.

Everything topic-specific arrives in the SEO package; this module only runs the steps and keeps a
receipt. A failure is returned, never raised, so the upload gate can decide what a missing
thumbnail means instead of the whole ARES job dying.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from openjarvis.one_agents import thumbnail_compose, thumbnail_retouch

PROCESS = "Sonia YATRA - Thumbnail"
TERMINAL = {"Successful", "Failed", "Stopped", "Cancelled", "Faulted"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}

EXPERIMENT_FORMATS = (
    {"name": "Single hero", "sonia_expression": "genuinely surprised, raised brows, alert eyes",
     "posture": "leaning slightly toward the hook", "gesture": "index finger clearly pointing toward the hook text",
     "composition": "one oversized story object in the protected centre lane; no decorative objects",
     "primary_colour": [255, 255, 255], "accent_colour": [255, 214, 0]},
    {"name": "Visual contrast", "sonia_expression": "curious and skeptical, one eyebrow raised",
     "posture": "upright three-quarter pose", "gesture": "one hand at chin, evaluating the offer",
     "composition": "one simple visual contrast using only truthful story elements; hero remains unobstructed",
     "primary_colour": [255, 255, 255], "accent_colour": [255, 64, 48]},
    {"name": "Clean curiosity", "sonia_expression": "concerned curiosity, alert eyes",
     "posture": "slightly forward-facing", "gesture": "open-palm stop or caution gesture beside the hook",
     "composition": "one curiosity object at large scale with a clean silhouette and no collage",
     "primary_colour": [255, 255, 255], "accent_colour": [151, 255, 45]},
)


def _local_fallback_base(portrait: Path, destination: str, out: Path) -> Path:
    """Create a zero-cost, deterministic thumbnail base when ChatGPT image credits are unavailable.

    ChatGPT remains the primary art director.  This fallback keeps the pipeline shippable: Sonia
    stays on the right, the left remains clean for the exact hook, and the destination palette is
    derived from the destination name so consecutive videos do not all look identical.
    """
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

    seed = hashlib.sha256(destination.encode("utf-8")).digest()
    accent = (80 + seed[0] % 140, 70 + seed[1] % 130, 70 + seed[2] % 150)
    canvas = Image.new("RGB", thumbnail_compose.SIZE, (10, 19, 36))
    draw = ImageDraw.Draw(canvas)
    for x in range(canvas.width):
        t = x / max(1, canvas.width - 1)
        colour = tuple(int((1 - t) * c + t * a) for c, a in zip((10, 19, 36), accent))
        draw.line((x, 0, x, canvas.height), fill=colour)
    # Large soft destination-colour shapes add depth without pretending to be evidence footage.
    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((570, -150, 1190, 470), fill=(*accent, 135))
    gd.ellipse((710, 300, 1390, 920), fill=(255, 196, 64, 75))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(55)))

    person = ImageOps.exif_transpose(Image.open(portrait)).convert("RGB")
    person = ImageEnhance.Contrast(person).enhance(1.05)
    target_h = 660
    person.thumbnail((570, target_h), Image.Resampling.LANCZOS)
    mask = Image.new("L", person.size, 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, person.width - 1, person.height - 1), radius=55, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    x = canvas.width - person.width - 22
    y = canvas.height - person.height
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 170), (x + 12, y + 16, x + person.width + 12, y + person.height + 16), mask)
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(16)))
    canvas.paste(person.convert("RGBA"), (x, y), mask)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out, "PNG", optimize=True)
    return out


def pick_portrait(library: Path, seed: str, recent: list[str] | None = None) -> Path:
    """An approved portrait (portraits.json "preferred"), the one used least recently by earlier videos first;
    otherwise the sharpest-looking large image. Raises if the library has nothing usable.

    With one approved photo every thumbnail had the same face and pose (Vietnam and Air France, 2026-10-09). The
    Chairman approved more, and they now rotate: never-used first, then the one used longest ago."""
    from PIL import Image

    files = sorted(p for p in library.glob("*") if p.suffix.lower() in IMAGE_SUFFIXES) if library.is_dir() else []
    if not files:
        raise RuntimeError(f"No Sonia portraits in {library}")
    config = library / "portraits.json"
    if config.is_file():
        preferred = [library / n for n in json.loads(config.read_text(encoding="utf-8")).get("preferred", [])]
        preferred = [p for p in preferred if p.is_file()]
        if preferred:
            order = [Path(r).name for r in (recent or [])]  # most recent first
            # Receipts live in different roots for long-form YATRA and VISTA,
            # and concurrent jobs choose before either receipt exists. Keep a
            # tiny global claim ledger beside the approved portraits so both
            # agents rotate one shared pool rather than converging on the same
            # last image. The exclusive lock makes simultaneous claims safe.
            ledger_path = library / "portrait-usage.json"
            lock_path = library / ".portrait-usage.lock"
            fd = None
            for _ in range(100):
                try:
                    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    break
                except FileExistsError:
                    try:
                        if time.time() - lock_path.stat().st_mtime > 30:
                            lock_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    time.sleep(0.02)
            if fd is None:
                raise RuntimeError("Sonia portrait rotation ledger is busy")
            os.close(fd)
            try:
                try:
                    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    ledger = {}
                # A retry of the same video must preserve its identity source;
                # rotation is across different videos, not across attempts.
                prior = next((library / name for name, usage in ledger.items()
                              if usage.get("seed") == seed[:160] and (library / name) in preferred), None)
                if prior is not None:
                    return prior
                tie = int(hashlib.sha256(seed.encode()).hexdigest(), 16)

                def rank(path: Path) -> tuple[int, int, float, int]:
                    usage = ledger.get(path.name) or {}
                    # A current video receipt is stronger than an old claim;
                    # otherwise least claimed, least recently claimed wins.
                    recent_penalty = len(order) - order.index(path.name) if path.name in order else 0
                    return (recent_penalty, int(usage.get("count") or 0),
                            float(usage.get("last_used") or 0),
                            (tie + preferred.index(path)) % len(preferred))

                chosen = min(preferred, key=rank)
                usage = ledger.get(chosen.name) or {}
                ledger[chosen.name] = {"count": int(usage.get("count") or 0) + 1,
                                       "last_used": time.time(), "seed": seed[:160]}
                tmp = ledger_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
                tmp.replace(ledger_path)
                return chosen
            finally:
                lock_path.unlink(missing_ok=True)

    def score(path: Path) -> int:
        with Image.open(path) as im:
            return min(im.size)

    return max(files, key=score)


REFERENCE_SHEET_NOTE = (
    "\n\nREFERENCE SHEET (mandatory): the attached image holds two photos of the SAME woman, Sonia. Take her face "
    "exactly from the close-up on the RIGHT panel: eye shape, nose, lips, jawline, cheeks, eyebrows, skin tone and "
    "age. Take her hair and outfit from the LEFT panel. Show her ONCE in the thumbnail, never twice, and never "
    "invent or beautify facial features. Remove only temporary acne/blemishes; keep natural pores and every "
    "permanent facial feature unchanged.")
FACE_MIN_PIXELS = 220  # a face smaller than this in its photo is too few pixels for the image model to copy


def _faces(path: Path) -> tuple[Any, list[tuple[int, int, int, int]]]:
    """(RGB image, face boxes largest first). No detector or no face -> empty list, never an error."""
    from PIL import Image, ImageOps
    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    try:
        import cv2
        import numpy as np
        detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
        boxes = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(40, 40))
        return image, sorted((tuple(int(v) for v in b) for b in boxes), key=lambda b: -b[3])
    except Exception:  # noqa: BLE001 - no OpenCV: fall back to the photo's upper middle
        return image, []


def _crop_around(image: Any, face: tuple[int, int, int, int] | None, *, wide: float, up: float, down: float,
                 height: int = 1024) -> Any:
    from PIL import Image
    if face:
        x, y, w, h = face
        cx = x + w / 2
        box = (max(0, int(cx - wide * w / 2)), max(0, int(y - up * h)),
               min(image.width, int(cx + wide * w / 2)), min(image.height, int(y + down * h)))
    else:
        box = (int(image.width * 0.1), 0, int(image.width * 0.9), int(image.height * 0.6))
    crop = image.crop(box)
    scale = height / crop.height
    return crop.resize((max(1, round(crop.width * scale)), height), Image.LANCZOS)


def reference_sheet(portrait: Path, library: Path, out: Path) -> dict[str, Any]:
    """What ChatGPT sees as Sonia: the chosen photo cropped to head and shoulders, plus her clearest close-up.

    Air France, 2026-10-09: the chosen photo was full-length, Sonia's face was 81 px of a 1310 px image, and
    ChatGPT invented a different face. A photo whose face is under FACE_MIN_PIXELS gets a second panel with the
    approved portrait whose face is largest, and the prompt takes the face from it."""
    from PIL import Image
    image, faces = _faces(portrait)
    left = _crop_around(image, faces[0] if faces else None, wide=3.4, up=1.0, down=3.2)
    panels = [left]
    if not faces or faces[0][3] < FACE_MIN_PIXELS:
        anchors = []
        config = library / "portraits.json"
        names = json.loads(config.read_text(encoding="utf-8")).get("preferred", []) if config.is_file() else []
        for candidate in [library / n for n in names if (library / n).is_file()]:
            c_image, c_faces = _faces(candidate)
            if c_faces and c_faces[0][3] >= FACE_MIN_PIXELS:
                anchors.append((c_faces[0][3], c_image, c_faces[0]))
        if anchors:
            _, a_image, a_face = max(anchors, key=lambda a: a[0])
            panels.append(_crop_around(a_image, a_face, wide=1.9, up=0.55, down=1.45))
    gap = 16
    sheet = Image.new("RGB", (sum(p.width for p in panels) + gap * (len(panels) - 1), 1024), (255, 255, 255))
    x = 0
    for panel in panels:
        sheet.paste(panel, (x, 0))
        x += panel.width + gap
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=92)
    return {"path": str(out), "panels": len(panels), "face_pixels": faces[0][3] if faces else 0}


def thumbnail_history(asset_root: Path, exclude: Path | None = None) -> list[dict[str, Any]]:
    """Earlier videos' thumbnails, most recent first: {"layout", "portrait"} from their receipts."""
    rows = []
    for folder in asset_root.iterdir() if asset_root.is_dir() else []:
        if not folder.is_dir() or folder.name.startswith("_") or (exclude and folder.resolve() == exclude.resolve()):
            continue
        for name in ("thumbnail-experiment.json", "thumbnail-receipt.json"):
            receipt = folder / "thumbnail" / name
            if receipt.is_file():
                try:
                    data = json.loads(receipt.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                rows.append((receipt.stat().st_mtime, {"layout": data.get("layout") or "right",
                                                        "portrait": data.get("portrait") or ""}))
                break
    return [row for _, row in sorted(rows, key=lambda r: r[0], reverse=True)]


def next_layout(history: list[dict[str, Any]]) -> str:
    """Which side Sonia stands on: the opposite of the last video, so consecutive thumbnails never mirror."""
    last = history[0]["layout"] if history else "left"
    return "left" if last == "right" else "right"


LAYOUT_SWAPS = (
    ("Sonia as a large close-up on the RIGHT", "Sonia as a large close-up on the LEFT"),
    ("LEFT 0-38 percent is a low-detail, high-contrast hook zone; CENTRE 38-66 percent contains one large, "
     "unobstructed hero proof of the story ({left_usp}); RIGHT 66-100 percent contains Sonia",
     "RIGHT 62-100 percent is a low-detail, high-contrast hook zone; CENTRE 34-62 percent contains one large, "
     "unobstructed hero proof of the story ({left_usp}); LEFT 0-34 percent contains Sonia"),
    ("Keep the LOWER-LEFT portion of the LEFT 0-38 percent clean",
     "Keep the LOWER-RIGHT portion of the RIGHT 62-100 percent clean"),
    ("inside that lower-left text-safe area", "inside that lower-right text-safe area"),
)


def layout_prompt(template_text: str, layout: str) -> str:
    """The prompt's composition for Sonia on `layout`; the stored template is written for Sonia on the right."""
    if layout == "right":
        return template_text
    for old, new in LAYOUT_SWAPS:
        template_text = template_text.replace(old, new)
    return template_text


def _find_artifact(roots: Iterable[Path], lao_job: str, filename: str) -> Path | None:
    for root in roots:
        for folder in ("artifacts", "artifacts-02", "artifacts-studio"):
            candidate = root / folder / lao_job / filename
            if candidate.is_file() and candidate.stat().st_size > 10_000:
                return candidate
    return None


def experiment_variants(thumb: dict[str, Any]) -> list[dict[str, Any]]:
    """Return exactly three distinct identity-safe creative directions.

    ARES's SEO model may supply one or several hooks.  The visual experiment is
    deliberately fixed at three so upload cannot silently regress to a single
    untested pose.
    """
    supplied = thumb.get("variants") or []
    anchor = supplied[0] if supplied else {}
    variants = []
    for index, fmt in enumerate(EXPERIMENT_FORMATS):
        source = supplied[index] if index < len(supplied) else anchor
        variants.append({**source, **fmt,
                         "left_usp": source.get("left_usp") or anchor.get("left_usp") or "destination context",
                         "text": source.get("text") or anchor.get("text") or thumb.get("text") or "WORTH IT?"})
    return variants


def score_thumbnail(path: Path, qc: dict[str, Any], variant: dict[str, Any], *, portrait: bool = True) -> dict[str, Any]:
    """Transparent vidIQ-style *pre-upload* score, not a prediction of actual CTR."""
    from PIL import Image, ImageStat

    img = Image.open(path).convert("L").resize((320, 180))
    # Contrast is measured where the hook sits, which is the right side when Sonia stands on the left.
    left = img.crop((0, 0, 198, 180)) if qc.get("side", "left") == "left" else img.crop((122, 0, 320, 180))
    stat = ImageStat.Stat(left)
    contrast = min(1.0, (stat.stddev[0] if stat.stddev else 0.0) / 64.0)
    # High entropy behind type becomes clutter; moderate variation keeps context.
    histogram = left.histogram()
    total = sum(histogram) or 1
    occupied = sum(1 for count in histogram if count / total > 0.0005)
    clutter = max(0.0, 1.0 - abs(occupied - 100) / 155.0)
    legibility = min(1.0, float(qc.get("font_size", 0)) / 118.0)
    safe = 1.0 if qc.get("inside_left_zone") else 0.0
    export = 1.0 if qc.get("under_2mb") and qc.get("size") == [1280, 720] else 0.0
    expression = (1.0 if variant.get("sonia_expression") and variant.get("gesture") else 0.5) if portrait else (
        1.0 if variant.get("visual_direction") else 0.5)
    if portrait:
        coverage = 1.0
        score = round(100 * (0.30 * legibility + 0.20 * safe + 0.15 * export +
                             0.15 * contrast + 0.10 * clutter + 0.10 * expression), 1)
    else:
        from PIL import ImageFilter
        edges = img.filter(ImageFilter.FIND_EDGES)
        regions = [ImageStat.Stat(edges.crop((x*80, y*90, (x+1)*80, (y+1)*90))).mean[0]
                   for y in range(2) for x in range(4)]
        blank_quadrants = sum(value < 5 for value in regions)
        coverage = max(0.0, 1.0 - blank_quadrants / 4.0)
        score = round(100 * (0.20 * legibility + 0.10 * safe + 0.10 * export +
                             0.15 * contrast + 0.05 * clutter + 0.10 * expression + 0.30 * coverage), 1)
    return {"score": score, "scale": "vidiq_style_preupload_0_100", "not_actual_ctr": True,
            "signals": {"mobile_legibility": round(legibility * 100), "safe_zone": round(safe * 100),
                        "export_quality": round(export * 100), "hook_contrast": round(contrast * 100),
                        "controlled_clutter": round(clutter * 100), "canvas_coverage": round(coverage * 100),
                        "expression_gesture" if portrait else "visual_direction": round(expression * 100)}}


def make_thumbnail(package_path: Path, *, tool: Any, artifact_roots: Iterable[Path], variant_index: int = 0,
                   poll_seconds: float = 30, max_wait_seconds: float = 1800,
                   sleep: Callable[[float], None] = time.sleep, layout: str | None = None,
                   portrait: Path | None = None) -> dict[str, Any]:
    package_path = Path(package_path)
    root = package_path.parent.parent
    pkg = json.loads(package_path.read_text(encoding="utf-8"))
    from openjarvis.one_agents.youtube_channels import SONIA

    SONIA.validate_record(pkg)
    thumb = pkg["thumbnail"]
    variants = thumb.get("variants") or []
    if not variants:
        return {"ok": False, "stage": "plan", "error": "package has no thumbnail variants"}
    variant = variants[min(variant_index, len(variants) - 1)]
    out_dir = root / "thumbnail"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        history = thumbnail_history(root.parent, exclude=root)
        layout = layout or next_layout(history)
        portrait = portrait or pick_portrait(Path(thumb["portrait_library"]), pkg.get("recommended_title", ""),
                                             [h["portrait"] for h in history])
        text_side = "left" if layout == "right" else "right"
        prompt = layout_prompt(thumb["chatgpt_prompt_template"], layout).format(
            video_title=pkg["recommended_title"], destination=pkg.get("destination") or "the destination",
            left_usp=variant["left_usp"], sonia_expression=variant["sonia_expression"], thumbnail_text=variant["text"])
        # What may change is listed apart from what may not. The identity clause
        # used to be the tail of a sentence whose verb was "Change the pose,
        # gesture and expression ... while preserving Sonia's identity, face
        # geometry, skin tone and age", and an image model reads that as
        # permission with a caveat: on 2026-10-17 the Qatar thumbnail came back
        # with a slimmer jaw, a narrower face and poreless skin - recognisably
        # a beautified version of her rather than her. The prohibitions are
        # spelled out because that is the drift these models have by default.
        prompt += ("\n\nVARIANT DIRECTION (mandatory): Composition: "
                   + str(variant.get("composition") or "one unobstructed hero object")
                   + ". Sonia posture: " + str(variant.get("posture") or "close-up")
                   + ". Gesture: " + str(variant.get("gesture") or "point toward the hook")
                   + ". Only her pose, gesture and expression change for this variant."
                   + "\n\nIDENTITY (do not deviate): this is a real person and the thumbnail goes on "
                     "her own channel, so she must be recognisable to someone who knows her. "
                     "Reproduce the face in the reference portrait exactly: same face shape and "
                     "width, same jawline and chin, same nose, same eye shape and spacing, same "
                     "eyebrows, same hairline, same age, same body shape. Keep her real skin "
                     "texture, pores and tone - not a rendered or plastic surface. You may softly remove only "
                     "temporary acne/blemishes; do not erase permanent marks or change facial geometry. "
                     "Do NOT slim, lift, sculpt or narrow the face or jaw; do NOT globally smooth or "
                     "airbrush the skin; do NOT make her younger, thinner or more "
                     "symmetrical; do NOT give her a different nose, lips or eyes. No beauty filter "
                     "of any kind. She is not a lookalike, a model or an idealised version - she is "
                     "this woman. Keep both hands anatomically correct and keep the gesture clear of text.")
        sheet = reference_sheet(portrait, Path(thumb["portrait_library"]), out_dir / "reference-sheet.jpg")
        if sheet["panels"] == 2:
            prompt += REFERENCE_SHEET_NOTE
    except (RuntimeError, KeyError, IndexError) as exc:
        return {"ok": False, "stage": "plan", "error": f"{type(exc).__name__}: {exc}"}

    def fallback(reason: str) -> dict[str, Any]:
        try:
            base = _local_fallback_base(portrait, str(pkg.get("destination") or "Travel"),
                                        out_dir / f"variant-{variant_index + 1}-local-base.png")
            composed = thumbnail_compose.compose(base, variant["text"],
                                                  out_dir / f"variant-{variant_index + 1}-final.png",
                                                  primary=tuple(variant.get("primary_colour", [255, 255, 255])),
                                                  accent=tuple(variant.get("accent_colour", [255, 214, 0])),
                                                  side=text_side)
            receipt = {"ok": composed["qc"]["ok"], "path": composed["path"], "qc": composed["qc"],
                       "base": str(base), "portrait": str(portrait), "variant": variant["name"], "layout": layout,
                       "text": variant["text"], "source": "local_fallback", "fallback_reason": reason}
            (out_dir / "thumbnail-receipt.json").write_text(
                json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
            return receipt
        except (ValueError, OSError, RuntimeError) as exc:
            return {"ok": False, "stage": "fallback", "error": f"{type(exc).__name__}: {exc}",
                    "fallback_reason": reason}

    filename = f"variant-{variant_index + 1}-base.png"
    started = tool.execute(action="start", mode="publish", process_name=PROCESS, scope="production",
                           confirm_publish=True,
                           input_args={"prompt": prompt, "portraitPath": sheet["path"], "filename": filename,
                                       "chatgptCredentialAssetName": "chatgptLogin"})
    if not started.success:
        return fallback(f"LAO refused the thumbnail job: {started.content}")
    lao_job = str(((started.metadata or {}).get("job") or {}).get("id") or "")
    if not lao_job:
        return fallback("LAO started the thumbnail job without an id")

    status, waited = "Pending", 0.0
    while waited < max_wait_seconds:
        sleep(poll_seconds)
        waited += poll_seconds
        probe = tool.execute(action="status", process_name=PROCESS, scope="production", job_id=lao_job)
        if not probe.success:
            continue
        status = str(((probe.metadata or {}).get("job") or {}).get("status") or status)
        if status in TERMINAL:
            break
    if status != "Successful":
        result = fallback(f"ChatGPT thumbnail job ended as {status}")
        result.update(lao_job=lao_job, chatgpt_status=status)
        return result
    found = _find_artifact(artifact_roots, lao_job, filename)
    if not found:
        result = fallback(f"job succeeded but {filename} is not on disk")
        result.update(lao_job=lao_job, chatgpt_status=status)
        return result
    base = out_dir / filename
    shutil.copyfile(found, base)
    # The Chairman's finish (2026-10-09): clear skin and a white glow outline around Sonia, on every thumbnail.
    try:
        finish = thumbnail_retouch.retouch(base, out_dir / f"variant-{variant_index + 1}-retouched.png")
    except Exception as exc:  # noqa: BLE001 - a retouch problem never costs the thumbnail
        finish = {"path": str(base), "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    try:
        # Each variant writes its own file; only the experiment promotes a QC-passed winner to final.png. A failed
        # variant used to overwrite final.png, and the upload gate shipped it (Air France, 2026-10-09).
        composed = thumbnail_compose.compose(Path(finish["path"]), variant["text"],
                                              out_dir / f"variant-{variant_index + 1}-final.png",
                                              primary=tuple(variant.get("primary_colour", [255, 255, 255])),
                                              accent=tuple(variant.get("accent_colour", [255, 214, 0])),
                                              side=text_side)
    except (ValueError, OSError) as exc:
        return {"ok": False, "stage": "compose", "lao_job": lao_job, "base": str(base), "error": str(exc)}
    receipt = {"ok": composed["qc"]["ok"], "path": composed["path"], "qc": composed["qc"], "base": str(base),
               "lao_job": lao_job, "portrait": str(portrait), "variant": variant["name"], "text": variant["text"],
               "layout": layout, "retouch": finish}
    # A per-variant receipt must not overwrite the experiment decision.  The
    # old shared receipt always described variant 3, even when variant 1/2 won.
    (out_dir / f"variant-{variant_index + 1}-receipt.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    return receipt


def make_thumbnail_experiment(package_path: Path, *, tool: Any, artifact_roots: Iterable[Path],
                              poll_seconds: float = 30, max_wait_seconds: float = 1800,
                              sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Generate, score and retain three variants; promote only the winner to final.png."""
    package_path = Path(package_path)
    pkg = json.loads(package_path.read_text(encoding="utf-8"))
    from openjarvis.one_agents.youtube_channels import SONIA

    SONIA.validate_record(pkg)
    variants = experiment_variants(pkg["thumbnail"])
    pkg["thumbnail"]["variants"] = variants
    package_path.write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
    root = package_path.parent.parent
    history = thumbnail_history(root.parent, exclude=root)
    # Sonia's channel identity is now fixed: host on the right, short hook on
    # the left, and the truthful story USP protected in the centre. Variety
    # comes from portrait, expression and art direction—not mirrored hierarchy.
    layout = "right"
    portrait = pick_portrait(Path(pkg["thumbnail"]["portrait_library"]), pkg.get("recommended_title", ""),
                             [h["portrait"] for h in history])
    results = []
    for index, variant in enumerate(variants):
        result = make_thumbnail(package_path, tool=tool, artifact_roots=artifact_roots,
                                variant_index=index, poll_seconds=poll_seconds,
                                max_wait_seconds=max_wait_seconds, sleep=sleep, layout=layout, portrait=portrait)
        if result.get("ok"):
            saved = Path(result["path"])
            result["direction"] = {k: variant.get(k) for k in ("name", "posture", "gesture", "sonia_expression")}
            result["preupload_score"] = score_thumbnail(saved, result["qc"], variant)
        results.append(result)
    eligible = [r for r in results if r.get("ok") and r.get("preupload_score")]
    generated = [r for r in eligible if r.get("source") != "local_fallback"]
    # A local fallback is continuity insurance, not a creative winner. Its
    # simple geometry scored well on mechanical legibility while having no
    # story visual at all (Queen Suthida, 2026-10-10). Prefer any generated,
    # QC-passed candidate; use fallback only when generation produced none.
    if generated:
        eligible = generated
    if not eligible:
        # Never leave an older or failed final.png for the gate to upload.
        stale = root / "thumbnail" / "final.png"
        if stale.is_file():
            stale.replace(stale.with_name("final.rejected.png"))
        receipt = {"ok": False, "stage": "experiment", "variants": results, "layout": layout,
                   "portrait": str(portrait), "error": "none of the three thumbnail variants passed QC"}
    else:
        winner = max(eligible, key=lambda r: r["preupload_score"]["score"])
        final = root / "thumbnail" / "final.png"
        shutil.copyfile(winner["path"], final)
        receipt = {"ok": True, "path": str(final), "winner": winner["variant"], "layout": layout,
                   "portrait": str(portrait),
                   "winner_score": winner["preupload_score"], "variants": results,
                   "selection": "highest transparent pre-upload score; actual CTR requires YouTube Test & Compare"}
        from openjarvis.one_agents import youtube_thumbnail_ab
        receipt["native_ab_test"] = youtube_thumbnail_ab.build_plan(
            root, receipt, visibility="private", content_format=str(pkg.get("content_format") or "long_form"))
    (root / "thumbnail" / "thumbnail-experiment.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "thumbnail" / "thumbnail-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return receipt
