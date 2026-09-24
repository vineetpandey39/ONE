#!/usr/bin/env python3
# ruff: noqa: E501
"""Say which link in the PostForge cockpit chain is broken.

The tab needs five separate things to be true, and when it is blank it never
says which one failed. Run this and it names the one that did:

    python scripts/postforge_selfcheck.py

Checks, in the order a refresh actually depends on them: the code is present,
the running server exposes the routes, the browser bundle was rebuilt after the
code arrived, Sanjeevani is loadable and exposes what the feed calls, and a real
refresh returns rows that the verifier can read. The last check also prints the
key names SearXNG actually returned, which is the one thing that cannot be
predicted from this repo alone.

Nothing here writes; the live refresh is the same one the tab runs.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "src" / "openjarvis" / "server" / "static"

OK = "  OK   "
BAD = " FAIL  "
WARN = " WARN  "


def say(status: str, title: str, detail: str = "") -> None:
    print(f"[{status}] {title}")
    for line in str(detail).splitlines():
        if line.strip():
            print(f"         {line}")


def check_code() -> bool:
    """Is the branch that carries the feed actually checked out here?"""
    try:
        from openjarvis.postforge import feed

        say(OK, "PostForge module importable", f"{len(feed.PILLARS)} pillars, {feed.fresh_hours()}h window")
        return True
    except ImportError as exc:
        say(BAD, "PostForge module missing", f"{exc}\ngit pull, then: git checkout claude/jolly-volta-1p85uu")
        return False


def check_server() -> bool:
    """Is the process that is serving the cockpit running this code?"""
    base = os.environ.get("ONE_API_URL", "http://127.0.0.1:8000").rstrip("/")
    try:
        import httpx

        response = httpx.get(f"{base}/v1/postforge/pillars", timeout=5)
    except Exception as exc:  # noqa: BLE001 - any failure here means "cannot reach it"
        say(WARN, f"Server unreachable at {base}", f"{type(exc).__name__}: {exc}\nStart ONE, or set ONE_API_URL.")
        return False

    if response.status_code == 404:
        say(BAD, "Server is running OLD code", "/v1/postforge/pillars is 404 -- restart ONE so the new router loads.")
        return False
    if response.status_code != 200:
        say(BAD, f"Server returned {response.status_code}", response.text[:300])
        return False
    say(OK, "Server exposes /v1/postforge", f"{base} -> {response.json().get('freshnessHours')}h window")
    return True


def check_bundle() -> bool:
    """The cockpit is served from a built bundle that git does not track.

    ``src/openjarvis/server/static/`` is gitignored, so pulling the branch does
    not update the page the browser loads. Without a rebuild the tab is simply
    absent, with no error anywhere -- the single most likely reason it "does not
    run" after a pull.
    """
    assets = list((STATIC / "assets").glob("*.js")) if (STATIC / "assets").is_dir() else []
    if not assets:
        say(BAD, "No built frontend bundle", f"{STATIC} is empty.\nRun: cd frontend && npm install && npm run build")
        return False
    for path in assets:
        if "one-postforge-board" in path.read_text(encoding="utf-8", errors="ignore"):
            say(OK, "Frontend bundle contains the PostForge tab", path.name)
            return True
    say(BAD, "Frontend bundle predates the PostForge tab", "Run: cd frontend && npm run build")
    return False


def check_sanjeevani() -> bool:
    """Loadable, and carrying the three entry points the feed calls."""
    from openjarvis.postforge import feed

    path = os.environ.get("SANJEEVANI_RESEARCH_LIBRARY", r"E:\ONE-SUITE\sanjeevani\research_library.py")
    library = feed._sanjeevani()
    if library is None:
        say(BAD, "Sanjeevani not loaded", f"Looked for: {path}\nSet SANJEEVANI_RESEARCH_LIBRARY to research_library.py.")
        return False

    missing = [name for name in ("searxng", "_get", "_safe_public_url") if not hasattr(library, name)]
    if missing:
        say(BAD, "Sanjeevani is loaded but incomplete", f"Missing: {', '.join(missing)}")
        return False
    say(OK, "Sanjeevani loaded", getattr(library, "__file__", path))
    return True


def check_refresh(pillar: str) -> bool:
    """The real thing, including what SearXNG's rows actually look like."""
    from openjarvis.postforge import feed

    library = feed._sanjeevani()
    if library is None:
        return False

    queries = feed.select_queries(pillar)
    try:
        rows = feed.search_rows(queries[:1], library=library)
    except Exception as exc:  # noqa: BLE001 - the operator needs the reason verbatim
        say(BAD, "SearXNG search failed", f"{type(exc).__name__}: {exc}\nIs Sanjeevani's SearXNG container up?")
        return False

    if not rows:
        say(WARN, "SearXNG returned no rows", f"Query: {queries[0][:90]}\nSearXNG is reachable but found nothing.")
        return False

    # The feed reads several spellings per field; this shows which ones this
    # SearXNG actually uses, so a mapping gap is visible instead of silent.
    sample = rows[0]
    say(OK, f"SearXNG returned {len(rows)} rows", "Row keys: " + ", ".join(sorted(sample.keys())))
    mapped = feed.row_to_candidate(sample)
    unmapped = [field for field in ("url", "headline") if not mapped.get(field)]
    if unmapped:
        say(BAD, "Row fields did not map", f"Empty after mapping: {', '.join(unmapped)}\nSample row:\n{json.dumps(sample, indent=2, default=str)[:600]}")
        return False

    payload = feed.refresh(pillar, force=True)
    verified, rejected = len(payload["items"]), payload["rejected"]
    if verified:
        say(OK, f"Refresh verified {verified} item(s)", "\n".join(item["headline"] for item in payload["items"][:3]))
        return True

    reasons = "\n".join(f"{row['reason']} <- {row['url']}" for row in payload["rejectedReasons"][:5])
    say(
        WARN,
        f"Refresh verified 0 items, rejected {rejected}",
        reasons or "Nothing was published in the window, or SearXNG found nothing dated.",
    )
    return False


def check_kairos() -> bool:
    """Is KAIROS's carousel brief actually being grounded in the feed?"""
    from openjarvis.one_agents import runtime

    switch = os.environ.get("ONE_KAIROS_VERIFIED_FEED", "1").strip().lower()
    if switch in ("0", "false", "no"):
        say(WARN, "KAIROS grounding is switched off", "ONE_KAIROS_VERIFIED_FEED=" + switch)
        return False

    pillar = os.environ.get("ONE_KAIROS_PILLAR") or os.environ.get("TITAN_DEFAULT_PILLAR") or "news"
    angle, path, count = runtime._kairos_grounded_angle("self-check", "selfcheck", [])
    if not count:
        say(WARN, "KAIROS would be briefed un-grounded today", f"Pillar '{pillar}' verified nothing; the lane falls back to the operator's own angle, exactly as before this feed existed.")
        return False
    say(OK, f"KAIROS brief carries {count} verified source(s)", f"Pillar '{pillar}', evidence at {path}")
    return True


def check_ollama() -> bool:
    """Generation needs a local model; refresh does not."""
    base = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    try:
        import httpx

        models = httpx.get(f"{base}/api/tags", timeout=5).json().get("models", [])
    except Exception as exc:  # noqa: BLE001
        say(WARN, "Ollama unreachable", f"{type(exc).__name__}: {exc}\nThe feed still works; generation will not.")
        return False
    say(OK, f"Ollama has {len(models)} model(s)", os.environ.get("ONE_LOCAL_RESEARCH_MODEL", "qwen3.5:9b"))
    return True


def main() -> int:
    pillar = sys.argv[1] if len(sys.argv) > 1 else "news"
    print(f"PostForge self-check ({pillar})\n")

    if not check_code():
        return 1
    check_server()
    check_bundle()
    if check_sanjeevani():
        check_refresh(pillar)
        check_kairos()
    check_ollama()

    print("\nEach FAIL above carries its own fix. WARN means that step is not blocking the feed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
