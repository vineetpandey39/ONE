"""Daily location rotation for the IA restoration-reel engine.

Phase 1 (per the user's plan): India-only, different slum/dirty/polluted
location per calendar day, building traction for 5-6 months before
expanding internationally (entries already exist in the rotation file,
just flagged ``"active": false`` until that phase starts).

Rotation is a pure function of the date, not a stored cursor: every
calendar day deterministically maps to the same location (so both of the
day's twice-daily runs use the same city), and the index advances by one
each day with no persisted state file to get out of sync.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.paths import get_config_dir

_DEFAULT_ROTATION_PATH = Path("configs/restoration_locations/india_rotation.json")


def _load_rotation_file(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load the full location list (active + inactive) from the rotation file."""
    candidates = [
        path,
        _DEFAULT_ROTATION_PATH,
        get_config_dir() / "restoration_locations" / "india_rotation.json",
    ]
    for p in candidates:
        if p and Path(p).exists():
            data = json.loads(Path(p).read_text(encoding="utf-8"))
            return data.get("locations", [])
    raise FileNotFoundError(
        "No restoration-locations rotation file found. Looked in: "
        f"{', '.join(str(c) for c in candidates if c)}"
    )


def active_locations(
    *, region: str = "india", path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Return the active locations for *region* (default: india-phase)."""
    all_locs = _load_rotation_file(path)
    return [
        loc
        for loc in all_locs
        if loc.get("active", False) and loc.get("region") == region
    ]

def location_for_date(
    on_date: Optional[date] = None,
    *,
    region: str = "india",
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Deterministically pick the day's location from the active rotation.

    Both daily runs (the agent runs twice a day) on the same calendar date
    resolve to the same location; the next calendar day advances to the
    next location in the list, wrapping around.
    """
    locations = active_locations(region=region, path=path)
    if not locations:
        raise ValueError(f"No active locations configured for region '{region}'.")
    d = on_date or date.today()
    day_index = d.toordinal()
    return locations[day_index % len(locations)]


# ---------------------------------------------------------------------------
# Curated Location Knowledge Base -- from 04_Location_Knowledge_Base.md
# (Imagine India agent knowledge pack). These are real, fully
# pre-vetted named locations the user hand-picked, each with the brand's own
# Hero Object / Emotional Trigger / Before / Restoration Concept / Camera /
# Viral Score fields -- richer than both the plain static rotation file
# (id/city/area_name/state/type/region/active) and the LLM-scout's own output
# shape. ``ia_scout.scout_location`` tries this pool FIRST (highest viral
# score, not yet used) before falling back to its existing LLM web-search
# step or the generic rotation file -- additive priority layer, the older
# fallback chain is untouched and still runs once this pool is exhausted.
#
# Field mapping notes (decided from the location's own description in the
# knowledge-base file, matching the existing ``type``/``scene`` vocabulary
# already used by ia_prompts.py's ``_CAMERA_STYLES``/``_SUBSTANCE`` dicts):
#   Dharavi                  -> type "land",  scene "corridor" (dense urban fabric, no water/monument anchor)
#   Mithi River               -> type "water", scene "corridor" (river channel/riverfront)
#   Bellandur Lake             -> type "water", scene "lake" (open urban lake -- NOT a
#                                  linear corridor; fixed from an earlier "corridor"
#                                  mistake that made it render identically to river/drain
#                                  locations like Mithi River)
#   Howrah Station             -> type "land",  scene "monument" (heritage railway building is the hero)
#   Ghazipur Landfill          -> type "land",  scene "corridor" (landfill hill)
#   Howrah Bridge Riverfront   -> type "water", scene "infra" (bridge is the fixed anchor, matches
#                                 the existing "infra" camera style which is built exactly for this case)
#   Gateway of India Precinct  -> type "water", scene "monument" (monument + waterfront precinct)
NAMED_LOCATIONS: List[Dict[str, Any]] = [
    {
        "id": "dharavi_mumbai",
        "location": "Dharavi, Mumbai",
        "area_name": "Dharavi",
        "city": "Mumbai",
        "state": "Maharashtra",
        "country": "India",
        "type": "land",
        "scene": "corridor",
        "hero_object": "Dharavi settlement and dense urban fabric",
        "emotional_trigger": "Hope, dignity, redevelopment, identity",
        "before": ["Dense slum rooftops", "Narrow lanes", "Blue tarpaulin", "Overcrowding"],
        "restoration_concept": [
            "Smart affordable housing",
            "Green public spaces",
            "Schools",
            "Hospitals",
            "Community infrastructure",
        ],
        "camera_notes": "Aerial for scale, ground level for human impact",
        "viral_score": 10.0,
        "pollution_type": "overcrowded informal settlement",
        "viral_angle": "Hope, dignity, redevelopment, identity",
        "source_image_query": "Dharavi Mumbai aerial slum rooftops",
    },
    {
        "id": "mithi_river_mumbai",
        "location": "Mithi River, Mumbai",
        "area_name": "Mithi River",
        "city": "Mumbai",
        "state": "Maharashtra",
        "country": "India",
        "type": "water",
        "scene": "corridor",
        "hero_object": "Mithi River channel and polluted riverfront",
        "emotional_trigger": "Mumbai's forgotten river comes back to life",
        "before": ["Black water", "Plastic islands", "Slums on banks", "Industrial discharge"],
        "restoration_concept": ["Clean riverfront", "Cycling tracks", "Mangroves", "Kayaking", "Public promenade"],
        "camera_notes": "Locked aerial for transformation, low waterfront hero reveal",
        "viral_score": 9.8,
        "pollution_type": "black water + plastic + industrial discharge",
        "viral_angle": "Mumbai's forgotten river comes back to life",
        "source_image_query": "Mithi River Mumbai polluted aerial",
    },
    {
        "id": "bellandur_lake_bengaluru",
        "location": "Bellandur Lake, Bengaluru",
        "area_name": "Bellandur Lake",
        "city": "Bengaluru",
        "state": "Karnataka",
        "country": "India",
        "type": "water",
        # FIXED: was "corridor" -- a lake is an OPEN body of water, not a
        # narrow linear corridor, and sharing the corridor template made
        # Bellandur Lake render visually identical to river/drain locations
        # (e.g. Mithi River) using that same camera template. "lake" is a
        # dedicated scene tag in ia_prompts.py's _CAMERA_STYLES describing
        # an open shoreline with the skyline ringing the water.
        "scene": "lake",
        "hero_object": "Bellandur Lake",
        "emotional_trigger": "The lake that once caught fire",
        "before": ["Toxic foam", "Polluted water", "Garbage", "Urban skyline"],
        "restoration_concept": ["Clean urban lake", "Floating wetlands", "Boardwalks", "Bird sanctuary", "Kayaking", "Cycling loop"],
        "camera_notes": "Aerial for scale, water-level final reveal",
        "viral_score": 9.8,
        "pollution_type": "toxic foam + polluted water",
        "viral_angle": "The lake that once caught fire",
        "source_image_query": "Bellandur Lake Bengaluru toxic foam aerial",
    },
    {
        "id": "howrah_station_kolkata",
        "location": "Howrah Station, Kolkata",
        "area_name": "Howrah Station",
        "city": "Kolkata",
        "state": "West Bengal",
        "country": "India",
        "type": "land",
        "scene": "monument",
        "hero_object": "Howrah Station heritage building",
        "emotional_trigger": "1905 to 2026, railway nostalgia",
        "before": ["Colonial station", "Steam engines", "Early workers and scaffolding"],
        "restoration_concept": [
            "Era-accurate engineering evolution",
            "Heritage facade restoration",
            "Modern railway infrastructure",
            "Digital systems",
            "Clean forecourt",
        ],
        "camera_notes": "40% aerial, 60% ground/station-level details",
        "viral_score": 9.4,
        "pollution_type": "aging colonial-era station infrastructure",
        "viral_angle": "1905 to 2026, railway nostalgia",
        "source_image_query": "Howrah Station Kolkata heritage aerial",
    },
    {
        "id": "ghazipur_landfill_delhi",
        "location": "Ghazipur Landfill, Delhi",
        "area_name": "Ghazipur Landfill",
        "city": "Delhi",
        "state": "Delhi",
        "country": "India",
        "type": "land",
        "scene": "corridor",
        "hero_object": "Garbage mountain / landfill hill",
        "emotional_trigger": "Delhi's garbage mountain becomes eco hill",
        "before": ["Massive landfill", "Smoke", "Plastic waste", "Leachate", "Birds", "Delhi skyline"],
        "restoration_concept": [
            "Biomining",
            "Waste sorting",
            "Engineered terraces",
            "Methane capture",
            "Eco hill",
            "Rainwater pond",
            "Observation deck",
            "Recycling education center",
        ],
        "camera_notes": "Aerial for scale, ground-level for park experience",
        "important_rule": (
            "All machinery must operate directly on the landfill hill. Do not"
            " let trucks or side roads steal attention."
        ),
        "viral_score": 9.2,
        "pollution_type": "landfill smoke + plastic waste + leachate",
        "viral_angle": "Delhi's garbage mountain becomes eco hill",
        "source_image_query": "Ghazipur landfill Delhi garbage mountain aerial",
    },
    {
        "id": "howrah_bridge_riverfront_kolkata",
        "location": "Howrah Bridge Riverfront, Kolkata",
        "area_name": "Howrah Bridge Riverfront",
        "city": "Kolkata",
        "state": "West Bengal",
        "country": "India",
        "type": "water",
        "scene": "infra",
        "hero_object": "Howrah Bridge + Hooghly riverfront precinct",
        "emotional_trigger": "Kolkata heritage + chaos to riverfront pride",
        "before": [
            "Congested road",
            "Slum pockets",
            "Hawkers",
            "Broken ghats",
            "Polluted river edge",
            "Yellow taxis and buses",
            "Howrah Bridge visible",
        ],
        "restoration_concept": [
            "Clean riverfront",
            "Restored ghats",
            "Heritage promenade",
            "Organized roads",
            "Ferries",
            "Public plazas",
            "Trees",
            "Lighting",
            "Kolkata heritage experience",
        ],
        "camera_notes": "Aerial for recognizability, ground-level for promenade emotional impact, bridge must remain visible in background",
        "important_rule": (
            "Do not restore the bridge itself. Restore surroundings and"
            " riverfront. Bridge remains the anchor."
        ),
        "viral_score": 9.6,
        "pollution_type": "congested riverfront + broken ghats",
        "viral_angle": "Kolkata heritage + chaos to riverfront pride",
        "source_image_query": "Howrah Bridge Kolkata riverfront aerial",
    },
    {
        "id": "gateway_of_india_precinct_mumbai",
        "location": "Gateway of India Precinct, Mumbai",
        "area_name": "Gateway of India Precinct",
        "city": "Mumbai",
        "state": "Maharashtra",
        "country": "India",
        "type": "water",
        "scene": "monument",
        "hero_object": "Gateway of India and waterfront surroundings",
        "emotional_trigger": "National pride + tourism landmark",
        "before": ["Crowded plaza", "Poorly organized public space", "Cluttered waterfront"],
        "restoration_concept": ["Clean heritage plaza", "Better pedestrian circulation", "Waterfront promenade", "Lighting", "Landscaping", "Tourism upgrade"],
        "camera_notes": "Monument wide shot, ground-level plaza shot",
        "viral_score": 9.0,
        "pollution_type": "cluttered/poorly organized public plaza",
        "viral_angle": "National pride + tourism landmark",
        "source_image_query": "Gateway of India Mumbai waterfront aerial",
    },
]

# Names-only -- no detailed Hero Object/Before/Restoration Concept fields
# yet (per the knowledge-base file's own "Future Locations" section). Used
# only as the option pool for the Facebook "vote for next location" pinned
# comment (see ia_prompts.build_seo_metadata) -- never auto-promoted into
# NAMED_LOCATIONS until the user supplies full details for one of them.
FUTURE_LOCATIONS: List[str] = [
    "Seelampur, Delhi",
    "Musi River, Hyderabad",
    "Cooum River, Chennai",
    "Charminar Precinct, Hyderabad",
    "CST Mumbai",
    "Khari Baoli, Delhi",
    "Silk Board Junction, Bengaluru",
]


def named_locations(*, sort_by_viral_score: bool = True) -> List[Dict[str, Any]]:
    """Return the curated Location Knowledge Base entries (see
    ``NAMED_LOCATIONS`` above), highest ``viral_score`` first by default so
    callers picking "the best unused one" can just take the first unused
    match."""
    locs = [dict(loc) for loc in NAMED_LOCATIONS]
    if sort_by_viral_score:
        locs.sort(key=lambda l: l.get("viral_score", 0), reverse=True)
    return locs


# ---------------------------------------------------------------------------
# Large real-location name pool -- added to fix the "every run feels
# generic" complaint, which traced back to two compounding problems:
#   1. ia_scout._llm_pick_location() was asked to *invent* a brand-new
#      never-used place from scratch every single run via free-text web
#      search -- unreliable, and prone to drifting back to a handful of
#      famous names.
#   2. Whenever that LLM step failed for ANY reason (no network, no API key,
#      or -- as happened on a real run -- the OpenAI account hit its billing
#      hard limit), the pipeline fell all the way back to the old bare
#      15-entry ``india_rotation.json`` file, whose entries carry only
#      id/city/area_name/state/type -- no hero_object/before/camera_notes/
#      pollution_type/viral_angle at all. ``ia_prompts._location_descriptor``
#      had nothing to work with for those entries and silently produced an
#      empty grounding clause, so the frame/clip prompts fell back to pure
#      generic template text -- which is exactly what happened on the
#      Chennai Cooum / Hyderabad Musi / Bengaluru Bellandur run.
#
# Fix: a much larger (100+) pool of REAL, named, well-documented polluted
# Indian rivers, drains, lakes, slums, and landfills, spanning many cities
# (not just the 6-7 metros the old rotation file and curated KB covered).
# ia_scout now anchors its LLM call to the next unused name from THIS pool
# (asking it to research/describe a specific real place, which is a much
# more reliable LLM task than "invent something new"), and even if the LLM
# step fails outright, ia_scout can build a non-empty heuristic descriptor
# directly from the pool entry's name + type -- so _location_descriptor()
# never again returns blank text, regardless of whether OpenAI is reachable.
# This pool intentionally overlaps with NAMED_LOCATIONS/the old rotation
# file in a few places (e.g. Mithi River, Bellandur Lake) -- that's fine,
# scout_location's used-keys dedup check already treats all three sources
# as one combined never-repeat space.
# ---------------------------------------------------------------------------
LOCATION_NAME_POOL: List[Dict[str, str]] = [
    # -- Delhi NCR --
    {"area_name": "Yamuna at ITO Bridge", "city": "Delhi", "state": "Delhi", "type": "water"},
    {"area_name": "Yamuna at Wazirabad Barrage", "city": "Delhi", "state": "Delhi", "type": "water"},
    {"area_name": "Najafgarh Drain", "city": "Delhi", "state": "Delhi", "type": "water"},
    {"area_name": "Shahdara Drain", "city": "Delhi", "state": "Delhi", "type": "water"},
    {"area_name": "Bhalswa Lake", "city": "Delhi", "state": "Delhi", "type": "water", "scene": "lake"},
    {"area_name": "Bhalswa Landfill", "city": "Delhi", "state": "Delhi", "type": "land"},
    {"area_name": "Okhla Landfill", "city": "Delhi", "state": "Delhi", "type": "land"},
    {"area_name": "Seelampur e-waste belt", "city": "Delhi", "state": "Delhi", "type": "land"},
    {"area_name": "Tughlakabad slum cluster", "city": "Delhi", "state": "Delhi", "type": "land"},
    {"area_name": "Savda Ghevra resettlement colony", "city": "Delhi", "state": "Delhi", "type": "land"},
    {"area_name": "Sahibi River stretch", "city": "Gurugram", "state": "Haryana", "type": "water"},
    {"area_name": "Hindon River", "city": "Ghaziabad", "state": "Uttar Pradesh", "type": "water"},
    # -- Mumbai / Maharashtra --
    {"area_name": "Mithi River channel", "city": "Mumbai", "state": "Maharashtra", "type": "water"},
    {"area_name": "Dahisar River", "city": "Mumbai", "state": "Maharashtra", "type": "water"},
    {"area_name": "Poisar River", "city": "Mumbai", "state": "Maharashtra", "type": "water"},
    {"area_name": "Oshiwara River", "city": "Mumbai", "state": "Maharashtra", "type": "water"},
    {"area_name": "Mahim Creek", "city": "Mumbai", "state": "Maharashtra", "type": "water"},
    {"area_name": "Vasai Creek", "city": "Mumbai", "state": "Maharashtra", "type": "water"},
    {"area_name": "Powai Lake", "city": "Mumbai", "state": "Maharashtra", "type": "water", "scene": "lake"},
    {"area_name": "Deonar Dumping Ground", "city": "Mumbai", "state": "Maharashtra", "type": "land"},
    {"area_name": "Govandi slum belt", "city": "Mumbai", "state": "Maharashtra", "type": "land"},
    {"area_name": "Mankhurd slum cluster", "city": "Mumbai", "state": "Maharashtra", "type": "land"},
    {"area_name": "Ulhas River stretch", "city": "Thane", "state": "Maharashtra", "type": "water"},
    {"area_name": "Mula-Mutha River confluence", "city": "Pune", "state": "Maharashtra", "type": "water"},
    {"area_name": "Pavana River stretch", "city": "Pune", "state": "Maharashtra", "type": "water"},
    {"area_name": "Indrayani River at Alandi", "city": "Pune", "state": "Maharashtra", "type": "water"},
    {"area_name": "Yerwada slum cluster", "city": "Pune", "state": "Maharashtra", "type": "land"},
    {"area_name": "Nag River", "city": "Nagpur", "state": "Maharashtra", "type": "water"},
    # -- Tamil Nadu --
    {"area_name": "Cooum River stretch", "city": "Chennai", "state": "Tamil Nadu", "type": "water"},
    {"area_name": "Adyar River banks", "city": "Chennai", "state": "Tamil Nadu", "type": "water"},
    {"area_name": "Buckingham Canal", "city": "Chennai", "state": "Tamil Nadu", "type": "water"},
    {"area_name": "Pallikaranai Marsh edge", "city": "Chennai", "state": "Tamil Nadu", "type": "water"},
    # -- Telangana / AP --
    {"area_name": "Musi River banks", "city": "Hyderabad", "state": "Telangana", "type": "water"},
    {"area_name": "Hussain Sagar shoreline", "city": "Hyderabad", "state": "Telangana", "type": "water", "scene": "lake"},
    {"area_name": "Gajuwaka industrial belt", "city": "Visakhapatnam", "state": "Andhra Pradesh", "type": "land"},
    # -- Karnataka --
    {"area_name": "Bellandur Lake edge", "city": "Bengaluru", "state": "Karnataka", "type": "water", "scene": "lake"},
    {"area_name": "Varthur Lake", "city": "Bengaluru", "state": "Karnataka", "type": "water", "scene": "lake"},
    {"area_name": "Ulsoor Lake", "city": "Bengaluru", "state": "Karnataka", "type": "water", "scene": "lake"},
    {"area_name": "Vrishabhavathi River", "city": "Bengaluru", "state": "Karnataka", "type": "water"},
    {"area_name": "Hebbal Lake", "city": "Bengaluru", "state": "Karnataka", "type": "water", "scene": "lake"},
    # -- West Bengal --
    {"area_name": "Tolly's Nullah (Adi Ganga)", "city": "Kolkata", "state": "West Bengal", "type": "water"},
    {"area_name": "Topsia slum belt", "city": "Kolkata", "state": "West Bengal", "type": "land"},
    {"area_name": "Howrah riverside slum cluster", "city": "Howrah", "state": "West Bengal", "type": "land"},
    # -- Punjab / Chandigarh --
    {"area_name": "Buddha Nullah", "city": "Ludhiana", "state": "Punjab", "type": "water"},
    {"area_name": "Kali Bein stretch", "city": "Kapurthala", "state": "Punjab", "type": "water"},
    {"area_name": "Satluj River at Ropar", "city": "Ropar", "state": "Punjab", "type": "water"},
    {"area_name": "Sukhna Lake periphery", "city": "Chandigarh", "state": "Chandigarh", "type": "water", "scene": "lake"},
    # -- Gujarat --
    {"area_name": "Sabarmati River stretch", "city": "Ahmedabad", "state": "Gujarat", "type": "water"},
    {"area_name": "Kankaria outskirts settlement", "city": "Ahmedabad", "state": "Gujarat", "type": "land"},
    {"area_name": "Vatva industrial slum belt", "city": "Ahmedabad", "state": "Gujarat", "type": "land"},
    {"area_name": "Amlakhadi stretch", "city": "Ankleshwar", "state": "Gujarat", "type": "water"},
    {"area_name": "Tapi riverside slum cluster", "city": "Surat", "state": "Gujarat", "type": "land"},
    {"area_name": "Daman Ganga River stretch", "city": "Vapi", "state": "Gujarat", "type": "water"},
    # -- Uttar Pradesh --
    {"area_name": "Gomti River banks", "city": "Lucknow", "state": "Uttar Pradesh", "type": "water"},
    {"area_name": "Kali River (East) stretch", "city": "Meerut", "state": "Uttar Pradesh", "type": "water"},
    {"area_name": "Kali River (West) stretch", "city": "Kanpur", "state": "Uttar Pradesh", "type": "water"},
    {"area_name": "Ganga at Kanpur ghats", "city": "Kanpur", "state": "Uttar Pradesh", "type": "water"},
    {"area_name": "Jajmau tannery belt", "city": "Kanpur", "state": "Uttar Pradesh", "type": "land"},
    {"area_name": "Ganga at Assi Ghat backwaters", "city": "Varanasi", "state": "Uttar Pradesh", "type": "water"},
    # -- Bihar / Jharkhand --
    {"area_name": "Ganga riverside slum belt", "city": "Patna", "state": "Bihar", "type": "land"},
    {"area_name": "Hanuman Nagar slum cluster", "city": "Patna", "state": "Bihar", "type": "land"},
    {"area_name": "Damodar River industrial stretch", "city": "Dhanbad", "state": "Jharkhand", "type": "water"},
    {"area_name": "Hatia slum cluster", "city": "Ranchi", "state": "Jharkhand", "type": "land"},
    # -- Kerala --
    {"area_name": "Periyar River industrial stretch", "city": "Eloor", "state": "Kerala", "type": "water"},
    {"area_name": "Vembanad Lake edge", "city": "Kochi", "state": "Kerala", "type": "water", "scene": "lake"},
    {"area_name": "Brahmapuram landfill-adjacent canal", "city": "Kochi", "state": "Kerala", "type": "water"},
    # -- Madhya Pradesh --
    {"area_name": "Khan River stretch", "city": "Indore", "state": "Madhya Pradesh", "type": "water"},
    {"area_name": "Kshipra River stretch", "city": "Ujjain", "state": "Madhya Pradesh", "type": "water"},
    {"area_name": "Indrapuri slum cluster", "city": "Bhopal", "state": "Madhya Pradesh", "type": "land"},
    # -- Rajasthan --
    {"area_name": "Bandi River stretch", "city": "Pali", "state": "Rajasthan", "type": "water"},
    {"area_name": "Chambal River industrial stretch", "city": "Kota", "state": "Rajasthan", "type": "water"},
    # -- Odisha / Northeast --
    {"area_name": "Salia Sahi slum cluster", "city": "Bhubaneswar", "state": "Odisha", "type": "land"},
    {"area_name": "Boragaon Landfill", "city": "Guwahati", "state": "Assam", "type": "land"},
    {"area_name": "Lamphelpat wetland encroachment", "city": "Imphal", "state": "Manipur", "type": "water"},
    # -- Heritage / monument / infra anchors (scene defaults set by scout) --
    {"area_name": "Charminar Precinct", "city": "Hyderabad", "state": "Telangana", "type": "land", "scene": "monument"},
    {"area_name": "Khari Baoli market belt", "city": "Delhi", "state": "Delhi", "type": "land"},
    {"area_name": "Silk Board Junction", "city": "Bengaluru", "state": "Karnataka", "type": "land", "scene": "infra"},
    {"area_name": "CST heritage precinct", "city": "Mumbai", "state": "Maharashtra", "type": "land", "scene": "monument"},
]


def location_name_pool() -> List[Dict[str, str]]:
    """Return a defensive copy of ``LOCATION_NAME_POOL`` -- the large
    real-place anchor pool ia_scout uses to seed its LLM-enrichment step and
    its no-LLM heuristic fallback (see module docstring above)."""
    return [dict(loc) for loc in LOCATION_NAME_POOL]


__all__ = [
    "active_locations",
    "location_for_date",
    "named_locations",
    "location_name_pool",
    "NAMED_LOCATIONS",
    "FUTURE_LOCATIONS",
    "LOCATION_NAME_POOL",
]
