"""Play a video in a real, visible browser window and auto-skip ads.

Separate from browser.py's shared Playwright session on purpose: that one
runs headless=True (invisible, for research/search where nobody needs to
see the page). Video playback needs a visible window, since the whole
point is Vineet actually watching/hearing it -- open_app (os.startfile)
can open the URL but has no way to see or interact with the page
afterward, so it can never click a Skip Ad button. This tool keeps a
handle to the page and runs a background watcher for the life of the
video, clicking any Skip Ad button the instant it becomes clickable.

Design history (2026-07-19/20), each fix confirmed live before moving on:
1. Started with a PERSISTENT Chrome profile so a manually-solved CAPTCHA
   would stick. Broke because several ad-hoc STANDALONE TEST SCRIPTS (each
   its own Python process, run directly by hand during development, not
   through the real server) opened the same profile directory at once --
   Chrome's SingletonLock allows one process per profile, so they fought
   each other: a stuck window on about:blank, YouTube's "Something went
   wrong".
2. Switched to a fresh/incognito-style context per call to kill that class
   of bug outright. Fixed the corruption, but a fresh profile has zero
   provisioned components every single time -- see next.
3. Root-caused "Something went wrong" (a DIFFERENT instance of it, on a
   real DRM video this time) to two of Playwright's default launch args:
   --enable-unsafe-swiftshader forces software rendering despite this
   machine's real GPU, and --disable-component-update blocks the Widevine
   CDM (DRM module most commercial/label content needs) from ever being
   fetched -- confirmed directly via chrome://components showing no
   Widevine entry with the flag present, a real one (4.10.3050.0) with it
   excluded.
4. Widevine has to be fetched over the network once it's allowed to be --
   doing that from a blank profile on every single call means re-fetching
   it (and racing the video's own load) every time. So: back to a
   PERSISTENT profile for Widevine/cookies to actually stick, but this
   time as a proper in-process singleton, reused across calls within one
   server run instead of re-launched -- which is what actually caused
   step 1's conflict (concurrent SEPARATE PROCESSES each launching fresh,
   not the persistence itself). As long as nothing outside this module
   opens the same profile directory concurrently, there's exactly one
   process holding the lock at a time.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# Text/selector patterns YouTube has used for its skip-ad button over the
# years. Text-based lookup is more resilient to YouTube's own class-name
# churn than pinning to a single CSS class, so both are tried.
_SKIP_AD_SELECTORS = [
    ".ytp-skip-ad-button",
    ".ytp-ad-skip-button",
    ".ytp-ad-skip-button-modern",
    "button.ytp-ad-skip-button-slot",
]
_SKIP_AD_TEXT_PATTERNS = ["Skip Ad", "Skip Ads", "Skip ad", "Skip ads"]

_POLL_INTERVAL_SECONDS = 1.5
_WATCH_DURATION_SECONDS = 900  # 15 minutes -- covers most videos' ad windows

_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = window.chrome || { runtime: {} };
"""

# Playwright's default launch args target headless CI environments and
# actively break real video playback -- see module docstring point 3.
# --no-sandbox added 2026-07-20: confirmed live via Chrome's own banner
# ("You are using an unsupported command-line flag: --no-sandbox.
# Stability and security will suffer.") on a SECOND, different video
# (not the same DRM-specific one Widevine fixed) -- "Something went
# wrong" recurred there too, meaning it was never purely a Widevine
# issue, it's general renderer/GPU-process instability from running
# unsandboxed. --no-sandbox exists in Playwright's defaults for Linux
# CI/root environments where the sandbox often can't initialize at all;
# this is a normal Windows user session, which doesn't need it.
_IGNORED_DEFAULT_ARGS = [
    "--enable-unsafe-swiftshader",
    "--disable-component-update",
    "--no-sandbox",
]


def _try_skip_once(page: Any) -> bool:
    """Attempt one skip-ad click. Returns True if something was clicked."""
    for selector in _SKIP_AD_SELECTORS:
        try:
            el = page.query_selector(selector)
            if el is not None and el.is_visible():
                el.click(timeout=1000)
                return True
        except Exception:
            continue
    for text in _SKIP_AD_TEXT_PATTERNS:
        try:
            el = page.get_by_text(text, exact=False).first
            if el is not None and el.is_visible():
                el.click(timeout=1000)
                return True
        except Exception:
            continue
    return False


def _watch_and_skip_ads(page: Any, duration_seconds: float, stop_event: threading.Event) -> None:
    """Background loop: click any skip-ad button that appears, for a while.

    stop_event lets a NEWER call cancel an OLDER call's still-running
    watcher. Confirmed live (2026-07-20): the page object is reused across
    play_video calls (see _VideoSession below), but each call used to spawn
    its own independent 15-minute watcher thread with no way to stop the
    previous one -- playing a second video while the first's watcher was
    still active meant two threads calling Playwright's sync API on the
    SAME page concurrently. That API is not safe to call from multiple
    threads at once; this is the most likely real cause of the
    intermittent "Something went wrong" crashes that kept recurring after
    every Chrome-launch-flag fix (swiftshader, component-update,
    sandbox) -- those were all real, individually confirmed issues, but
    apparently not the only one.
    """
    deadline = time.time() + duration_seconds
    while time.time() < deadline:
        if stop_event.is_set():
            return
        try:
            if page.is_closed():
                return
            _try_skip_once(page)
        except Exception:
            return
        time.sleep(_POLL_INTERVAL_SECONDS)


class _VideoSession:
    """Dedicated, VISIBLE, PERSISTENT Playwright session for video playback.

    A module-level singleton -- reused across every play_video call within
    one running ONE server process. Never launch a second one against the
    same profile directory from anywhere else (a standalone test script,
    a second tool, etc.) -- that reintroduces the SingletonLock conflict
    documented in the module docstring.
    """

    def __init__(self) -> None:
        self._playwright = None
        self._context = None
        self._page = None
        # Stop-signal for whichever ad-skip watcher thread is currently
        # active on self._page, if any -- see _watch_and_skip_ads.
        self._watcher_stop_event: threading.Event | None = None

    def cancel_watcher(self) -> None:
        """Signal any currently-running ad-skip watcher thread to stop.

        Must be called before starting a new one against the reused page --
        otherwise two watcher threads end up calling Playwright's sync API
        on the same page concurrently, which is not safe.
        """
        if self._watcher_stop_event is not None:
            self._watcher_stop_event.set()

    def start_watcher(self, duration_seconds: float) -> None:
        """Cancel any previous watcher, then start a fresh one on self._page."""
        self.cancel_watcher()
        stop_event = threading.Event()
        self._watcher_stop_event = stop_event
        threading.Thread(
            target=_watch_and_skip_ads,
            args=(self._page, duration_seconds, stop_event),
            daemon=True,
            name="ghost-agent-ad-skip-watcher",
        ).start()

    def _profile_dir(self):
        from openjarvis.core.paths import get_config_dir

        d = get_config_dir() / "ghost_agent_video_profile"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _ensure_browser(self) -> None:
        if self._page is not None and not self._page.is_closed():
            return
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            str(self._profile_dir()),
            headless=False,
            channel="chrome",
            # --start-maximized + no_viewport=True together make the page
            # use the real (maximized) window size instead of Playwright's
            # default fixed 1280x720 viewport -- the fixed viewport
            # rendered inside a maximized window is what produced the
            # "half screen" look.
            args=["--start-maximized"],
            no_viewport=True,
            ignore_default_args=_IGNORED_DEFAULT_ARGS,
        )
        self._page = (
            self._context.pages[0] if self._context.pages else self._context.new_page()
        )
        self._page.add_init_script(_STEALTH_INIT_SCRIPT)

    @property
    def page(self) -> Any:
        self._ensure_browser()
        return self._page


_video_session = _VideoSession()


@ToolRegistry.register("play_video")
class PlayVideoTool(BaseTool):
    """Open a video URL in a real visible browser and auto-skip ads."""

    tool_id = "play_video"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="play_video",
            description=(
                "Open a video (e.g. a specific YouTube watch URL found via "
                "web_search) in a real, visible, maximized browser window, "
                "and automatically click any 'Skip Ad' button that appears "
                "for as long as the video plays -- Vineet should never need "
                "to click Skip himself. Use this INSTEAD of open_app "
                "whenever the target is a video you want actually playing "
                "(not just any page you want opened). Reuses the same "
                "browser session across calls -- if Google shows a "
                "CAPTCHA, Vineet needs to solve it himself in that window "
                "the first time; this tool will never attempt to solve it, "
                "but the solve then sticks for future calls."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": (
                            "Direct video URL to play (e.g. a "
                            "youtube.com/watch?v=... link)."
                        ),
                    },
                },
                "required": ["url"],
            },
            category="local_execution",
            cost_estimate=0.0,
            timeout_seconds=20,
        )

    def _try_via_extension(self, url: str) -> ToolResult | None:
        """Try opening the video through the ONE Ghost Agent Chrome
        extension in Vineet's own real browser, if it's connected.

        Confirmed root cause (2026-07-20) of most of this tool's crash
        history: the Playwright path below opens a separate, cookie-less,
        unauthenticated automation Chrome profile, which YouTube/Google
        treats very differently from Vineet's real logged-in session
        (CAPTCHA challenges the real browser never sees), on top of a long
        tail of separate-process issues (SingletonLock conflicts, orphaned
        processes, the whole automation window dying whenever the ONE
        server process itself restarts). Per Vineet's own suggestion, the
        extension controls tabs in his REAL browser instead -- same model
        as Anthropic's own "Claude in Chrome". Returns None (not a
        ToolResult) when the extension isn't connected, so the caller falls
        through to the Playwright path unchanged -- this is purely
        additive, zero risk if Vineet hasn't loaded the extension yet.
        """
        from openjarvis.server.ghost_extension_bridge import (
            enqueue_open_video,
            extension_is_live,
            pop_result,
        )

        if not extension_is_live():
            return None

        command_id = enqueue_open_video(url)
        deadline = time.time() + 12.0
        while time.time() < deadline:
            result = pop_result(command_id)
            if result is not None:
                if result["success"]:
                    return ToolResult(
                        tool_name=self.tool_id,
                        content=(
                            f"Opened {url} in your browser, Sir. The ONE "
                            "extension will auto-skip any ads."
                        ),
                        success=True,
                        metadata={"url": url, "via": "extension"},
                    )
                # Extension picked up the command but failed to act on it
                # (e.g. chrome.tabs.create threw) -- fall back to Playwright
                # rather than surfacing a hard failure to Vineet.
                return None
            time.sleep(0.2)
        # Extension claimed to be live but never answered -- fall back
        # rather than leaving Vineet with neither path having worked.
        return None

    def execute(self, **params: Any) -> ToolResult:
        url = str(params.get("url", "")).strip()
        if not url:
            return ToolResult(tool_name=self.tool_id, content="No URL provided.", success=False)

        from openjarvis.security.ssrf import check_ssrf

        ssrf_error = check_ssrf(url)
        if ssrf_error:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"SSRF blocked: {ssrf_error}",
                success=False,
            )

        extension_result = self._try_via_extension(url)
        if extension_result is not None:
            return extension_result

        try:
            # Cancel any watcher left over from a PREVIOUS play_video call
            # before touching the (reused) page at all -- see
            # _watch_and_skip_ads's docstring for why this matters: two
            # watcher threads calling Playwright's sync API on the same
            # page concurrently is a real, confirmed cause of intermittent
            # crashes here.
            _video_session.cancel_watcher()
            page = _video_session.page
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except ImportError:
            return ToolResult(
                tool_name=self.tool_id,
                content="playwright not installed. Install with: uv sync --extra browser",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Failed to open video: {exc}",
                success=False,
            )

        # Try an immediate skip (covers the common case where a pre-roll ad
        # is already showing by the time the page settles) before handing
        # off to the background watcher, so the first ad doesn't have to
        # wait a full poll cycle.
        try:
            _try_skip_once(page)
        except Exception:
            pass

        _video_session.start_watcher(_WATCH_DURATION_SECONDS)

        return ToolResult(
            tool_name=self.tool_id,
            content=f"Playing {url}. Any Skip Ad button will be clicked automatically as it appears.",
            success=True,
            metadata={"url": url},
        )


__all__ = ["PlayVideoTool"]
