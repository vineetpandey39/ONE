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
    # floor_registry.py first. It was called registry.py until a safety check
    # found it colliding with _services/products/registry.py in a tree that
    # imports flatly - whichever loaded first won, and gate.py's bare
    # ``import registry`` could get the wrong one. The rename fixed that and
    # silently broke this bridge, because a missing file returns None here by
    # design and nothing complains. Both names are accepted now, so neither
    # tree can disconnect the other by renaming alone.
    module_path = next(
        (p for p in (registry_dir / "floor_registry.py", registry_dir / "registry.py")
         if p.is_file()),
        None,
    )
    if module_path is None:
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


def needs_approval(agent_id: str, action: str) -> bool | None:
    """Does this agent need OLYMPUS before performing this action?

    True  - stop and ask. The action is amber or red for this agent.
    False - proceed. The agent's own permissions allow it outright.
    None  - the floors tree is absent or its registry is stale, so this
            cannot be answered. The caller decides what to do with that;
            this module never raises and never guesses.

    None is deliberately not False. An unanswerable question is not
    permission, and a caller that treats it as permission has turned a
    missing registry into an open door.
    """
    reg = registry()
    if reg is None:
        return None
    try:
        return bool(reg.needs_approval(agent_id, action))
    except Exception:  # noqa: BLE001 - a broken registry must never break the queue
        return None


def agent_is_defined(agent_id: str) -> bool | None:
    """Does this agent exist on a floor?

    True  - it has a definition and the registry can see it.
    False - the registry works and has never heard of this agent. It was
            wired without being defined, so it carries no capabilities, no
            approval tier and no audit.
    None  - there is no floors tree, or its index is stale, so the question
            cannot be answered here.

    Callers must decide what None means for them; it is not the same answer
    in every place. Dispatch treats it as allow, because a public clone has
    no floors tree by design and refusing would stop every agent. The publish
    gate treats it as hold, because refusing to publish costs a delay and
    publishing wrongly cannot be undone.
    """
    reg = registry()
    if reg is None:
        return None
    try:
        return agent_id in reg.agents()
    except Exception:  # noqa: BLE001 - a broken registry must never break the queue
        return None


def _service(package: str, module: str) -> Any | None:
    """Import one module out of floors/_services, or None.

    The services import each other flatly - `import ledger`, `import limits` -
    so the package directory goes on sys.path rather than being imported as a
    package. Same degradation rule as everything else here: absent tree, no
    exception, None.
    """
    directory = floors_root() / "_services" / package
    path = directory / f"{module}.py"
    if not path.is_file():
        return None
    try:
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
        key = f"one_floors_{package}_{module}"
        cached = sys.modules.get(key)
        if cached is not None:
            return cached
        spec = importlib.util.spec_from_file_location(key, path)
        if spec is None or spec.loader is None:
            return None
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[key] = loaded
        spec.loader.exec_module(loaded)
        return loaded
    except Exception:  # noqa: BLE001 - a broken service must never break the queue
        sys.modules.pop(f"one_floors_{package}_{module}", None)
        return None


def may(agent_id: str, capability: str) -> bool | None:
    """Is this agent allowed to use this capability?

    True / False from the agent's own capabilities.yaml, which denies by
    default. None when the registry cannot answer.

    Callers on the execution path should treat None as allow, for the same
    reason dispatch does: a public clone has no floors tree and refusing every
    capability would stop the whole application. False is the answer that
    means something - the agent's own file says no.
    """
    reg = registry()
    if reg is None:
        return None
    try:
        return bool(reg.may(agent_id, capability))
    except Exception:  # noqa: BLE001
        return None


def audit(**fields: Any) -> bool:
    """Append one record to the company's hash-chained audit log.

    Returns True when it was written. Never raises, and never blocks the work
    it is recording - an audit that can stop a job is a new way for the job to
    fail, and this exists to observe rather than to interfere.

    The record is validated before it is written, and validation refuses a
    credential in any field, so a secret cannot be recorded by accident.
    """
    record = _service("audit", "record")
    store = _service("audit", "store")
    if record is None or store is None:
        return False
    try:
        store.AuditStore().append(record.build(**fields))
        return True
    except Exception:  # noqa: BLE001
        return False


def budget_verdict(agent_id: str, floor_id: str | None = None,
                   projected_cost: float | None = None,
                   job: dict[str, Any] | None = None) -> Any | None:
    """What the budget guard says about work that has not happened yet.

    Returns the guard's own Verdict - it carries .allowed() and .explain() -
    or None when the guard cannot be reached. The decision on projected spend
    is checked before the call is made, because a limit discovered after the
    money is gone is a report rather than a guardrail.
    """
    guard = _service("budget", "guard")
    limits_mod = _service("budget", "limits")
    audit_store = _service("audit", "store")
    if guard is None or limits_mod is None or audit_store is None:
        return None
    try:
        return guard.check(
            limits=limits_mod.Limits(),
            store=audit_store.AuditStore(),
            agent_id=agent_id,
            floor_id=floor_id,
            job=job,
            projected_cost=projected_cost,
        )
    except Exception:  # noqa: BLE001
        return None


def claim_once(idempotency_key: str, event_type: str | None = None) -> bool | None:
    """Has this exact work already been claimed?

    True  - first time, go ahead.
    False - seen before, and doing it again would repeat a real effect.
    None  - the dedupe store cannot be reached, so the question is unanswered.

    A caller deciding what None means should think about what repeating costs.
    Repeating a read is free; repeating a paid generation is not.
    """
    dedupe = _service("idempotency", "dedupe")
    if dedupe is None:
        return None
    try:
        claim = dedupe.DedupeStore().claim(idempotency_key, event_type=event_type)
        # should_act is a property, not a method. Calling it raised
        # TypeError: 'bool' object is not callable, which this module's own
        # except swallowed into None - so the dedupe looked unreachable when
        # it was working perfectly. Degrading quietly hides your own bugs as
        # readily as somebody else's.
        return bool(claim.should_act)
    except Exception:  # noqa: BLE001
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
