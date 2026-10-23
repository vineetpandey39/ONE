"""Face-obscured biography direction. Automated detection is screening, not editorial approval."""
from __future__ import annotations

from pathlib import Path
from typing import Any

# Calibrated 2026-10-22 on the 27 quarantined Virat frames: at 7% of the frame width the detector flagged 11 of the
# 12 side-profile/portrait shots and none of the wide, equipment or rear shots (stadium crowds stay below it).
FACE_MIN_FRACTION = 0.07

COVERAGE = ("establishing_wide", "shoulder_side", "hands_equipment", "over_shoulder", "rear_walk")
MOTION = ("slow_push", "lateral_drift", "focus_detail", "slow_pullback", "wide_hold")

FACELESS_RULES = (
    "The subject's face is never visible: no frontal view, no profile showing eyes, nose or mouth; the head is turned "
    "away from camera, cropped out of frame, or in deep shadow. Recognition comes only from the signature details "
    "given. No logos, crests, sponsor marks, signatures or watermark; the only text allowed is the shirt number "
    "or documented jersey name stated. Never add a modern number/name to an era without evidence. "
    "Use rear views, over-shoulder views, silhouettes, torso, equipment, hands, feet, environmental POV or "
    "reflections without facial detail. Side angles are allowed only with the face fully obscured. "
    "Cricket anatomy and bat grip physically correct, no extra fingers or twisted wrists.")


def visuals(chapter: dict[str, Any]) -> list[str]:
    """Five faceless shots for one chapter, in COVERAGE order."""
    era, look = chapter["era"], signature(chapter)
    place = chapter.get("place_detail") or f"historically appropriate cricket venue of {era}"
    return [
        f"Wide establishing view of {place}; no identifiable athlete",
        f"Side view from behind the subject's right shoulder, face turned away toward the field; {look}",
        f"Close-up of the subject's gloved hands on the bat handle and wristband, no face in frame; {chapter['kit']}",
        f"Over-the-shoulder from behind: back of the head and shoulders, looking out at {place}; {look}",
        f"Rear view walking toward the middle, cinematic wide perspective; {look}",
    ]


def signature(chapter: dict[str, Any]) -> str:
    """The era's recognisable details, all visible without a face."""
    parts = [chapter["kit"], chapter["hair"], chapter.get("beard") or "", chapter.get("hand") or ""]
    return ", ".join(p for p in parts if p)


def prompt(shot_id: str, visual: str, chapter: dict[str, Any], subject: str) -> str:
    return (f"Create ONE full-frame 16:9 photoreal cinematic CGI biography scene, original illustrative "
            f"reconstruction, NOT 2D, NOT collage. {shot_id}: {visual}. Episode subject {subject}; age "
            f"{chapter['age']}, {chapter['era']}. {FACELESS_RULES} Period-appropriate clothing, buildings and "
            f"equipment. No archival claim. Output one widescreen image.")


def thumbnail_prompt(subject: str, look: str, headline: str) -> str:
    return (f"Cinematic photoreal CGI biography thumbnail, 16:9. {subject} seen from behind under stadium lights, "
            f"walking out to bat, face never visible; {look}. Huge floodlit crowd ahead, strong simple composition. "
            f"{FACELESS_RULES} Large readable headline only: {headline}.")


def visible_faces(image: Path, min_fraction: float = FACE_MIN_FRACTION) -> list[dict[str, Any]]:
    """Prominent faces in a frame (frontal or either profile), CPU only. Crowd faces fall below min_fraction."""
    import cv2
    img = cv2.imread(str(image))
    if img is None:
        raise ValueError(f"Unreadable frame: {image}")
    gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    side = int(img.shape[1] * min_fraction)
    found = []
    for kind, cascade in (("frontal", "haarcascade_frontalface_alt2.xml"), ("profile", "haarcascade_profileface.xml")):
        detector = cv2.CascadeClassifier(cv2.data.haarcascades + cascade)
        for flipped in ((False, True) if kind == "profile" else (False,)):
            frame = cv2.flip(gray, 1) if flipped else gray
            for (x, y, w, h) in detector.detectMultiScale(frame, 1.1, 6, minSize=(side, side)):
                found.append({"kind": kind, "width": int(w), "x": int(x), "y": int(y)})
    return found


def reject_faces(plan: list[dict[str, Any]], rejected_dir: Path) -> list[dict[str, Any]]:
    """Move every generated frame that shows a face out of the plan's image path, so the next batch regenerates it."""
    rejected = []
    for shot in plan:
        image = Path(shot["image"])
        if not image.is_file():
            continue
        faces = visible_faces(image)
        if faces:
            rejected_dir.mkdir(parents=True, exist_ok=True)
            target = rejected_dir / f"{image.stem}-face-{len(list(rejected_dir.glob(image.stem + '-face-*')))+1}{image.suffix}"
            image.replace(target)
            rejected.append({"shot_id": shot["shot_id"], "moved_to": str(target), "faces": faces})
    return rejected


def enforce_prompt(text: str) -> str:
    """Enforce channel policy at every provider boundary, including old callers."""
    return str(text).rstrip() + "\nMANDATORY CAMERA RULE (overrides any portrait/likeness instruction above): " + FACELESS_RULES


def scene_qa(image: Path, *, age, era, reviewer=None) -> dict:
    """A detector negative cannot certify hidden identity, anatomy or historical detail."""
    import hashlib
    findings = visible_faces(image)
    checks = reviewer or {}
    required = ("face_obscured", "anatomy", "historical_accuracy")
    return {"image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "age": age, "era": era,
            "detected_faces": findings, "screening": "rejected" if findings else "no_face_detected",
            "editorial_status": "passed" if not findings and all(checks.get(k) is True for k in required)
                and age is not None and era else "review_required",
            "visual_checks": {k: checks.get(k) for k in required}}
