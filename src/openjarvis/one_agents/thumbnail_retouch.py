"""Finish Sonia on a thumbnail background with identity-safe natural skin cleanup.

The channel standard: temporary acne should be softened without changing Sonia's identity. ChatGPT may copy spots
from the reference photo, so compact blemish cleanup is done here deterministically and identity-safely:

  - clear skin: inside each detected face, an edge-preserving smoothing is blended in. Spots and uneven texture
    soften, while eyes, brows, lips and the face's outline (strong edges) stay as they are;
  - no automatic glow: the old silhouette glow could become a white veil around Sonia or her hand. Subject
    separation now belongs to the generated lighting and composition, never a post-process white layer.

Each step is skipped, and says so, when its model or detector is missing: a thumbnail is never refused for a retouch.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

MODEL = Path(os.environ.get("ONE_ISNET_MODEL") or r"E:\ONE-Suite\data\models\isnet-general-use.onnx")
_SESSION: Any = None


def subject_mask(image: Image.Image) -> Image.Image | None:
    """Sonia's silhouette as an L mask (255 = her), or None when the matting model is unavailable."""
    global _SESSION
    if not MODEL.is_file():
        return None
    try:
        import numpy as np
        import onnxruntime as ort
        if _SESSION is None:
            _SESSION = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])  # never the GPU
        small = np.asarray(image.convert("RGB").resize((1024, 1024), Image.LANCZOS), dtype=np.float32)
        small = small / max(float(small.max()), 1e-6) - 0.5
        tensor = small.transpose(2, 0, 1)[None].astype(np.float32)
        pred = _SESSION.run(None, {_SESSION.get_inputs()[0].name: tensor})[0][0, 0]
        pred = (pred - pred.min()) / max(float(pred.max() - pred.min()), 1e-6)
        mask = Image.fromarray((pred * 255).astype("uint8"), mode="L").resize(image.size, Image.LANCZOS)
        return mask.point(lambda v: 0 if v < 40 else v)
    except Exception:  # noqa: BLE001 - a missing or broken model only skips the glow
        return None


def faces(image: Image.Image) -> list[tuple[int, int, int, int]]:
    try:
        import cv2
        import numpy as np
        detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
        found = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(60, 60))
        return sorted((tuple(int(v) for v in f) for f in found), key=lambda f: -f[3])[:1]
    except Exception:  # noqa: BLE001
        return []


def _feature_mask(size: tuple[int, int], face: tuple[int, int, int, int]) -> Image.Image:
    """Protect identity-bearing eyes, brows, nostrils and lips, but not cheek blemishes."""
    x, y, w, h = face
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((x + .10*w, y + .18*h, x + .90*w, y + .48*h), radius=max(4, w // 30), fill=255)
    draw.ellipse((x + .35*w, y + .43*h, x + .65*w, y + .67*h), fill=210)
    draw.rounded_rectangle((x + .34*w, y + .66*h, x + .66*w, y + .86*h), radius=max(4, w // 26), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(max(2, w // 80)))


def clear_skin(image: Image.Image, strength: float = 0.82) -> tuple[Image.Image, int]:
    """Remove compact temporary spots without smoothing intact facial texture."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return image, 0
    boxes = faces(image)
    if not boxes:
        return image, 0
    rgb = np.asarray(image.convert("RGB"))
    feature_pil = _feature_mask(image.size, boxes[0])
    feature_arr = np.asarray(feature_pil)
    # Remove compact dark/red blemishes against the local skin tone before
    # smoothing.  Feature zones are excluded, so eyes, brows, nostrils and
    # lips cannot be mistaken for acne.
    skin = np.zeros(rgb.shape[:2], dtype=np.uint8)
    for x, y, w, h in boxes:
        cv2.ellipse(skin, (x + w // 2, y + int(h * .56)),
                    (int(w * .47), int(h * .55)), 0, 0, 360, 255, -1)
        skin[y + int(h * .76):, :] = 0  # a hand may overlap the lower face
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    skin_colour = (
        (ycrcb[..., 0] > 55) & (ycrcb[..., 1] >= 128) & (ycrcb[..., 1] <= 190)
        & (ycrcb[..., 2] >= 72) & (ycrcb[..., 2] <= 138)
    )
    skin[~skin_colour] = 0
    skin[feature_arr > 48] = 0
    local = cv2.medianBlur(rgb, 21)
    dark_delta = local.mean(axis=2) - rgb.mean(axis=2)
    red_delta = rgb[..., 0].astype(np.float32) - (
        rgb[..., 1].astype(np.float32) + rgb[..., 2].astype(np.float32)
    ) / 2.0
    local_red_delta = local[..., 0].astype(np.float32) - (
        local[..., 1].astype(np.float32) + local[..., 2].astype(np.float32)
    ) / 2.0
    red_anomaly = red_delta - local_red_delta
    blemish = np.where(
        (skin > 0) & (dark_delta > 4.0) & ((red_anomaly > 1.5) | (dark_delta > 12.0)), 255, 0
    ).astype(np.uint8)
    blemish = cv2.morphologyEx(blemish, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    blemish = cv2.dilate(blemish, np.ones((5, 5), np.uint8), iterations=1)
    corrected = cv2.inpaint(rgb, blemish, 4, cv2.INPAINT_TELEA)
    # Never blur the whole face.  The previous median+bilateral+Gaussian stack
    # turned natural skin into the white beauty-filter patch visible on mobile.
    # Feather only the compact pixels classified as blemishes; every other skin
    # pixel, including pores and natural tonal variation, remains byte-for-byte
    # from the generated base image.
    area = Image.fromarray(blemish, mode="L").filter(
        ImageFilter.GaussianBlur(max(1, boxes[0][2] // 180))
    ).point(lambda v: int(v * strength))
    cleared = Image.composite(Image.fromarray(corrected), image.convert("RGB"), area)
    return Image.composite(cleared, image.convert("RGB"), feature_pil), len(boxes)


def natural_face_finish(image: Image.Image, face: tuple[int, int, int, int] | None,
                        lift: float = 1.025, warmth: float = 1.008) -> Image.Image:
    """Apply identity-safe face lighting and subtle natural makeup toning."""
    if not face:
        return image
    x, y, w, h = face
    lifted = ImageEnhance.Brightness(image).enhance(lift)
    lifted = ImageEnhance.Contrast(lifted).enhance(1.025)
    r, g, b = lifted.split()
    lifted = Image.merge("RGB", (
        r.point(lambda v: min(255, int(v * warmth))),
        g,
        b.point(lambda v: max(0, int(v * 0.985))),
    ))
    area = Image.new("L", image.size, 0)
    ImageDraw.Draw(area).ellipse(
        (x - .06*w, y - .04*h, x + 1.06*w, y + 1.12*h), fill=92
    )
    area = area.filter(ImageFilter.GaussianBlur(max(8, w // 10)))
    return Image.composite(lifted, image, area)


def under_eye_boxes(image: Image.Image, face: tuple[int, int, int, int]) -> list[tuple[int, int, int, int]]:
    """The skin just below each eye: detected eyes inside the face, else where eyes sit on a face."""
    x, y, w, h = face
    eyes: list[tuple[int, int, int, int]] = []
    try:
        import cv2
        import numpy as np
        detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
        top = np.asarray(image.convert("L").crop((x, y, x + w, y + int(h * 0.6))))
        found = detector.detectMultiScale(top, scaleFactor=1.1, minNeighbors=8, minSize=(w // 10, w // 10))
        eyes = sorted(((ex + x, ey + y, ew, eh) for ex, ey, ew, eh in found), key=lambda e: -e[2])[:2]
    except Exception:  # noqa: BLE001
        eyes = []
    if len(eyes) != 2:
        eyes = [(x + int(w * 0.17), y + int(h * 0.30), int(w * 0.28), int(h * 0.18)),
                (x + int(w * 0.55), y + int(h * 0.30), int(w * 0.28), int(h * 0.18))]
    # From just under the lower lid to the top of the cheek; the eye itself is never touched.
    return [(ex - int(ew * 0.05), ey + int(eh * 0.68), int(ew * 1.1), int(eh * 0.8)) for ex, ey, ew, eh in eyes]


def brighten_under_eyes(image: Image.Image, face: tuple[int, int, int, int] | None,
                        lift: float = 1.06, strength: float = 0.32) -> Image.Image:
    """Lift the dark circles under her eyes (the Chairman, 2026-10-09) with a soft, warm local brightening."""
    if not face:
        return image
    lighter = ImageEnhance.Brightness(image).enhance(lift)
    r, g, b = lighter.split()  # dark circles read blue-grey; trimming a little blue evens them with the cheek
    lighter = Image.merge("RGB", (r, g, b.point(lambda v: int(v * 0.985))))
    area = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(area)
    for bx, by, bw, bh in under_eye_boxes(image, face):
        draw.ellipse((bx, by, bx + bw, by + bh), fill=int(255 * strength))
    area = area.filter(ImageFilter.GaussianBlur(max(4, face[2] // 28)))
    return Image.composite(lighter, image, area)


def fill_holes(solid: Image.Image) -> Image.Image:
    """Only her outer edge gets the rim. The matte left gaps inside a raised palm (Air France, 2026-10-09) and the
    rim was drawn inside her hand as white blotches; filling every enclosed gap keeps the glow on the outside."""
    try:
        import cv2
        import numpy as np
        arr = np.asarray(solid)
        contours, _ = cv2.findContours(arr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros_like(arr)
        cv2.drawContours(filled, contours, -1, 255, thickness=-1)
        return Image.fromarray(filled)
    except Exception:  # noqa: BLE001 - without OpenCV, close small gaps instead
        return solid.filter(ImageFilter.MaxFilter(15)).filter(ImageFilter.MinFilter(15))


def sonia_only(mask: Image.Image, face: tuple[int, int, int, int] | None) -> Image.Image:
    """The part of the matte that is Sonia: the connected region holding her face, solid and without holes.

    The matte marks everything salient. On the Air France thumbnail that included the plane, which got its own
    glow, and her raised palm came out half-transparent, so a 50% cut ran through her hand. A low cut keeps the
    whole hand, and only the region joined to her face is kept, so the plane is dropped."""
    solid = mask.point(lambda v: 255 if v >= 48 else 0)
    try:
        import cv2
        import numpy as np
        arr = np.asarray(solid)
        count, labels = cv2.connectedComponents(arr)
        if count > 2:
            if face:
                x, y, w, h = face
                keep = labels[min(arr.shape[0] - 1, y + h // 2), min(arr.shape[1] - 1, x + w // 2)]
            else:
                sizes = [(labels == i).sum() for i in range(1, count)]
                keep = 1 + int(np.argmax(sizes))
            if keep:
                solid = Image.fromarray(np.where(labels == keep, 255, 0).astype("uint8"))
    except Exception:  # noqa: BLE001
        pass
    return fill_holes(solid)


def outline_glow(image: Image.Image, mask: Image.Image, *, spread: int = 34, strength: float = 0.75,
                 colour: tuple[int, int, int] = (255, 244, 225),
                 face: tuple[int, int, int, int] | None = None) -> Image.Image:
    """A soft light glow behind her silhouette, fading into the background; no drawn line, and she is untouched.

    The first version drew a crisp white rim. The Chairman (2026-10-09): it looked like a white layer, most of all
    where it crossed her hand, and earlier thumbnails had a glow, not an outline. The glow is now light, not paint:
    a blurred silhouette screen-blended onto the background, so it brightens what is behind her instead of covering
    it."""
    solid = sonia_only(mask, face)
    halo = solid.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(spread))
    halo = ImageChops.subtract(halo, solid).point(lambda v: int(min(255, v * 1.6) * strength))
    # Where she is cut by the frame (a hand at the edge), the matte misses her and the glow lit her own skin as a
    # white patch. The glow fades out near the frame edges, where it has nothing to separate her from anyway.
    edge = max(24, image.width // 18)
    fade = Image.new("L", image.size, 255)
    draw = ImageDraw.Draw(fade)
    for i in range(edge):
        level = int(255 * i / edge)
        draw.rectangle((i, i, image.width - 1 - i, image.height - 1 - i), outline=level)
    halo = ImageChops.multiply(halo, fade)
    light =Image.composite(Image.new("RGB", image.size, colour), Image.new("RGB", image.size, (0, 0, 0)), halo)
    glowing = ImageChops.screen(image.convert("RGB"), light)
    return Image.composite(image.convert("RGB"), glowing, solid.filter(ImageFilter.GaussianBlur(1.0)))


def retouch(base: Path, out: Path) -> dict[str, Any]:
    """Clear compact blemishes and lightly balance the face; never add a white glow or face-wide blur."""
    image = Image.open(base).convert("RGB")
    found = faces(image)
    image, face_count = clear_skin(image)
    image = brighten_under_eyes(image, found[0] if found else None)
    image = natural_face_finish(image, found[0] if found else None)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, "PNG", optimize=True)
    return {
        "path": str(out),
        "skin_cleared_faces": face_count,
        "face_lighting": bool(found),
        "natural_makeup": bool(found),
        "glow": False,
    }
