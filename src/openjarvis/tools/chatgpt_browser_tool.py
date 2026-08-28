"""Text-prompt tool -- drives chatgpt.com via a real, persistently-logged-in browser.

Why this exists: PEITHO's reel-hook scripts were first written by calling
Claude directly (`_claude_research`), then by calling OpenAI's paid API
(`_openai_research`). Both work, but the Chairman's own side-by-side
comparison (2026-08-28, driving an actual chatgpt.com session by hand) found
ChatGPT-the-product's output for this specific job -- punchy short-form
video copy -- consistently better than either API call, and asked
specifically for the ChatGPT *product* to be used, not a metered API call
riding on the same underlying model.

This tool does not call any OpenAI endpoint and does not store or transmit
a password. It drives a real Chrome window against a *dedicated, persistent*
browser profile the user logs into once by hand (see
``scripts/chatgpt_browser_login.py``) -- identical pattern to
``leonardo_browser_video_tool.py``. After that one-time manual login, this
profile's cookies persist across runs, so every subsequent call here acts
as that already-authenticated user, using their existing ChatGPT
subscription instead of pay-per-call billing.

Flow per call:
  1. Launch (or reuse) a persistent Chromium context bound to the profile
     dir in CHATGPT_CHROME_PROFILE_DIR.
  2. Navigate to a fresh chatgpt.com/ chat (no conversation id) so each
     call starts with a clean context -- mirrors why PEITHO already makes
     one independent call per angle rather than one combined call.
  3. Fill the prompt into the composer via Playwright's `fill()` (sets the
     value directly, no simulated keystrokes) -- deliberately NOT using
     character-by-character typing, which is what caused ChatGPT's composer
     to submit early on embedded newlines during manual testing earlier
     this session (Enter-without-Shift = send).
  4. Submit, then poll for a new assistant response element beyond the
     pre-submit count, and wait for generation to finish (Stop-generating
     control disappears).
  5. Reject a response that's just an echo of the submitted prompt (same
     failure mode LAO's own `_ask_chatgpt` guards against) and return the
     extracted text.

Requires: ``playwright`` installed (``uv sync --extra browser``) and Google
Chrome present on this machine (uses ``channel="chrome"``, not the bundled
Chromium, so it can share the real Chrome cookie store this profile builds).
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_COMPOSER_SELECTORS = ["#prompt-textarea", "[contenteditable='true']", "textarea"]
_SEND_BUTTON_SELECTORS = ["[data-testid='send-button']", "button[aria-label*='Send' i]"]
_ASSISTANT_SELECTOR = "[data-message-author-role='assistant']"
_STOP_BUTTON_SELECTORS = ["[data-testid='stop-button']", "button[aria-label*='Stop' i]"]


class _BrowserAutomationError(RuntimeError):
    """Raised internally to short-circuit to a ToolResult failure."""


def _profile_dir() -> Path:
    configured = os.environ.get("CHATGPT_CHROME_PROFILE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".openjarvis" / "chatgpt_browser_profile"


def _launch_context(playwright: Any, headless: bool):
    profile = _profile_dir()
    if not profile.exists():
        raise _BrowserAutomationError(
            "No ChatGPT browser profile found at"
            f" {profile}. Run"
            " `python -m openjarvis.scripts.chatgpt_browser_login` once to"
            " log in manually -- after that this tool reuses the saved"
            " session automatically."
        )
    return playwright.chromium.launch_persistent_context(
        str(profile),
        headless=headless,
        channel="chrome",
        viewport={"width": 1480, "height": 900},
    )


def _find_composer(page: Any):
    for selector in _COMPOSER_SELECTORS:
        loc = page.locator(selector).first
        try:
            if loc.count() > 0:
                return loc
        except Exception:
            continue
    return None


def _click_first(page: Any, selectors: list[str], timeout_ms: int = 5000) -> bool:
    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False


def _is_own_prompt_echo(prompt: str, candidate: str) -> bool:
    """Guards against the composer's own submitted text being picked up as
    if it were the assistant's reply -- a real bug hit driving this UI by
    hand earlier this session, not a hypothetical."""
    p = re.sub(r"\s+", " ", prompt).strip().lower()
    c = re.sub(r"\s+", " ", candidate).strip().lower()
    if not c:
        return True
    if c == p:
        return True
    # A long verbatim prefix match is the same failure mode even if the
    # trailing text differs (e.g. UI shows the prompt still mid-render).
    prefix_len = min(120, len(p))
    return prefix_len > 40 and c[:prefix_len] == p[:prefix_len]


def _wait_for_reply(page: Any, prompt: str, before_count: int, timeout_seconds: float) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        nodes = page.locator(_ASSISTANT_SELECTOR)
        n = nodes.count()
        if n > before_count:
            # Still generating? Wait for the stop-generating control to clear.
            still_generating = any(
                page.locator(sel).count() > 0 for sel in _STOP_BUTTON_SELECTORS
            )
            if not still_generating:
                try:
                    text = nodes.nth(n - 1).inner_text(timeout=2000).strip()
                except Exception:
                    text = ""
                if text and not _is_own_prompt_echo(prompt, text):
                    return text
        page.wait_for_timeout(1500)
    raise _BrowserAutomationError(
        f"Timed out after {timeout_seconds:.0f}s waiting for ChatGPT's reply."
    )


@ToolRegistry.register("chatgpt_browser_ask")
class ChatGptBrowserAskTool(BaseTool):
    """Submit a text prompt to chatgpt.com (real product, not the API) and return the reply."""

    tool_id = "chatgpt_browser_ask"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="chatgpt_browser_ask",
            description=(
                "Submit a text prompt to an already-logged-in chatgpt.com"
                " session in a real browser and return the assistant's"
                " reply text. Requires a one-time manual login into a"
                " dedicated browser profile (see"
                " scripts/chatgpt_browser_login.py). Uses the existing"
                " ChatGPT subscription, not a metered API call."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The prompt to submit.",
                    },
                    "headless": {
                        "type": "boolean",
                        "description": "Run without a visible window. Default true.",
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": "Max seconds to wait for the reply. Default 120.",
                    },
                },
                "required": ["prompt"],
            },
            category="research",
            required_capabilities=[],
            timeout_seconds=180.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        prompt = str(params.get("prompt") or "")
        if not prompt.strip():
            return ToolResult(tool_name="chatgpt_browser_ask", content="prompt is required.", success=False)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return ToolResult(
                tool_name="chatgpt_browser_ask",
                content="playwright package not installed. Run: uv sync --extra browser",
                success=False,
            )

        headless = bool(params.get("headless", True))
        timeout_seconds = float(params.get("timeout_seconds", 120))

        try:
            with sync_playwright() as pw:
                context = _launch_context(pw, headless=headless)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)

                if page.get_by_text(re.compile(r"log\s*in|sign\s*in", re.I)).count() > 0 and _find_composer(page) is None:
                    context.close()
                    return ToolResult(
                        tool_name="chatgpt_browser_ask",
                        content=(
                            "ChatGPT browser profile is not logged in. Run"
                            " `python -m openjarvis.scripts.chatgpt_browser_login`"
                            " once to log in manually, then retry."
                        ),
                        success=False,
                    )

                composer = _find_composer(page)
                if composer is None:
                    raise _BrowserAutomationError("Could not find ChatGPT's prompt composer on the page.")

                before_count = page.locator(_ASSISTANT_SELECTOR).count()

                composer.click()
                composer.fill(prompt)
                if not _click_first(page, _SEND_BUTTON_SELECTORS, timeout_ms=5000):
                    composer.press("Enter")

                reply = _wait_for_reply(page, prompt, before_count, timeout_seconds)
                context.close()
        except _BrowserAutomationError as exc:
            return ToolResult(tool_name="chatgpt_browser_ask", content=f"Browser automation error: {exc}", success=False)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(tool_name="chatgpt_browser_ask", content=f"Browser automation error: {exc}", success=False)

        return ToolResult(tool_name="chatgpt_browser_ask", content=reply, success=True)


__all__ = ["ChatGptBrowserAskTool"]
