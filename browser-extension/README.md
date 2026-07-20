# ONE Ghost Agent -- Chrome extension

Lets the Ghost Agent open and manage videos in your *real* Chrome session
instead of a separate, unauthenticated automation browser window. Same idea
as Anthropic's own "Claude in Chrome" -- it talks only to your local ONE
server at `127.0.0.1:8000`, never to anything remote.

## One-time setup

1. Open `chrome://extensions` in your regular Chrome.
2. Turn on **Developer mode** (top-right toggle).
3. Click **Load unpacked** and select this folder
   (`src/browser-extension`).
4. That's it -- as long as ONE's server is running, the extension is live.
   `play_video` will now open videos as a normal tab in this browser and
   auto-skip ads there; if the extension isn't loaded or the server isn't
   running, it falls back to the old separate-Chrome-window behavior
   automatically.

## Why this exists

The old approach launched a separate, cookie-less, unauthenticated
Playwright-controlled Chrome profile. YouTube/Google treat that very
differently from a real logged-in browser -- it's what caused most of the
CAPTCHA and "Something went wrong" crashes. This extension runs inside your
actual browser, so it inherits your real session and never looks like a bot
in the first place.
