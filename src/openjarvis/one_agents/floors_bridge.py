"""Bridge from ONE's runtime to per-floor code that lives outside this repo.

Floor business logic, prompts and brand registries live in
``one-company/floors/``, which is deliberately not part of this repository:
this repo is mirrored to a public GitHub remote, that folder is not.

Every function here degrades to ``None`` when the floors tree is absent, so a
clone of this repository still starts and every already-working agent keeps
running exactly as before. Nothing in this module raises.

Override the location with ``ONE_FLOORS_ROOT`` if the folder ever moves.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

# runtime.py sits at <ONE-Suite>/src/src/openjarvis/one_agents/, so the
# company layer is four levels up and then one across.
_DEFAULT_ROOT = Path(__file__).resolve().parents[4] / "one-company" / "floors"


def floors_root() -> Path:
    override = os.environ.get("ONE_FLOORS_ROOT", "").strip()
    return Path(override) if override else _DEFAULT_ROOT


def registry() -> Any | None:
    """The compiled floors index, or None when it cannot be trusted.

    Returns None in three cases, all of them deliberate: the floors tree is
    absent, the index has never been built, or the index is stale because the
    tree changed after it was compiled. A stale registry is worse than no
    registry - it answers confidently and wrongly - so this refuses it rather
    than passing it on. Rebuild with ``python _registry/build_index.py``.

    The module it returns is standard-library only, so it works in a process
    that has no PyYAML.
    """
    registry_dir = floors_root() / "_registry"
    module_path = registry_dir / "registry.py"
    if not module_path.is_file():
        return None
    try:
        if str(registry_dir) not in sys.path:
            sys.path.insert(0, str(registry_dir))
        spec = importlib.util.spec_from_file_location("one_floors_registry", module_path)
        if spec is None or spec.loader is None:
            return None
        module = sys.modules.get("one_floors_registry")
        if module is None:
            module = importlib.util.module_from_spec(spec)
            sys.modules["one_floors_registry"] = module
            spec.loader.exec_module(module)
        module.check_fresh()
        return module
    except Exception:  # noqa: BLE001 - a broken registry must never break the queue
        sys.modules.pop("one_floors_registry", None)
        return None


def load(floor_dir: str, module_name: str) -> Any | None:
    """Import ``<floors_root>/<floor_dir>/lib/<module_name>.py``.

    The floor's ``lib`` package is registered under a floor-scoped name
    (``one_floor_<floor_dir>_lib``) rather than the bare name ``lib``, so two
    floors can each have a ``lib`` package without colliding in sys.modules.
    Returns None if anything at all is missing or broken.
    """
    lib_dir = floors_root() / floor_dir / "lib"
    init = lib_dir / "__init__.py"
    if not init.is_file():
        return None

    package = f"one_floor_{floor_dir}_lib"
    try:
        if package not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                package, init, submodule_search_locations=[str(lib_dir)]
            )
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[package] = module
            spec.loader.exec_module(module)
        return importlib.import_module(f"{package}.{module_name}")
    except Exception:  # noqa: BLE001 - a missing floor must never break the queue
        sys.modules.pop(package, None)
        return None


def route_media(task: str, job: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a Floor 4 request to one brand.

    Returns ``(brand, question)``. Exactly one is ever set:
      - ``(brand, None)``  route it to ``brand["worker_agent_id"]``
      - ``(None, "...")``  the request named two brands or none; ask, do not
        dispatch, because guessing here means posting to the wrong account
      - ``(None, None)``   the floors tree is unavailable; caller keeps its
        existing single-brand behaviour
    """
    router = load("floor_04_media", "brand_router")
    if router is None:
        return None, None

    explicit = None
    if job:
        try:
            import json

            payload = json.loads(str(job.get("task") or "{}"))
            if isinstance(payload, dict):
                explicit = payload.get("brand")
        except Exception:  # noqa: BLE001 - a plain-text task is normal
            explicit = None

    try:
        brand = router.route(task, explicit=explicit)
    except router.BrandConflict as exc:
        return None, str(exc)
    except Exception:  # noqa: BLE001
        return None, None

    if brand is None:
        return None, (
            "Which brand is this for - ImagineIndia or aibyvineet? Naming it "
            "keeps the work on the right account."
        )
    return brand, None


def media_head_busy(head_agent_id: str = "ia") -> dict[str, Any] | None:
    """The head's current stage if it is mid-flow, else None."""
    router = load("floor_04_media", "brand_router")
    if router is None:
        return None
    try:
        from openjarvis.one_agents import stages

        return router.head_flow_in_progress(stages.get_stages(), head_agent_id)
    except Exception:  # noqa: BLE001
        return None
