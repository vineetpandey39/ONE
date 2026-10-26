"""Face-obscured biography direction. Automated detection is screening, not editorial approval."""
from __future__ import annotations

from pathlib import Path
from typing import Any

# Calibrated 2026-10-22 on the 27 quarantined Virat frames: at 7% of the frame width the detector flagged 11 of the
# 12 side-profile/portrait shots and none of the wide, equipment or rear shots (stadium crowds stay below it).
FACE_MIN_FRACTION = 0.07

# A vocabulary, not a five-shot template.  The old implementation emitted the
# same wide/shoulder/hands/over-shoulder/walk cycle for every chapter; a 75-shot
# episode consequently looked like five pictures repeated fourteen times.
COVERAGE = (
    "establishing_wide", "dynamic_action", "equipment_macro", "environmental_pov",
    "obscured_side_action", "low_angle", "overhead", "reflection", "crowd_reaction",
    "document_or_score_evidence", "team_context", "travel_context", "feet_detail",
    "behind_stumps", "quiet_aftermath",
)
MOTION = ("slow_push", "lateral_drift", "focus_detail", "slow_pullback", "wide_hold")

_DIRECTIONS = {
    "establishing_wide": "Wide period establishing view of {place}; environment leads the frame; no identifiable athlete",
    "dynamic_action": "Dynamic faceless action at {place}: {action}; body mechanics and equipment contact physically correct",
    "equipment_macro": "Macro still-life of {object}; period wear and texture visible; no face or generic bat-grip repeat",
    "environmental_pov": "First-person environmental POV at {place}, using {object} as foreground story evidence; no face",
    "obscured_side_action": "Side action angle with the entire face hidden by helmet, deep shadow or crop: {action}; {look}",
    "low_angle": "Ground-level low angle showing {action}, feet, surface and scale; head turned completely away; {look}",
    "overhead": "High overhead composition mapping {place}, subject small and face unreadable, action: {action}",
    "reflection": "Oblique reflection in glass, rain or polished equipment; facial detail impossible; {place}; {look}",
    "crowd_reaction": "Reaction-led frame from spectators or teammates while the faceless subject remains distant at {place}",
    "document_or_score_evidence": "Graphic-ready factual insert of {evidence}; historically accurate object or scoreboard, no invented text",
    "team_context": "Team-context tableau around {action}; subject seen from rear or fully occluded, distinct body poses, {look}",
    "travel_context": "Period-accurate journey or transition through {place}; luggage or equipment tells the story; face hidden",
    "feet_detail": "Close detail of period footwear, crease or ground during {action}; anatomically correct stance, no face",
    "behind_stumps": "Behind-stumps view of {action}; wicketkeeping/batting equipment correct, face fully blocked by helmet or crop",
    "quiet_aftermath": "Quiet aftermath at {place}: empty space, used {object}, or distant rear silhouette carries the consequence",
}

FACELESS_RULES = (
    "The subject's face is never visible: no frontal view, no profile showing eyes, nose or mouth; the head is turned "
    "away from camera, cropped out of frame, or in deep shadow. Recognition comes only from the signature details "
    "given. No logos, crests, sponsor marks, signatures or watermark; the only text allowed is the shirt number "
    "or documented jersey name stated. Never add a modern number/name to an era without evidence. "
    "Use rear views, over-shoulder views, silhouettes, torso, equipment, hands, feet, environmental POV or "
    "reflections without facial detail. Side angles are allowed only with the face fully obscured. "
    "Keep every athlete portrayal dignified: no close or medium rear-body composition and no camera emphasis on "
    "the back, hips, chest, thighs or body shape; use distant full-body action, neutral upper-torso crops, equipment "
    "occlusion, court geography and action mechanics instead. "
    "Cricket anatomy and bat grip physically correct, no extra fingers or twisted wrists.")


def visual_specs(chapter: dict[str, Any]) -> list[dict[str, str]]:
    """Return five chapter-specific directions with rotating camera grammar.

    Editors can supply ``visual_beats`` (five sourced actions/objects) and
    ``coverage`` (five types).  Otherwise the chapter number rotates through
    the full vocabulary instead of resetting to the same five shots.
    """
    era, look = chapter["era"], signature(chapter)
    place = chapter.get("place_detail") or f"historically appropriate setting of {era}"
    chapter_no = int(chapter.get("chapter", chapter.get("chapter_number", 1)))
    requested = chapter.get("coverage")
    offset = (chapter_no - 1) % len(COVERAGE)
    if requested is not None:
        if len(requested) != 5 or any(kind not in COVERAGE for kind in requested):
            raise ValueError("chapter coverage must contain five valid, distinct visual types")
        kinds = list(requested)
    else:
        kinds = [COVERAGE[(offset + i * 3) % len(COVERAGE)] for i in range(5)]
    if len(set(kinds)) != 5:
        raise ValueError("a chapter cannot repeat a visual type")
    beats = chapter.get("visual_beats") or []
    defaults = [chapter.get("action") or "the documented chapter action"] * 5
    actions = [str(beats[i]) if i < len(beats) else defaults[i] for i in range(5)]
    objects = chapter.get("story_objects") or [chapter.get("equipment") or chapter.get("kit") or "period equipment"]
    evidence = chapter.get("evidence_visual") or "the chapter's sourced date, score, record or period document"
    specs = []
    for i, kind in enumerate(kinds):
        text = _DIRECTIONS[kind].format(place=place, action=actions[i], object=objects[i % len(objects)],
                                         evidence=evidence, look=look)
        specs.append({"shot_type": kind, "visual": text, "motion": MOTION[(offset + i) % len(MOTION)]})
    return specs


def visuals(chapter: dict[str, Any]) -> list[str]:
    """Compatibility wrapper returning five diversified visual strings."""
    return [item["visual"] for item in visual_specs(chapter)]

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
