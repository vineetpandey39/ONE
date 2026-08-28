"""One-time manual login for the ChatGPT browser-automation profile.

Run this once on the machine that will run PEITHO's reel-hook pipeline:

    python -m openjarvis.scripts.chatgpt_browser_login

It opens a real, visible Chrome window pointed at a dedicated profile
directory (CHATGPT_CHROME_PROFILE_DIR, default
``~/.openjarvis/chatgpt_browser_profile``) and waits while *you* log into
ChatGPT by hand -- email/password, Google sign-in, whatever you normally
use. Nothing you type is read, stored, or transmitted by this script; it
only waits for you to confirm you're logged in, then saves the session.
Playwright saves the resulting cookies into that profile directory, and
every later run of ``chatgpt_browser_ask`` reuses them automatically --
no username/password ever passes through our code (same pattern as
``leonardo_browser_login.py``).

Re-run this any time the session expires (ChatGPT logs you out, or you
revoke the session from another device).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def _profile_dir() -> Path:
    configured = os.environ.get("CHATGPT_CHROME_PROFILE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".openjarvis" / "chatgpt_browser_profile"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "playwright not installed. Run:"
            " uv sync --extra browser (or pip install playwright)",
            file=sys.stderr,
        )
        return 1

    profile = _profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    print(f"Using browser profile: {profile}")
    print("A Chrome window will open. Log into ChatGPT, then come back here.")

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(profile),
            headless=False,
            channel="chrome",
            viewport={"width": 1480, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://chatgpt.com/", wait_until="domcontentloaded")

        print(
            "Take your time -- log in with email/password, Google, whatever you"
            " normally use. This window will NOT auto-close and there is no"
            " timeout. Multi-step sign-in flows are expected, just keep going."
        )
        print()
        input(
            "Once you're fully logged in and can see the ChatGPT chat screen,"
            " come back to this terminal and press Enter to save the session..."
        )

        try:
            page.wait_for_timeout(1000)
            still_login = page.get_by_text(re.compile("log\\s*in|sign\\s*in", re.I)).count() > 0
        except Exception:
            still_login = False

        if still_login:
            print(
                "Heads up: this page still shows login/sign-in text, which might"
                " mean you're not fully logged in yet. If you ARE logged in and"
                " this is just stray text on the page, ignore this warning --"
                " the session will be saved either way."
            )

        print("Saving session to the browser profile...")
        context.close()
        print("Done. Session saved to:", profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
