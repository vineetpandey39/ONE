"""Universal prompt templates for the Punarnirman restoration-reel engine.

Generates the fixed 5-frame master-prompt set and 4-clip continuity-prompt
set for ANY location, rather than requiring a hand-written JSON file per
city. Two templates are supported via ``location["type"]``:

  "water" -- river/drain/lake-style locations (Yamuna, Mithi, Cooum, ...).
             Tracks a water-color progression: black -> brown -> blue-green.
  "land"  -- slum lane / dumping-ground-style locations with no water body.
             Tracks a ground/structure-condition progression instead:
             trash-strewn/dilapidated -> cleared/repaired.

Shared structural rules (kept identical across both templates, matching the
original Selampur master-prompt architecture): locked tilted-oblique drone
angle (~35-45 degrees downward, looking lengthwise down the corridor toward
the horizon -- not straight-down nadir), fixed camera direction/composition
across all 5 frames, lighting progression overcast -> golden hour, color
progression desaturated -> vibrant, photorealistic drone cinematography only
(never illustrated / cartoon / painted), 9:16 vertical, worker-count arc
0 -> 400 -> 800 -> 400 -> 0, and -- for the clips -- continuous, gradual,
labor/machine-driven change only (never an instant "magic" transformation).
Frames 2-4 (and clips A-D) are deliberately written dense with workers, heavy
machinery, and refinery/processing-plant-style equipment throughout -- a
sparse-looking crew reads as "nothing is happening" in the final timelapse,
so every frame/clip from frame 2 onward keeps the scene visibly packed with
people and machines until the taper in frame 5.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# Shared photographic-quality language, independent of which camera/framing
# strategy (see _CAMERA_STYLES below) a given location's "scene" tag uses.
_PHOTO_QUALITY = (
    "Photorealistic drone cinematography only -- NOT illustrated, NOT cartoon,"
    " NOT painting, NOT 3D render. Shot on a real consumer drone (DJI Mavic 3"
    " Pro-style). 9:16 vertical composition, sharp focus, real-world texture"
    " and detail, true photographic grain -- not smooth or artificial-looking."
)

# Camera/framing strategy, keyed by ``location["scene"]``. Every location
# gets exactly ONE of these for its entire 5-frame sequence -- frame 1 states
# it explicitly, frames 2-5 inherit it implicitly because they're generated
# as image-edits of frame 1 (same pixels, same locked shot). The point is
# variety ACROSS different runs/locations, never variety within one run:
# whichever style a given reel uses stays identical across all 5 frames so
# the timelapse reads as one continuous, locked camera watching restoration
# happen -- that's what makes people stay and watch the workforce/machinery
# build up, not the camera moving around.
_CAMERA_STYLES = {
    # Default: narrow drains, slum lanes, generic urban waterways with no
    # standout landmark -- the original locked lengthwise-corridor shot.
    "corridor": (
        "Tilted oblique aerial view -- NOT a straight-down nadir shot. Camera"
        " angled downward at roughly 35-45 degrees from horizontal, positioned"
        " at one end of the water/ground corridor and looking lengthwise"
        " straight down its full length, so the corridor recedes into the"
        " distance toward a visible horizon/skyline rather than being seen"
        " from directly overhead -- matching real oblique drone footage that"
        " shows depth and a horizon line, not a flat top-down map view."
        " Moderate altitude, enough height to take in the full corridor depth"
        " and the skyline beyond it. The water/ground body runs straight down"
        " the vertical center of the frame from the near foreground to the"
        " horizon, with the banks, walkways, and buildings lining both sides"
        " symmetrically and receding into the distance in forced perspective,"
        " open sky visible in the upper portion of the frame."
    ),
    # Temple-lined river ghats (stepped riverfronts): shoot ACROSS the river
    # at the ghat face instead of lengthwise down it, so temple spires read
    # on the skyline instead of disappearing into a top-down view.
    "ghat": (
        "Tilted oblique aerial view, NOT a straight-down nadir shot, lower"
        " altitude than a wide establishing shot -- camera positioned out"
        " over the water looking back across the river at the ghat"
        " embankment and temple skyline, not lengthwise down a corridor."
        " Stone steps descend from the temple/building line down into the"
        " water, filling the lower-to-mid frame; temple spires, shikharas,"
        " and domes are clearly silhouetted against the sky in the upper"
        " portion of the frame rather than being lost looking straight down."
        " The water occupies the foreground, the ghat steps and buildings"
        " the middle ground, and the temple skyline the background."
    ),
    # A lake/river/ground area beside a fort, mosque, or other heritage
    # monument: the monument itself is the hero of the frame, not the water.
    "monument": (
        "Tilted oblique aerial view, NOT a straight-down nadir shot, slightly"
        " higher altitude wide establishing shot -- camera positioned to"
        " capture the full facade of the monument/heritage structure, placed"
        " prominently off-center (rule of thirds) rather than dead-center,"
        " with the polluted water/ground body occupying the rest of the"
        " frame in front of or beside it. The monument's architecture is"
        " clearly readable, not distant or cropped out of frame."
    ),
    # Polluted beaches/coastlines: follow the natural curve of the shore
    # instead of forcing a straight corridor onto open coastline.
    "coast": (
        "Tilted oblique aerial view, NOT a straight-down nadir shot, lower"
        " angle following the natural curve of the coastline rather than a"
        " straight corridor -- the shoreline sweeps diagonally through the"
        " frame from near foreground to the distant horizon, open sea"
        " visible on one side, polluted beach/tideline debris visible along"
        " the curve of the shore."
    ),
    # A drain/river/ground corridor crossed by a major bridge, flyover, or
    # rail line: anchor the shot on that structure as the landmark.
    "infra": (
        "Tilted oblique aerial view, NOT a straight-down nadir shot, similar"
        " to a corridor shot but anchored on a recognizable bridge, flyover,"
        " or rail line crossing the water/ground corridor -- the structure"
        " spans the frame as a clear landmark, camera positioned slightly"
        " higher to take in the full span of the crossing along with the"
        " corridor receding toward the horizon beyond it."
    ),
}

_CLIP_CAMERA_LOCK = {
    "corridor": "looking lengthwise down the corridor toward the horizon",
    "ghat": "looking back across the river at the temple-lined ghat embankment",
    "monument": "framing the monument's full facade prominently off-center",
    "coast": "following the curve of the coastline with open sea in frame",
    "infra": "anchored on the bridge/flyover/rail crossing spanning the corridor",
}

# What the camera descends/pushes in toward during the dedicated finale clip
# (clip E, shot entirely after restoration is complete). Generic per scene
# type -- this is NOT specific to any one location or landmark (e.g. not
# hardcoded to "the Gateway of India" or any other named place); whichever
# scene tag a given run uses just maps to its own natural focal point.
_CLIP_DESCENT_TARGET = {
    "corridor": "down toward the restored corridor and its clean banks/walkways",
    "ghat": "down toward the restored ghat steps and the temple-lined embankment",
    "monument": "toward the monument/heritage structure's facade, to showcase its restored detail",
    "coast": "down toward the restored shoreline and clean tideline",
    "infra": "toward the bridge/flyover/rail crossing and the clean corridor beneath it",
}


def _base_rules(scene: str) -> str:
    style = _CAMERA_STYLES.get(scene, _CAMERA_STYLES["corridor"])
    return f"{_PHOTO_QUALITY} {style}"

# Used only for frame 1, which is a fresh text-to-image generation and so
# needs the full framing spec stated explicitly.
_LOCK_NOTE = (
    " This is frame 1 of a 5-frame sequence -- establish a clear, well-framed"
    " shot, since frames 2-5 will be generated as edits of this exact image to"
    " stay visually locked to it."
)

# Used for frames 2-5, which are generated via image-edit using frame 1 as
# the input image -- the camera lock comes from editing the same pixels,
# not from re-describing the composition, so the instruction here is about
# what to change, not the shot itself.
_EDIT_PREFIX = (
    "Using the provided reference image as the exact starting point, keep"
    " the identical camera position, altitude, angle, composition, framing,"
    " and crop -- do not change the shot in any way. CRITICAL: every"
    " existing building, monument, temple, tower, minaret, dome, arch,"
    " bridge, and other fixed structure already visible in the reference"
    " image must remain pixel-for-pixel identical -- same shape, same"
    " number of towers/domes/arches, same proportions, same position. Do"
    " NOT redesign, distort, resize, add, remove, or move any part of the"
    " architecture. Apply ONLY the following changes to the water/ground/"
    " people/vehicles in front of or around that fixed architecture: "
)

# Negative constraints appended to every still-image prompt (frame 1 fresh
# generation and frames 2-5 edits alike) -- gpt-image has no separate
# negative_prompt parameter, so exclusions have to be stated in-line.
_NEGATIVE_IMAGE = (
    " Do not produce: cartoon or illustrated style, painting, 3D render,"
    " warped or distorted architecture, extra or missing towers/domes/"
    " minarets, mismatched building proportions, melted or duplicated"
    " structures, blurry or low-resolution upscale artifacts, watermarks,"
    " logos, text overlays, deformed people, duplicated limbs or faces."
)

_COLOR_GRADE = (
    "Color grading: rich, punchy, magazine-quality color -- well-balanced"
    " exposure with deep but detail-retaining shadows and clean,"
    " non-blown highlights. Strong, natural contrast (not flat or hazy)."
    " Saturation and vividness pushed slightly above neutral so colors feel"
    " alive without looking oversaturated or artificial. Accurate, pleasing"
    " hue rendering -- true greens, true blues, warm skin-toned earth and"
    " skin tones where people are visible. Balanced midtones with no muddy"
    " or washed-out gray areas. Overall a vibrant, high-production-value"
    " cinematic drone-photography look."
)

_SUBSTANCE = {
    "water": {
        1: "black, heavily polluted water choked with visible trash along the banks",
        2: (
            "still mostly black water, but the banks are now lined wall-to-wall"
            " with a large, dense workforce in high-visibility vests and helmets,"
            " dozens of trucks, excavators, and cranes, plus a temporary"
            " refinery-style water-treatment setup (pipes, tanks, filtration"
            " pumps) already being assembled along the shore -- the scene reads"
            " as a full-scale industrial restoration operation, not a few"
            " workers"
        ),
        3: (
            "water turning brown from disturbed sediment as a dense fleet of"
            " heavy machinery -- excavators, dredgers, cranes, tanker trucks, and"
            " floating dredge barges -- works the water at full force, the bank"
            " packed end to end with a massive workforce and a refinery-like"
            " bank of treatment tanks, pipes, and pumps running at peak"
            " industrial-scale capacity"
        ),
        4: (
            "a literal split-screen composition down the middle of the frame:"
            " one half (same camera, same water body, just one section of it)"
            " is fully transformed already -- blue-green clean water, tidy"
            " cleared bank, golden-hour light -- while the other half is"
            " still mid-operation -- brown/dirty water, dense workers and"
            " heavy machinery, refinery-style treatment rig still running."
            " The dividing line between the two halves is clear and visible"
            " in-frame (a natural break point like a bridge, bend in the"
            " river, or boundary wall), making the before/after contrast"
            " unmistakable in a single shot"
        ),
        5: "fully blue-green, clean water across the full width, banks cleared of debris",
    },
    "land": {
        1: "ground strewn with trash and debris, dilapidated structures, no workers present",
        2: (
            "trash and debris still present, but the area is now packed with a"
            " large, dense workforce in high-visibility vests and helmets, dozens"
            " of trucks, excavators, and cranes, plus a temporary"
            " refinery/processing-plant-style setup (sorting conveyors, holding"
            " tanks, pipework) already being assembled on site -- the scene reads"
            " as a full-scale industrial restoration operation, not a few"
            " workers"
        ),
        3: (
            "a dense fleet of heavy machinery -- excavators, bulldozers, cranes,"
            " and tanker/dump trucks -- actively clearing debris and repairing"
            " structures, the ground packed end to end with a massive workforce"
            " and a refinery-like bank of processing equipment, pipes, and tanks"
            " running at peak industrial-scale capacity"
        ),
        4: (
            "a literal split-screen composition down the middle of the frame:"
            " one half (same camera, same area, just one section of it) is"
            " fully transformed already -- cleared, repaired, tidy ground,"
            " golden-hour light -- while the other half is still"
            " mid-operation -- trash-strewn ground, dense workers and heavy"
            " machinery, refinery/processing-plant-style rig still running."
            " The dividing line between the two halves is clear and visible"
            " in-frame (a natural break point like a wall, road, or structure"
            " boundary), making the before/after contrast unmistakable in a"
            " single shot"
        ),
        5: "fully cleared, repaired, and tidy ground across the whole area",
    },
}

_LIGHT = {
    1: "7:00 AM, overcast lighting, desaturated color palette",
    2: "late morning, overcast lighting beginning to break",
    3: "2:00 PM, brighter lighting transitioning toward golden hour",
    4: "5:00 PM, golden hour lighting, color shifting from desaturated to vibrant",
    5: "golden hour lighting, fully vibrant color palette",
}

_WORKERS = {
    1: "no workers present",
    2: "roughly 400 workers present, dense and continuous across the full frame",
    3: "roughly 800 workers present, peak activity, the largest crowd of the sequence",
    4: "worker count tapering from 800 back toward 400, still a large, dense crew",
    5: "a small finishing crew remaining, near 0",
}

_FRAME_LABELS = {
    1: "Establish / Dirty Aerial Wide",
    2: "Workers Arrive",
    3: "Mid-Cleanup with Heavy Machinery",
    4: "Transition / Split Reveal",
    5: "After / Transformation",
}


def build_frame_prompts(location: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build the 5 fixed master-frame prompts for *location*."""
    loc_type = location.get("type", "water")
    substance = _SUBSTANCE.get(loc_type, _SUBSTANCE["water"])
    place = f"{location.get('area_name', '')}, {location.get('city', '')}".strip(", ")
    base_rules = _base_rules(location.get("scene", "corridor"))

    frames = []
    for i in range(1, 6):
        content = f"{_LIGHT[i]}. {substance[i]}. {_WORKERS[i]}."
        generate_prompt = (
            f"{base_rules} Aerial wide shot over {place}. {content}"
            f" {_COLOR_GRADE}{_LOCK_NOTE if i == 1 else ''}{_NEGATIVE_IMAGE}"
        )
        edit_prompt = f"{_EDIT_PREFIX}{content} {_COLOR_GRADE}{_NEGATIVE_IMAGE}"
        frames.append(
            {
                "id": i,
                "label": _FRAME_LABELS[i],
                "size": "1024x1792",
                # Used for frame 1 (fresh generation, no reference image).
                "prompt": generate_prompt,
                # Used for frames 2-5 (image-edit, conditioned on frame 1).
                "edit_prompt": edit_prompt,
            }
        )
    return frames


_CLIP_LABELS = {
    "A": "First Workers Hit the Ground",
    "B": "Machines Enter, Scale Explodes",
    "C": "The Slow Reveal — First Section Transforms",
    "D": "The Reveal — Same Workers Now Finishing Touches",
    "E": "The Payoff — Post-Restoration Descent",
}

_CLIP_BODY = {
    "water": {
        "A": (
            "A large, continuous wave of labor and equipment floods in throughout"
            " the clip -- hundreds of workers walk in, dozens of trucks, excavators"
            " and cranes roll in, and a refinery-style water-treatment rig (pipes,"
            " tanks, filtration pumps) is being assembled along the bank, building"
            " up to a dense, full-scale operation by the end of the clip, never a"
            " sparse or empty-looking bank. Water remains black/dirty the entire"
            " clip; lighting shifts gradually from overcast to brighter morning"
            " light."
        ),
        "B": (
            "A dense fleet of heavy machinery (excavators, dredgers, cranes,"
            " tanker trucks, floating dredge barges) enters and works continuously"
            " throughout the clip at full industrial scale; worker count visibly"
            " grows toward a packed, wall-to-wall peak crowd, with the"
            " refinery-style treatment tanks and pumps now fully online. Water"
            " gradually darkens/browns from disturbed sediment as machines work --"
            " no instantaneous color change. Lighting gradually brightens."
        ),
        "C": (
            "The dense workforce and full fleet of heavy machinery remain"
            " continuously visible and active throughout, gradually finishing the"
            " near bank first while still working the rest at full scale -- water"
            " and shoreline on that section visibly and gradually shift from brown"
            " toward blue-green as the large crew and machines visibly work it,"
            " while the rest of the frame is still a dense, full-scale mid-cleanup"
            " operation. Lighting gradually shifts toward golden hour."
        ),
        "D": (
            "The same large workforce seen earlier is now doing finishing touches"
            " -- still a dense, continuously visible crew, only gradually tapering"
            " in number as sections are completed and crews move out, never"
            " disappearing abruptly or looking sparse. Remaining water gradually"
            " shifts from brown/mixed to fully blue-green as the last of the heavy"
            " machinery and refinery-style equipment finishes its pass and is"
            " packed up. Lighting is warm golden hour throughout."
        ),
        "E": (
            "Restoration is fully complete -- the water is clean blue-green, the"
            " banks are clear and tidy, only a light, calm presence of people"
            " remains (strolling, sitting, a few finishing touches in the"
            " distance), no heavy machinery or dense crews left. Nothing in the"
            " scene itself changes during this clip -- it is the same fully"
            " restored moment held in warm golden-hour light, with the camera"
            " doing all the work."
        ),
    },
    "land": {
        "A": (
            "A large, continuous wave of labor and equipment floods in throughout"
            " the clip -- hundreds of workers walk in, dozens of trucks, excavators"
            " and cranes roll in, and a refinery/processing-plant-style rig"
            " (sorting conveyors, holding tanks, pipework) is being assembled on"
            " site, building up to a dense, full-scale operation by the end of the"
            " clip, never a sparse or empty-looking area. Ground remains untouched"
            " the entire clip; lighting shifts gradually from overcast to brighter"
            " morning light."
        ),
        "B": (
            "A dense fleet of heavy machinery (excavators, bulldozers, cranes,"
            " tanker/dump trucks) enters and works continuously throughout the"
            " clip at full industrial scale, clearing debris and beginning"
            " structural repairs; worker count visibly grows toward a packed,"
            " wall-to-wall peak crowd, with the refinery-style processing"
            " equipment now fully online. Piles of cleared debris gradually grow"
            " at the edge of frame -- no instantaneous change. Lighting gradually"
            " brightens."
        ),
        "C": (
            "The dense workforce and full fleet of heavy machinery remain"
            " continuously visible and active throughout, gradually finishing one"
            " section first while still working the rest at full scale -- that"
            " section visibly and gradually becomes tidy and repaired as the large"
            " crew and machines visibly work it, while the rest of the frame is"
            " still a dense, full-scale mid-cleanup operation. Lighting gradually"
            " shifts toward golden hour."
        ),
        "D": (
            "The same large workforce seen earlier is now doing finishing touches"
            " -- still a dense, continuously visible crew, only gradually tapering"
            " in number as sections are completed and crews move out, never"
            " disappearing abruptly or looking sparse. The remaining area"
            " gradually becomes fully cleared and tidy as the last of the heavy"
            " machinery and refinery-style equipment finishes its pass and is"
            " packed up. Lighting is warm golden hour throughout."
        ),
        "E": (
            "Restoration is fully complete -- the ground is clear, tidy, and"
            " repaired, only a light, calm presence of people remains"
            " (strolling, sitting, a few finishing touches in the distance), no"
            " heavy machinery or dense crews left. Nothing in the scene itself"
            " changes during this clip -- it is the same fully restored moment"
            " held in warm golden-hour light, with the camera doing all the"
            " work."
        ),
    },
}

_NEGATIVE_CLIP = (
    " Do not produce: warping, melting, or morphing of any building/monument/"
    " bridge/tower, flickering or strobing, sudden hard cuts, flash-frame"
    " artifacts, deformed or duplicated people, extra or merging limbs,"
    " distorted faces, or any cartoon/illustrated look -- photorealistic"
    " drone footage only."
)

# Appended to every A-D clip body (not the camera-only finale clip E, which
# has no worker/machine activity to begin with). Each clip only has 5
# seconds to depict a large amount of crowd/machinery change, and left
# unconstrained the video model compresses that into fast, sped-up motion --
# workers and machines blurring/smearing across frames -- which reads as
# low-quality or fake rather than a believable real-world restoration. This
# explicitly forces the opposite: real-world walking/operating speed, fully
# resolved (non-blurred) people and machinery throughout, even though a lot
# of large-scale change is still happening across the clip.
_MOTION_CLARITY = (
    " Every person and vehicle moves at a calm, real-world, natural pace --"
    " workers walk and work at normal human speed, machinery operates at its"
    " normal mechanical speed -- never sped-up, fast-forwarded, or rushed."
    " No motion blur, smearing, ghosting, or strobing on any moving person,"
    " limb, or vehicle -- every worker and machine stays crisp, sharply"
    " defined, and individually readable in every frame of the clip, even"
    " while in motion. If this means fewer individual actions are visible"
    " in the 5 seconds, that is correct -- believable, sharp, real-world-speed"
    " motion matters more than cramming in lots of visible activity."
)


def _clip_suffix(scene: str, clip_id: str = "A") -> str:
    lock = _CLIP_CAMERA_LOCK.get(scene, _CLIP_CAMERA_LOCK["corridor"])
    base = (
        " Locked-off tilted oblique aerial drone shot, camera angled downward"
        f" at roughly 35-45 degrees, {lock} (NOT straight-down nadir) -- the"
        " exact same camera position, angle, altitude, and framing as the"
        " reference image"
    )
    if clip_id == "E":
        # Clip E is a dedicated finale, shot entirely AFTER restoration is
        # complete (frame 5 to frame 5 -- nothing in the scene itself
        # changes). It is the one deliberate exception to the locked camera
        # for the whole sequence: across this entire clip the drone slowly
        # descends and pushes in toward this scene's own focal point (see
        # _CLIP_DESCENT_TARGET) as a closing reveal move. This is generic
        # across every scene type (corridor/ghat/monument/coast/infra) --
        # whichever location a given run uses, the descent targets that
        # scene's own landmark, never a specific named place.
        target = _CLIP_DESCENT_TARGET.get(scene, _CLIP_DESCENT_TARGET["corridor"])
        movement = (
            ", and for this entire clip the drone performs a slow, smooth,"
            f" deliberate descent and push-in {target} -- lowering altitude"
            " and moving closer gradually and steadily (no jerky or sudden"
            " motion) from the very first frame of this clip to the last,"
            " ending closer to and lower over the scene so its restored"
            " quality and detail are clearly showcased. This is the only"
            " clip in the entire sequence where the camera moves -- every"
            " other clip (A-D) stays fully locked-off; this is the final"
            " reveal payoff after restoration is already finished."
        )
    else:
        movement = (
            ", and it does not move, tilt, rotate, or zoom for the entire"
            " clip."
        )
    motion_clarity = "" if clip_id == "E" else _MOTION_CLARITY
    return (
        base + movement +
        " Nothing changes instantly or 'by itself' anywhere"
        " in the frame -- every change is driven by visible, continuous"
        " human/machine action. Every existing building, monument, or fixed"
        " structure stays completely unchanged in shape and position"
        " throughout the clip -- only the water/ground/people/machinery"
        " change (and, for the finale clip, the camera's own approach)."
        " Clip length 5 seconds or less." + motion_clarity
        + " " + _COLOR_GRADE + _NEGATIVE_CLIP
    )


# First-2-second retention hook, keyed by ``location["scene"]`` -- shown as
# the opening on-screen text overlay during the merge step, NOT baked into
# any generated frame/clip. Since these reels are silent (music only, no
# voiceover/dialogue), the opening hook line is the only thing doing the
# "stop scrolling" job, so it has to land in the first two seconds and never
# names a specific place (that's what the separate location-pin badge is
# for) -- it's a generic curiosity opener per scene type, paired with a
# constant retention nudge line that's the same across every run by design.
_HOOK_LINES = {
    "corridor": "Everyone walked past this and ignored it.",
    "ghat": "This ghat was drowning in trash.",
    "monument": "This heritage site was vanishing.",
    "coast": "This coastline was unrecognizable.",
    "infra": "Nobody thought this could be fixed.",
}
_HOOK_RETENTION_LINE = "Watch till the end."


def build_hook_lines(location: Dict[str, Any]) -> List[str]:
    """Return the 2-line opening hook (scene-generic curiosity line + a
    constant retention nudge) for *location*'s ``scene`` tag. Never includes
    a place name -- the location-pin badge handles that separately."""
    scene = location.get("scene", "corridor")
    return [
        _HOOK_LINES.get(scene, _HOOK_LINES["corridor"]),
        _HOOK_RETENTION_LINE,
    ]


# ---------------------------------------------------------------------------
# Storytelling intro clip (politician/JE addressing workers at the site).
# Optional, separate from the silent A-E drone sequence -- this is the one
# clip in the whole reel with a human voice, lip-synced dialogue, and a
# ground-level camera instead of the locked aerial shot. Both the reference
# image and the dialogue line are generated fresh per location/scene/
# pollution_type -- never a single fixed script reused across runs -- so a
# Mithi River "land-grab encroachment" run and a Najafgarh "industrial
# effluent" run don't end up with the same JE saying the same line.
# ---------------------------------------------------------------------------

# Two speaker archetypes, rotated per-location the same way the SEO tag
# pools rotate (see _rotate_seed/_rotate_pick below) -- a JE (Junior
# Engineer, a real on-the-ground municipal role) reads as procedural/
# official, a local politician reads as more campaign/accountability-coded.
# Both are plausible messengers for "why is this still like this" at an
# Indian urban-pollution site, so alternating keeps the intro from feeling
# like the same character in every reel.
_DIALOGUE_SPEAKERS = ["JE", "politician"]

_SPEAKER_DESCRIPTION = {
    "JE": (
        "a municipal Junior Engineer (JE) in his 40s, short-sleeved"
        " collared shirt, ID badge clipped to his pocket, holding a"
        " clipboard, standing with the posture of a government field"
        " officer giving instructions"
    ),
    "politician": (
        "a local politician in his 50s, white kurta-pajama with a"
        " shoulder stole, standing with the posture of someone making a"
        " public statement at the site, a couple of aides visible just"
        " behind him"
    ),
}

# Dialogue line templates, keyed by (speaker, scene). Each is a short,
# natural Hindi/Hinglish line a real official/politician could plausibly
# say while pointing at a polluted site and addressing workers/subordinates
# -- the {pollution} slot is filled from the location's own
# ``pollution_type`` field (falling back to a generic word) so the line
# stays grounded in what this specific location actually has wrong with it,
# instead of a generic "ye ganda hai" that could apply anywhere.
_DIALOGUE_TEMPLATES = {
    "JE": {
        "corridor": "Itna {pollution}? Isko jaldi saaf karao -- aaj se hi shuru karo.",
        "ghat": "Yeh ghat itna {pollution} kaise ho gaya? Sabko bolo, kaam abhi shuru karein.",
        "monument": "Yeh jagah itni important hai aur itna {pollution}? Turant team lagao.",
        "coast": "Yeh beach dekho, kitna {pollution} hai. Cleanup crew ko bulao, aaj hi.",
        "infra": "Is pure stretch mein itna {pollution} -- ab aur deri nahi, kaam shuru karo.",
    },
    "politician": {
        "corridor": "Yeh {pollution} hamari janta ki zimmedari hai. Hum isko jaldi saaf karayenge.",
        "ghat": "Hamare ghat ki yeh haalat sahi nahi hai. {pollution} ko khatam karna hamara wada hai.",
        "monument": "Hamari virasat itni {pollution} nahi reh sakti. Kaam aaj se shuru hoga.",
        "coast": "Yeh coastline humari pehchaan hai. Itna {pollution} bardasht nahi karenge.",
        "infra": "Logon ki suvidha ke liye yeh {pollution} jaldi se theek karna zaroori hai.",
    },
}

_POLLUTION_WORD_FALLBACK = "ganda"


def _pollution_word(location: Dict[str, Any]) -> str:
    raw = (location.get("pollution_type") or "").strip().lower()
    if not raw:
        return _POLLUTION_WORD_FALLBACK
    # Keep it short and speakable in a single dialogue line -- a long
    # technical phrase like "untreated industrial effluent discharge"
    # doesn't read naturally as something said out loud, so collapse to
    # "ganda" (dirty/polluted) whenever the source phrase is more than a
    # couple of words, and otherwise use the location's own term verbatim.
    if len(raw.split()) > 2:
        return _POLLUTION_WORD_FALLBACK
    return raw


def build_dialogue_line(location: Dict[str, Any]) -> Dict[str, str]:
    """Return ``{"speaker": ..., "text": ...}`` for the storytelling intro
    clip -- a fresh, location-grounded Hindi/Hinglish line each time, never
    a single fixed script reused across runs."""
    scene = location.get("scene", "corridor")
    seed = _rotate_seed(location)
    speaker = _DIALOGUE_SPEAKERS[seed % len(_DIALOGUE_SPEAKERS)]
    template = _DIALOGUE_TEMPLATES.get(speaker, _DIALOGUE_TEMPLATES["JE"]).get(
        scene, _DIALOGUE_TEMPLATES[speaker]["corridor"]
    )
    text = template.format(pollution=_pollution_word(location))
    return {"speaker": speaker, "text": text}


def build_intro_frame_prompt(location: Dict[str, Any]) -> str:
    """Build the still-image prompt for the storytelling intro clip's
    reference frame -- a ground-level medium shot of a JE/politician
    addressing workers at the (still-polluted) site, used as the input
    image for TTS + lip-sync. Deliberately NOT the locked aerial drone
    framing used by frames 1-5 -- this is a separate, ground-level shot,
    the one other deliberate camera exception in the sequence besides clip
    E's descent."""
    dialogue = build_dialogue_line(location)
    speaker_desc = _SPEAKER_DESCRIPTION.get(dialogue["speaker"], _SPEAKER_DESCRIPTION["JE"])
    place = f"{location.get('area_name', '')}, {location.get('city', '')}".strip(", ")
    loc_type = location.get("type", "water")
    backdrop = (
        "the still-polluted, trash-strewn water/bank behind him"
        if loc_type == "water"
        else "the still-polluted, trash-strewn ground behind him"
    )
    return (
        "Photorealistic ground-level medium shot, eye-level camera, shallow"
        f" depth of field, shot on a real camera (not a drone) -- {speaker_desc},"
        f" standing at {place or 'the site'}, gesturing with one hand toward"
        f" {backdrop}, mid-sentence with mouth slightly open as if actively"
        " speaking, 2-3 workers in high-visibility vests standing nearby"
        " listening attentively. Natural daylight, realistic skin texture and"
        " clothing detail, candid documentary-photography look -- NOT posed"
        " or staged-looking. 9:16 vertical composition." + _NEGATIVE_IMAGE
    )


# ---------------------------------------------------------------------------
# Per-platform SEO metadata (Instagram / Facebook / YouTube / TikTok), built
# from the same scene/type/location fields as everything else above -- no
# hardcoded place, so this works for any location the scout picks. Written
# into the trailing columns of the location tracker at the end of a
# successful run so a future "publish" step can pull ready-to-post content
# straight from there instead of regenerating it.
# ---------------------------------------------------------------------------

# Generic, evergreen viral/restoration tags that read well on any platform,
# regardless of scene/type. Kept deliberately larger than any single post
# needs (see _rotate_pick below) so consecutive runs don't all grab the same
# fixed slice -- both Instagram and TikTok penalize accounts that post the
# identical hashtag set on every upload, so the *generic* portion of the mix
# has to rotate across runs even though the location/type/scene tags already
# vary naturally because the location itself never repeats.
_SEO_GENERIC_TAGS = [
    "BeforeAndAfter",
    "Transformation",
    "Restoration",
    "CleanUp",
    "SaveThePlanet",
    "ClimateAction",
    "Incredible",
    "Satisfying",
    "GlowUp",
    "DidYouKnow",
    "Inspiring",
    "MustWatch",
    "Wholesome",
    "GoodNews",
]

# Type-specific tags (water body vs. land/dumping-ground style locations).
_SEO_TYPE_TAGS = {
    "water": ["RiverRestoration", "WaterPollution", "CleanWater", "RiverCleanup"],
    "land": ["WasteManagement", "LandRestoration", "ZeroWaste", "WasteCleanup"],
}

# Scene-specific tags, matching the same _CAMERA_STYLES keys used elsewhere.
_SEO_SCENE_TAGS = {
    "corridor": ["UrbanDrain", "CityClean", "UrbanRiver"],
    "ghat": ["RiverGhat", "TempleTown", "SacredRiver"],
    "monument": ["Heritage", "IncredibleIndia", "HeritageSite"],
    "coast": ["BeachCleanup", "OceanClean", "CoastalCleanup"],
    "infra": ["Infrastructure", "UrbanRenewal", "CityInfra"],
}

# TikTok skews toward trend/format tags rather than place/aesthetic tags.
_SEO_TIKTOK_TREND_TAGS = [
    "fyp",
    "Satisfying",
    "BeforeAndAfter",
    "Transformation",
    "Viral",
    "ForYou",
    "Oddlysatisfying",
    "GlowUp",
    "WatchThis",
]


def _rotate_seed(location: Dict[str, Any]) -> int:
    """Stable per-location integer seed -- same location always rotates the
    same way (reproducible), but different locations land on different
    offsets into the generic/trend pools, so consecutive runs (which always
    use a different, never-repeated location -- see punarnirman_scout's
    dedup check) naturally pick a different slice of generic tags instead of
    always grabbing the same first N entries."""
    key = (
        str(location.get("id", ""))
        or str(location.get("location", ""))
        or f"{location.get('area_name', '')}{location.get('city', '')}"
    )
    return sum(ord(c) for c in key) if key else 0


def _rotate_pick(pool: List[str], seed: int, n: int) -> List[str]:
    """Pick *n* tags from *pool* starting at a seed-derived offset, wrapping
    around -- deterministic per seed, but varies which tags come out as the
    seed (i.e. the location) changes."""
    if not pool:
        return []
    offset = seed % len(pool)
    return [pool[(offset + i) % len(pool)] for i in range(n)]


def _seo_tag(text: str) -> str:
    """Turn free text into a single CamelCase hashtag token, e.g.
    'Mithi River, Mumbai' -> 'MithiRiverMumbai'."""
    words = re.findall(r"[A-Za-z0-9]+", text or "")
    return "".join(w.capitalize() for w in words)


def _dedupe_keep_order(tags: List[str]) -> List[str]:
    seen = set()
    out = []
    for t in tags:
        key = t.lower()
        if key and key not in seen:
            seen.add(key)
            out.append(t)
    return out


def build_seo_metadata(location: Dict[str, Any]) -> Dict[str, str]:
    """Generate per-platform, viral-market-standard SEO metadata for
    *location*: Instagram (exactly 5 hashtags), Facebook (a longer hashtag
    set), YouTube (a title plus separate keywords and hashtags), and TikTok
    (exactly 5 hashtags) -- plus a full caption/description per platform.
    Entirely scene/type/location-driven -- never a hardcoded place name --
    so it works for whatever the scout picks."""
    loc_type = location.get("type", "water")
    scene = location.get("scene", "corridor")
    city = location.get("city", "")
    state = location.get("state", "")
    country = location.get("country", "")
    area_name = location.get("area_name", "")
    pollution_type = location.get("pollution_type", "")
    display = location.get("location", f"{area_name}, {city}".strip(", "))

    city_tag = _seo_tag(city) if city else _seo_tag(display)
    country_tag = _seo_tag(country) if country else ""
    area_tag = _seo_tag(area_name) if area_name else ""

    seed = _rotate_seed(location)
    type_pool = _SEO_TYPE_TAGS.get(loc_type, _SEO_TYPE_TAGS["water"])
    scene_pool = _SEO_SCENE_TAGS.get(scene, _SEO_SCENE_TAGS["corridor"])
    # Rotate which tag(s) come out of each pool based on the location's own
    # seed, rather than always taking pool[0] -- two different rivers of the
    # same "water" type now don't necessarily get the identical type tag.
    type_tags = _rotate_pick(type_pool, seed, len(type_pool))
    scene_tags = _rotate_pick(scene_pool, seed + 1, len(scene_pool))
    location_tags = [t for t in (area_tag, city_tag, country_tag) if t]

    # Instagram: exactly 5 -- a tight mix of one location tag, one type tag,
    # one scene tag, and 2 generic viral tags (current IG best practice is a
    # small number of *highly relevant* tags, not a long spray list). The
    # generic pair is rotated per-location (see _rotate_pick) instead of
    # always being the pool's first two entries, since Instagram penalizes
    # accounts that post the exact same hashtag set on every upload.
    instagram = _dedupe_keep_order(
        (location_tags[:1] or ["Restoration"])
        + type_tags[:1]
        + scene_tags[:1]
        + _rotate_pick(_SEO_GENERIC_TAGS, seed, 2)
    )[:5]
    fallback_pool = _rotate_pick(_SEO_GENERIC_TAGS, seed + 3, len(_SEO_GENERIC_TAGS))
    fi = 0
    while len(instagram) < 5 and fi < len(fallback_pool):
        if fallback_pool[fi].lower() not in {t.lower() for t in instagram}:
            instagram.append(fallback_pool[fi])
        fi += 1

    # Facebook: no strict cap -- current FB practice favors a broader,
    # discovery-oriented set, so include everything we've got. Still rotated
    # (offset by seed) rather than a fixed pool order, for the same
    # anti-repetition reason as Instagram, even though FB is less sensitive
    # to repeated tags than IG/TikTok.
    facebook = _dedupe_keep_order(
        location_tags
        + type_tags
        + scene_tags
        + _rotate_pick(_SEO_GENERIC_TAGS, seed, len(_SEO_GENERIC_TAGS))
        + ["India" if country == "India" else country_tag]
    )
    facebook = [t for t in facebook if t]

    # YouTube: title + separate keyword phrases (no #) + a small hashtag set
    # (YouTube renders only the first few hashtags above the title, so keep
    # it short -- current platform guidance is 3 or fewer).
    youtube_title = f"{display}: Pollution to Restoration | Before & After Drone Timelapse"
    keyword_phrases = _dedupe_keep_order(
        [
            display,
            f"{city} pollution" if city else "",
            f"{city} restoration" if city else "",
            pollution_type,
            "before and after restoration",
            "drone timelapse",
            "aerial drone footage",
            "environmental cleanup",
            f"{country} environment" if country else "",
        ]
    )
    youtube_keywords = ", ".join(p for p in keyword_phrases if p)
    youtube_hashtags = _dedupe_keep_order((location_tags[:1] or ["Restoration"]) + ["Shorts"] + type_tags[:1])[:3]

    # TikTok: exactly 5 -- trend/format-led rather than location-led, since
    # TikTok's discovery algorithm rewards matching active format trends.
    # The trend-tag trio is rotated per-location for the same
    # anti-repetition reason as Instagram (TikTok shadow-bans/deprioritizes
    # accounts that spam an identical hashtag block on every post).
    tiktok = _dedupe_keep_order(
        _rotate_pick(_SEO_TIKTOK_TREND_TAGS, seed, 3) + location_tags[:1] + type_tags[:1]
    )[:5]
    tiktok_fallback = _rotate_pick(_SEO_TIKTOK_TREND_TAGS, seed + 4, len(_SEO_TIKTOK_TREND_TAGS))
    ti = 0
    while len(tiktok) < 5 and ti < len(tiktok_fallback):
        if tiktok_fallback[ti].lower() not in {t.lower() for t in tiktok}:
            tiktok.append(tiktok_fallback[ti])
        ti += 1

    instagram_hashtags = " ".join(f"#{t}" for t in instagram)
    facebook_hashtags = " ".join(f"#{t}" for t in facebook)
    youtube_hashtags_str = " ".join(f"#{t}" for t in youtube_hashtags)
    tiktok_hashtags = " ".join(f"#{t}" for t in tiktok)

    place = display or f"{city}, {country}".strip(", ") or "this location"
    angle = (location.get("viral_angle") or "").strip()
    angle_line = f" {angle}" if angle else ""

    # Captions are deliberately built only from this run's own location
    # fields (display name, city, state, country, pollution_type,
    # viral_angle) -- never a hardcoded landmark or claim about what's
    # physically near the site, so they stay accurate to whatever the
    # scout actually picked.
    instagram_caption = (
        f"{place} -- watch this {pollution_type or 'pollution'} hotspot go through a full "
        f"restoration, start to finish.{angle_line} Which transformation should we cover next? "
        f"Drop your guess below.\n\n{instagram_hashtags}"
    )

    facebook_caption = (
        f"Before & after: {place}.\n\n"
        f"This stretch dealt with serious {pollution_type or 'pollution'} -- our timelapse "
        f"shows the entire clean-up and restoration process from the first cleanup crew to "
        f"the finished site.{angle_line}\n\n"
        f"Tag someone who needs to see this, and let us know in the comments what location "
        f"we should restore next.\n\n{facebook_hashtags}"
    )

    tiktok_caption = (
        f"{place} glow-up{angle_line} Wait for the end.\n\n{tiktok_hashtags}"
    )

    youtube_description = (
        f"{place} -- a full pollution-to-restoration timelapse, from the first signs of "
        f"{pollution_type or 'pollution'} to a fully restored site.{angle_line}\n\n"
        f"Keywords: {youtube_keywords}\n\n{youtube_hashtags_str}"
    )

    return {
        "instagram_hashtags": instagram_hashtags,
        "instagram_caption": instagram_caption,
        "facebook_hashtags": facebook_hashtags,
        "facebook_caption": facebook_caption,
        "youtube_title": youtube_title,
        "youtube_keywords": youtube_keywords,
        "youtube_hashtags": youtube_hashtags_str,
        "youtube_description": youtube_description,
        "tiktok_hashtags": tiktok_hashtags,
        "tiktok_caption": tiktok_caption,
    }


_CLIP_FRAME_PAIRS = {
    "A": (1, 2),
    "B": (2, 3),
    "C": (3, 4),
    "D": (4, 5),
    # Clip E is the dedicated post-restoration descent/reveal -- shot after
    # restoration is complete, so it bridges frame 5 to itself (no content
    # change, only the camera moving) rather than to a new frame.
    "E": (5, 5),
}


def build_clip_prompts(location: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build the 5 fixed continuity-clip prompts for *location*: A-D are the
    locked-camera restoration clips, E is the dedicated post-restoration
    descent/reveal finale."""
    loc_type = location.get("type", "water")
    bodies = _CLIP_BODY.get(loc_type, _CLIP_BODY["water"])
    scene = location.get("scene", "corridor")

    clips = []
    for clip_id in ("A", "B", "C", "D", "E"):
        from_frame, to_frame = _CLIP_FRAME_PAIRS[clip_id]
        clips.append(
            {
                "id": clip_id,
                "label": _CLIP_LABELS[clip_id],
                "from_frame": from_frame,
                "to_frame": to_frame,
                "resolution": "720p",
                "prompt": bodies[clip_id] + _clip_suffix(scene, clip_id),
            }
        )
    return clips


__all__ = [
    "build_frame_prompts",
    "build_clip_prompts",
    "build_hook_lines",
    "build_seo_metadata",
    "build_dialogue_line",
    "build_intro_frame_prompt",
]
