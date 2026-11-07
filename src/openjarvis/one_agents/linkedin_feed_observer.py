"""The browser half of ORION's feed observer: look at LinkedIn the way a person scrolling it would, and hand back what
each rendered post shows. Reads only.

What this module does NOT do, by construction: it never types, never clicks anything on a page, never likes, follows,
connects, messages or comments, and it never handles a password. Signing in is a one-time human step (`sign_in`, run
by the Chairman in a visible window); the session lives in a dedicated Chrome profile that is not the Chairman's daily
profile. When the session is missing or LinkedIn asks for a check, the observer stops, records why, and stays stopped
until the Chairman signs in again. It never tries to get past a login wall, a checkpoint or a CAPTCHA.

LinkedIn's User Agreement forbids automated access to its pages and a restricted account is a real possibility, so the
footprint is kept small and is policy-controlled (engage/policy.json "observer"): a handful of page visits per cycle,
a daily visit cap, human-paced scrolling and a 24 hour cool-off after any block signal.

What a post IS (urn, author, text, age) is decided offline in floors/floor_03_growth/lib/engage_feed.py.
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any, Callable

CHROME = Path(os.environ.get("ONE_LINKEDIN_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe"))
LOGIN_MARKERS = ("/login", "/authwall", "/uas/", "/signup")
CHALLENGE_MARKERS = ("/checkpoint/", "/challenge")
BLOCK_PHRASES = ("unusual activity", "we've restricted", "we have restricted", "temporarily restricted",
                 "verify you're not a robot", "verify you are not a robot", "too many requests")
COOL_OFF_SECONDS = 24 * 3600


def profile_dir(home: Path) -> Path:
    return home / "linkedin-observer-profile"


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now + 19800))  # IST


def state_of(state_path: Path) -> dict[str, Any]:
    return _load(state_path)


def may_observe(cfg: dict[str, Any], state: dict[str, Any], now: float, visits_wanted: int) -> tuple[bool, str]:
    """The observer's own gate, checked before any browser starts."""
    if not cfg.get("enabled", False):
        return False, "disabled"
    if state.get("login_required"):
        return False, "login_required"
    if float(state.get("blocked_until", 0)) > now:
        return False, "cooling_off"
    today = state.get("day") == _day(now)
    used = int(state.get("visits_today", 0)) if today else 0
    if used + visits_wanted > int(cfg.get("visits_per_day", 12)):
        return False, "daily_visit_cap"
    return True, ""


def _page_problem(url: str, text: str) -> str:
    low = (url or "").lower()
    if any(m in low for m in CHALLENGE_MARKERS):
        return "challenge"
    if any(m in low for m in LOGIN_MARKERS):
        return "login"
    body = (text or "").lower()[:4000]
    if any(p in body for p in BLOCK_PHRASES):
        return "blocked"
    return ""


def _launch(playwright: Any, profile: Path, headless: bool) -> Any:
    kwargs: dict[str, Any] = {"headless": headless, "viewport": {"width": 1280, "height": 900},
                              "args": ["--window-position=-2400,-2400", "--window-size=1280,900"]}
    if CHROME.is_file():
        kwargs["executable_path"] = str(CHROME)
    return playwright.chromium.launch_persistent_context(str(profile), **kwargs)


def observe(visits: list[dict[str, str]], *, cfg: dict[str, Any], state_path: Path, profile: Path,
            posts_js: str, pair: Callable[[str], dict[str, str]] | None = None, now: float | None = None,
            sleep: Callable[[float], None] = time.sleep, launch: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Visit each page, scroll a little, read the rendered posts. Returns {status, detail, visits}.

    status: ok | partial | disabled | login_required | challenge | cooling_off | daily_visit_cap | error.
    `launch` is injectable for tests; production uses Playwright's persistent context on the dedicated profile.
    `pair` turns one feed payload body into {card key hash: activity URN}: the current feed renders cards without their
    URN, so the payloads the page itself loaded are read (never fetched separately) to tie each card to its post.
    """
    at = time.time() if now is None else now
    state = _load(state_path)
    allowed, why = may_observe(cfg, state, at, len(visits))
    if not allowed:
        return {"status": why, "detail": why.replace("_", " "), "visits": []}
    if not profile.exists():
        state.update(login_required=True, last_status="login_required", last_status_at=at)
        _save(state_path, state)
        return {"status": "login_required", "detail": "no signed-in observer profile yet", "visits": []}

    results: list[dict[str, Any]] = []
    status, detail = "ok", ""
    scrolls = max(1, int(cfg.get("scrolls", 5)))
    pause = cfg.get("pause_seconds", [22, 45])
    scroll_wait = cfg.get("scroll_wait_seconds", [2.5, 5.0])
    context = None
    playwright = None
    try:
        if launch is None:
            from playwright.sync_api import sync_playwright
            playwright = sync_playwright().start()
            context = _launch(playwright, profile, headless=bool(cfg.get("headless", False)))
        else:
            context = launch(profile)
        page = context.pages[0] if context.pages else context.new_page()
        for index, visit in enumerate(visits):
            if index:
                sleep(random.uniform(*pause))
            entry: dict[str, Any] = {"label": visit.get("label", ""), "url": visit["url"], "posts": []}
            results.append(entry)
            bodies: list[str] = []

            def keep(resp: Any, _bag: list[str] = bodies) -> None:
                # Read the body now: a streamed pagination response is gone by the time the scrolling is over.
                if "sduiid=" in resp.url or "rsc-action" in resp.url:
                    try:
                        _bag.append(resp.text())
                    except Exception:  # noqa: BLE001 - an unreadable payload only costs its own pairings
                        pass

            try:
                if pair is not None:
                    page.on("response", keep)
                document = page.goto(visit["url"], wait_until="domcontentloaded", timeout=45000)
                if pair is not None and document is not None:
                    try:
                        bodies.append(document.text())
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    page.wait_for_selector("main", timeout=15000)
                except Exception:  # noqa: BLE001 - a page without <main> is judged below by what it says
                    pass
                sleep(random.uniform(2.0, 4.0))
                problem = _page_problem(page.url, _body_text(page))
                if problem:
                    entry["error"] = problem
                    status, detail = ("login_required" if problem == "login" else
                                      "challenge" if problem in {"challenge", "blocked"} else "error"), problem
                    break
                page.mouse.move(640, 450)
                for _ in range(scrolls):
                    page.mouse.wheel(0, random.randint(700, 1100))
                    sleep(random.uniform(*scroll_wait))
                payload = page.evaluate(posts_js) or {}
                entry["posts"] = list(payload.get("posts") or [])
                if pair is not None:
                    entry["urn_by_key"] = _pairs(pair, bodies)
            except Exception as exc:  # noqa: BLE001 - one bad page must not cost the others
                entry["error"] = f"{type(exc).__name__}: {exc}"[:160]
                status = "partial"
            finally:
                if pair is not None:
                    try:
                        page.remove_listener("response", keep)
                    except Exception:  # noqa: BLE001
                        pass
    except Exception as exc:  # noqa: BLE001 - a browser that will not start is reported, not hidden
        status, detail = "error", f"{type(exc).__name__}: {exc}"[:200]
    finally:
        for closer in (getattr(context, "close", None), getattr(playwright, "stop", None)):
            try:
                if closer:
                    closer()
            except Exception:  # noqa: BLE001 - teardown must never mask the result
                pass

    state = _load(state_path)
    today = state.get("day") == _day(at)
    state.update(day=_day(at), visits_today=(int(state.get("visits_today", 0)) if today else 0) + len(results),
                 last_status=status, last_status_at=at)
    if status == "ok" and any(r["posts"] for r in results):
        state["last_ok_at"] = at
    if status == "login_required":
        state["login_required"] = True
    if status == "challenge":
        state["blocked_until"] = at + COOL_OFF_SECONDS
    _save(state_path, state)
    return {"status": status, "detail": detail, "visits": results}


def _pairs(pair: Callable[[str], dict[str, str]], bodies: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for body in bodies:
        try:
            out.update(pair(body))
        except Exception:  # noqa: BLE001 - one unreadable payload must not cost the rest
            continue
    return out


def _body_text(page: Any) -> str:
    try:
        return page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 4000)") or ""
    except Exception:  # noqa: BLE001
        return ""


def sign_in(profile: Path, state_path: Path, *, wait_seconds: int = 900) -> str:
    """The one human step. Opens a VISIBLE Chrome on the dedicated profile; the Chairman signs in himself (this code
    never sees or types the password); once the home feed is showing, the session is kept and the observer is re-armed."""
    from playwright.sync_api import sync_playwright
    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        kwargs: dict[str, Any] = {"headless": False, "viewport": {"width": 1280, "height": 900}}
        if CHROME.is_file():
            kwargs["executable_path"] = str(CHROME)
        context = pw.chromium.launch_persistent_context(str(profile), **kwargs)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60000)
            deadline = time.time() + wait_seconds
            while time.time() < deadline:
                time.sleep(3)
                try:
                    url = page.url
                except Exception:  # noqa: BLE001 - the window was closed
                    return "window closed before sign-in finished"
                if "linkedin.com/feed" in url:
                    time.sleep(4)  # let the session cookies settle to disk
                    state = _load(state_path)
                    state.pop("login_required", None)
                    state.update(signed_in_at=time.time(), last_status="signed_in")
                    _save(state_path, state)
                    return "signed in; the observer is armed"
            return "timed out waiting for the home feed"
        finally:
            try:
                context.close()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":  # python -m openjarvis.one_agents.linkedin_feed_observer sign-in
    import sys

    home = Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))
    base = home / "agent_outputs" / "linkedin" / "engage"
    if len(sys.argv) > 1 and sys.argv[1] == "sign-in":
        print(sign_in(profile_dir(home), base / "observer_state.json"))
    else:
        print(json.dumps(state_of(base / "observer_state.json"), indent=1))
