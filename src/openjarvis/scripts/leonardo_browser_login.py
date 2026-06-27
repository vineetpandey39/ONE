"""One-time manual login for the Leonardo browser-automation profile.

Run this once on the machine that will run the restoration-reel pipeline:

    python -m openjarvis.scripts.leonardo_browser_login

It opens a real, visible Chrome window pointed at a dedicated profile
directory (LEONARDO_CHROME_PROFILE_DIR, default
``~/.openjarvis/leonardo_browser_profile``) and waits while *you* log into
Leonardo by hand -- email/password or Google sign-in, whatever you normally
use. Nothing you type is read, stored, or transmitted by this script; it
only waits for the page to reach a logged-in state, then closes. Playwright
saves the resulting session cookies into that profile directory, and every
later run of ``leonardo_browser_video_generate`` reuses them automatically.

Re-run this any time the session expires (Leonardo logs you out, or you
revoke the session).
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path


def _profile_dir() -> Path:
    configured = os.environ.get("LEONARDO_CHROME_PROFILE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".openjarvis" / "leonardo_browser_profile"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "playwright not installed. Run:"
            " pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        return 1

    profile = _profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    print(f"Using browser profile: {profile}")
    print("A Chrome window will open. Log into Leonardo, then come back here.")

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(profile),
            headless=False,
            channel="chrome",
            viewport={"width": 1480, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://app.leonardo.ai/generate?model=kling-3.0", wait_until="domcontentloaded")

        print(
            "Take your time -- log in with email/password, Google, whatever you"
            " normally use. This window will NOT auto-close and there is no"
            " timeout. Google's sign-in flow can bounce through several pages"
            " (email -> password -> 2FA); that's expected, just keep going."
        )
        print()
        input(
            "Once you're fully logged in and back on the Leonardo generate page,"
            " come back to this terminal and press Enter to save the session..."
        )

        # Give the page a moment to settle, then sanity-check before saving.
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
