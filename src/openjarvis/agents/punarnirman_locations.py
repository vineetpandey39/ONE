"""Daily location rotation for the Punarnirman restoration-reel engine.

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


__all__ = ["active_locations", "location_for_date"]
