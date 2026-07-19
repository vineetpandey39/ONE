"""Play a video in a real, visible browser window and auto-skip ads.

Separate from browser.py's shared Playwright session on purpose: that one
runs headless=True (invisible, for research/search where nobody needs to
see the page). Video playback needs a visible window, since the whole
point is Vineet actually watching/hearing it -- open_app (os.startfile)
can open the URL but has no way to see or interact with the page
afterward, so it can never click a Skip Ad button. This tool keeps a
handle to the page and runs a background watcher for the life of the
video, clicking any Skip Ad button the instant it becomes clickable.
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


def _watch_and_skip_ads(page: Any, duration_seconds: float) -> None:
    """Background loop: click any skip-ad button that appears, for a while."""
    deadline = time.time() + duration_seconds
    while time.time() < deadline:
        try:
            if page.is_closed():
                return
            _try_skip_once(page)
        except Exception:
            return
        time.sleep(_POLL_INTERVAL_SECONDS)


class _VideoSession:
    """Dedicated, VISIBLE, PERSISTENT Playwright session for video playback.

    Confirmed live (2026-07-19): even real Chrome (channel="chrome", not
    Playwright's bundled Chromium) plus JS-side stealth patches still hit
    Google's "unusual traffic" CAPTCHA wall on youtube.com/watch pages --
    including on a video never touched before, and even though the plain
    youtube.com homepage loaded fine. That rules out per-video or pure
    fingerprint causes; it's Google flagging this IP for the /watch
    endpoint specifically, most likely from the sheer volume of automated
    requests generated while building and testing this tool today.
    Completing that CAPTCHA programmatically is not something this tool
    will ever do -- it's explicitly against policy here and against
    Google's own terms. What IS legitimate: the window is real and visible,
    so Vineet can solve it himself the one time it appears. A PERSISTENT
    context (a real profile directory on disk, not a fresh throwaway
    session per call) means that solve -- and any Google/YouTube login --
    sticks in cookies for every future call, including across ONE server
    restarts, instead of needing to be redone constantly.
    """

    def __init__(self) -> None:
        self._playwright = None
        self._context = None
        self._page = None

    def _profile_dir(self):
        from pathlib import Path

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
        )
        self._page = (
            self._context.pages[0] if self._context.pages else self._context.new_page()
        )
        self._page.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = window.chrome || { runtime: {} };
            """
        )

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
                "web_search) in a real, visible browser window, and "
                "automatically click any 'Skip Ad' button that appears for as "
                "long as the video plays -- Vineet should never need to click "
                "Skip himself. Use this INSTEAD of open_app whenever the "
                "target is a video you want actually playing (not just any "
                "page you want opened)."
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

        try:
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

        threading.Thread(
            target=_watch_and_skip_ads,
            args=(page, _WATCH_DURATION_SECONDS),
            daemon=True,
            name="ghost-agent-ad-skip-watcher",
        ).start()

        return ToolResult(
            tool_name=self.tool_id,
            content=f"Playing {url}. Any Skip Ad button will be clicked automatically as it appears.",
            success=True,
            metadata={"url": url},
        )


__all__ = ["PlayVideoTool"]
