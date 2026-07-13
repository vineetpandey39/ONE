"""Image-to-video tool — drives Leonardo's web app via a real browser.

Why this exists: Leonardo's REST API (``leonardo_video_tool.py``) and the
*web app* (app.leonardo.ai) draw from two different credit pools. Confirmed
live on 2026-06-23 by inspecting network traffic while clicking Generate on
app.leonardo.ai: the web app talks to ``https://api.leonardo.ai/v1/graphql``
using the browser's own session cookie, and a 504-credit Kling 3.0 clip was
deducted from the "AI Creation" subscription wallet (38,016 -> 37,512) --
NOT from the separate LEONARDO_API_KEY pay-as-you-go balance the REST tool
uses. Subscription credits are bundled into the monthly plan price, so
spending them through the web app is effectively free per-clip (up to the
monthly allotment), while the REST API bills every clip at full pay-as-you-go
rates.

This tool does NOT replicate the GraphQL calls directly (that would mean
extracting and handling the user's session cookie/auth token ourselves,
which is credential-equivalent and something we don't do). Instead it drives
an actual Chrome window via Playwright, reusing a *dedicated, persistent*
browser profile the user logs into once by hand (see
``scripts/leonardo_browser_login.py``). After that one-time manual login,
this profile's cookies persist across runs, so every subsequent call here
acts as that already-authenticated user -- no token ever passes through our
code.

Flow per call:
  1. Launch (or reuse) a persistent Chromium context bound to the profile
     dir in LEONARDO_CHROME_PROFILE_DIR.
  2. Navigate to app.leonardo.ai/generate with the Kling 3.0 + dimensions
     query params pre-set.
  3. Upload the start frame and end frame images via the page's file inputs.
  4. Fill the prompt box and click Generate.
  5. Poll the new generation card until its <video> element has a real src
     (not the pending-loader placeholder), or timeout.
  6. Download the resulting video file via the same authenticated context.

Requires: ``pip install playwright`` + ``playwright install chromium`` on
the machine this runs on (the user's own always-on PC, not a sandbox).
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_GENERATE_URL = (
    "https://app.leonardo.ai/generate"
    "?model=kling-3.0&aspectRatio={aspect}&size={size}&duration={duration}"
    "&quantity=1&seedEnabled=false&negativePromptEnabled=false"
)

_ASPECT_BY_ORIENTATION = {"portrait": "9:16", "landscape": "16:9"}
_VALID_SIZES = {"RESOLUTION_720", "RESOLUTION_1080"}
_PENDING_MARKERS = ("pending-loader", "blob:")
_LAO_PROFILE_DIR = Path.home() / "Documents" / "LAO" / "task-capture-browser-profile-leonardo"


class _BrowserAutomationError(RuntimeError):
    """Raised internally to short-circuit to a ToolResult failure."""


def _profile_dir() -> Path:
    configured = os.environ.get("LEONARDO_CHROME_PROFILE_DIR")
    if configured:
        return Path(configured).expanduser()
    if _LAO_PROFILE_DIR.exists():
        return _LAO_PROFILE_DIR
    return Path.home() / ".openjarvis" / "leonardo_browser_profile"


def _launch_context(playwright: Any, headless: bool):
    profile = _profile_dir()
    if not profile.exists():
        raise _BrowserAutomationError(
            "No Leonardo browser profile found at"
            f" {profile}. Run scripts/leonardo_browser_login.py once to log"
            " into Leonardo manually -- after that this tool reuses the"
            " saved session automatically."
        )
    return playwright.chromium.launch_persistent_context(
        str(profile),
        headless=headless,
        channel="chrome",
        viewport={"width": 1920, "height": 1080},
    )


def _click_first(page: Any, selectors: Iterable[str], timeout_ms: int = 8000) -> bool:
    for selector in selectors:
        try:
            target = page.locator(selector).first
            target.click(timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False


def _ensure_audio_off(page: Any) -> None:
    """Best-effort: Leonardo keeps changing the switch markup."""
    candidates = [
        "[aria-label='Audio']",
        "[role='switch'][aria-checked='true']",
        "button:has-text('on')",
        "text=on",
    ]
    for selector in candidates:
        try:
            loc = page.locator(selector).first
            if loc.count() == 0:
                continue
            checked = loc.get_attribute("aria-checked")
            text = ""
            try:
                text = loc.inner_text(timeout=1000).strip().lower()
            except Exception:
                pass
            if checked == "true" or text == "on":
                loc.click(timeout=3000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def _ensure_full_hd(page: Any) -> None:
    _click_first(
        page,
        [
            "label:has-text('Full HD')",
            "text=Full HD",
            "button:has-text('Full HD')",
        ],
        timeout_ms=4000,
    )


def _open_reference_controls(page: Any) -> None:
    _click_first(
        page,
        [
            "[aria-label='Add reference to generation']",
            "button:has-text('Add reference to generation')",
            "button:has-text('Add')",
            "text=Add",
        ],
        timeout_ms=5000,
    )
    page.wait_for_timeout(700)


def _upload_frame(page: Any, button_label_regex: str, image_path: str) -> None:
    """Set a local file on the start/end frame uploader.

    Tries the direct hidden <input type=file> first (most robust — no click
    needed); falls back to clicking the labeled button and catching the
    resulting file chooser, in case the input is rendered lazily.
    """
    for _ in range(2):
        file_inputs = page.locator("input[type='file']")
        count = file_inputs.count()
        if count > 0:
            target_index = 0 if "start" in button_label_regex.lower() else min(1, count - 1)
            try:
                file_inputs.nth(target_index).set_input_files(image_path)
                return
            except Exception:
                pass
        _open_reference_controls(page)

    button_names = [
        button_label_regex,
        r"upload|choose|select.*file|add.*image|image",
    ]
    last_error: Optional[Exception] = None
    for name_pattern in button_names:
        try:
            button = page.get_by_role("button", name=re.compile(name_pattern, re.I)).first
            with page.expect_file_chooser(timeout=15000) as chooser_info:
                button.click()
            chooser_info.value.set_files(image_path)
            return
        except Exception as exc:
            last_error = exc
            continue
    raise _BrowserAutomationError(
        f"Could not find a Leonardo file upload control for {button_label_regex}: {last_error}"
    )


def _read_credit_balance(page: Any) -> Optional[int]:
    try:
        text = page.get_by_role("button", name=re.compile("token balance", re.I)).inner_text(
            timeout=3000
        )
        digits = re.sub(r"[^0-9]", "", text)
        return int(digits) if digits else None
    except Exception:
        return None


def _wait_for_video(page: Any, timeout_seconds: float, existing_sources: Optional[set[str]] = None) -> str:
    existing_sources = existing_sources or set()
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        videos = page.locator("video")
        n = videos.count()
        for i in reversed(range(n)):
            src = videos.nth(i).get_attribute("src") or ""
            if (
                src
                and src not in existing_sources
                and not any(marker in src for marker in _PENDING_MARKERS)
            ):
                return src
        page.wait_for_timeout(4000)
    raise _BrowserAutomationError(
        f"Timed out after {timeout_seconds:.0f}s waiting for the clip to finish rendering."
    )


@ToolRegistry.register("leonardo_browser_video_generate")
class LeonardoBrowserVideoGenerateTool(BaseTool):
    """Generate a Kling start/end-frame clip via Leonardo's web app (subscription credits)."""

    tool_id = "leonardo_browser_video_generate"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="leonardo_browser_video_generate",
            description=(
                "Generate a start->end frame Kling 3.0 video clip by driving"
                " Leonardo's web app in a real browser, so the cost comes out"
                " of the subscription's bundled 'AI Creation' credits instead"
                " of the pay-as-you-go API balance. Requires Playwright and a"
                " one-time manual login into a dedicated browser profile (see"
                " scripts/leonardo_browser_login.py). Runs locally on the"
                " machine that has that profile -- not a network API call."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "start_image_path": {
                        "type": "string",
                        "description": "Local file path to the starting frame image.",
                    },
                    "end_image_path": {
                        "type": "string",
                        "description": "Local file path to the ending frame image.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Motion/continuity description for the clip.",
                    },
                    "duration": {
                        "type": "integer",
                        "description": "Clip length in seconds (Kling 3.0 UI default 6).",
                    },
                    "resolution": {
                        "type": "string",
                        "description": "'RESOLUTION_720' (HD) or 'RESOLUTION_1080' (Full HD). Default 720.",
                    },
                    "orientation": {
                        "type": "string",
                        "description": "'portrait' (9:16, default) or 'landscape' (16:9).",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Local file path to download the resulting video to.",
                    },
                    "headless": {
                        "type": "boolean",
                        "description": "Run the browser without a visible window. Default false (visible, easier to debug).",
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": "Max seconds to wait for rendering to finish. Default 480 (Kling can be slow-queued).",
                    },
                },
                "required": ["start_image_path", "end_image_path", "prompt", "output_path"],
            },
            category="media",
            required_capabilities=["filesystem:write"],
            timeout_seconds=600.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        start_image_path = params.get("start_image_path", "")
        end_image_path = params.get("end_image_path", "")
        prompt = params.get("prompt", "")
        output_path = params.get("output_path", "")
        if not start_image_path or not end_image_path or not prompt or not output_path:
            return ToolResult(
                tool_name="leonardo_browser_video_generate",
                content="start_image_path, end_image_path, prompt, and output_path are all required.",
                success=False,
            )
        for label, p in (("start_image_path", start_image_path), ("end_image_path", end_image_path)):
            if not Path(p).exists():
                return ToolResult(
                    tool_name="leonardo_browser_video_generate",
                    content=f"{label} does not exist: {p}",
                    success=False,
                )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return ToolResult(
                tool_name="leonardo_browser_video_generate",
                content=(
                    "playwright package not installed. Install with:"
                    " pip install playwright && playwright install chromium"
                ),
                success=False,
            )

        duration = int(params.get("duration", 6))
        orientation = str(params.get("orientation", "portrait")).strip().lower()
        aspect = _ASPECT_BY_ORIENTATION.get(orientation, "9:16")
        resolution = params.get("resolution", "RESOLUTION_720")
        if resolution not in _VALID_SIZES:
            resolution = "RESOLUTION_720"
        headless = bool(params.get("headless", False))
        timeout_seconds = float(params.get("timeout_seconds", 480))

        url = _GENERATE_URL.format(aspect=aspect, size=resolution, duration=duration)

        try:
            with sync_playwright() as pw:
                context = _launch_context(pw, headless=headless)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)

                if page.get_by_text(re.compile("log\\s*in|sign\\s*in", re.I)).count() > 0:
                    context.close()
                    return ToolResult(
                        tool_name="leonardo_browser_video_generate",
                        content=(
                            "Leonardo browser profile is not logged in. Run"
                            " scripts/leonardo_browser_login.py once to log in"
                            " manually, then retry."
                        ),
                        success=False,
                    )

                credits_before = _read_credit_balance(page)
                _ensure_full_hd(page)
                _ensure_audio_off(page)
                existing_video_sources = {
                    page.locator("video").nth(i).get_attribute("src") or ""
                    for i in range(page.locator("video").count())
                }

                _upload_frame(page, "start", start_image_path)
                page.wait_for_timeout(1500)
                _upload_frame(page, "end", end_image_path)
                page.wait_for_timeout(1500)

                prompt_box = page.locator("#prompt-textarea, textarea[name='prompt'], textarea[placeholder*='prompt' i]").first
                prompt_box.click()
                prompt_box.fill(prompt[:1500])

                generate_button = page.locator("button:has-text('Generate')").first
                generate_button.click()

                video_src = _wait_for_video(page, timeout_seconds, existing_video_sources)
                credits_after = _read_credit_balance(page)

                resp = context.request.get(video_src)
                if resp.status >= 400:
                    raise _BrowserAutomationError(
                        f"Downloading finished clip failed ({resp.status})."
                    )
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(resp.body())

                context.close()
        except _BrowserAutomationError as exc:
            return ToolResult(
                tool_name="leonardo_browser_video_generate",
                content=f"Browser automation error: {exc}",
                success=False,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_name="leonardo_browser_video_generate",
                content=f"Browser automation error: {exc}",
                success=False,
            )

        credits_used = (
            credits_before - credits_after
            if credits_before is not None and credits_after is not None
            else None
        )

        return ToolResult(
            tool_name="leonardo_browser_video_generate",
            content=output_path,
            success=True,
            metadata={
                "resolution": resolution,
                "orientation": orientation,
                "duration": duration,
                "credits_before": credits_before,
                "credits_after": credits_after,
                "credits_used": credits_used,
                "backend": "browser-subscription-credits",
            },
        )


__all__ = ["LeonardoBrowserVideoGenerateTool"]
