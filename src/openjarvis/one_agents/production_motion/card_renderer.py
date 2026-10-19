"""Frame-exact rendering of cards.html (GSAP) through headless Chrome.

One long-lived browser serves every card of a video, so the fonts load once. A card is driven by time, not
by a clock: build(spec) lays it out, seek(t) puts the timeline at t, and Chrome screenshots exactly that
moment. The result is repeatable, and a slow machine only makes it slower, never different.

Opaque cards go to ffmpeg as JPEG frames; overlays (spec["overlay"] is true) go as PNG frames with alpha.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterator

HERE = Path(__file__).resolve().parent
FPS = 30
FFMPEG = "ffmpeg"
PROOF_RECT = (96, 250, 1728, 690)  # keep in step with PROOF in cards.html


def launch_chromium(pw):
    """Playwright's own Chromium, else the installed Google Chrome, else Edge.

    Each Playwright release wants its own browser build. ONE runs these tools under Playwright 1.58, whose
    headless shell (build 1208) was never installed here, so every motion_v2 render from the agent failed and
    the cut fell back to Remotion (2026-10-06). The installed Chrome renders the same cards."""
    errors = []
    for options in ({}, {"channel": "chrome"}, {"channel": "msedge"}):
        try:
            return pw.chromium.launch(**options)
        except Exception as exc:  # noqa: BLE001 - try the next browser, report all if none starts
            errors.append(f"{options or 'bundled'}: {str(exc).splitlines()[0]}")
    raise RuntimeError("No Chromium-based browser could start for motion_v2: " + " | ".join(errors))


class CardRenderer:
    def _launch(self) -> None:
        self._browser = launch_chromium(self._pw)
        self.page = self._browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        self.page.on("pageerror", lambda e: print("PAGE ERROR:", e, file=sys.stderr))
        self.page.goto((HERE / "cards.html").as_uri())
        self.page.wait_for_function("window.fontsReady === true")

    def __enter__(self) -> "CardRenderer":
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._launch()
        return self

    def __exit__(self, *exc) -> None:
        try:
            self._browser.close()
        finally:
            self._pw.stop()

    def _restart(self) -> None:
        """A page that stops answering (it has happened once in a 200-beat render) is replaced, not waited on."""
        try:
            self._browser.close()
        except Exception:  # noqa: BLE001 - it is already unresponsive
            pass
        self._launch()

    def _frame(self, spec: dict, t: float, overlay: bool) -> bytes:
        for attempt in (1, 2, 3):
            try:
                self.page.evaluate("(t) => window.seek(t)", t)
                if overlay:
                    return self.page.screenshot(type="png", omit_background=True, timeout=60000)
                return self.page.screenshot(type="jpeg", quality=96, timeout=60000)
            except Exception as exc:  # noqa: BLE001 - playwright TimeoutError / closed target
                if attempt == 3:
                    raise
                print(f"frame at {t:.2f}s failed ({type(exc).__name__}); restarting the browser", file=sys.stderr, flush=True)
                self._restart()
                self._build(spec)
        raise AssertionError("unreachable")

    def _build(self, spec: dict) -> float:
        duration = self.page.evaluate("(s) => window.build(s)", spec)
        self.page.evaluate("document.fonts.ready")
        return float(duration)

    def still(self, spec: dict, at: float, path: Path) -> None:
        self._build(spec)
        self.page.evaluate("(t) => window.seek(t)", at)
        self.page.screenshot(path=str(path), type="png")

    def frames(self, spec: dict) -> Iterator[bytes]:
        """Yield encoded frames for the whole card: PNG with alpha for overlays, JPEG otherwise."""
        duration = self._build(spec)
        overlay = bool(spec.get("overlay"))
        for n in range(max(1, round(duration * FPS))):
            yield self._frame(spec, n / FPS, overlay)

    def render_clip(self, spec: dict, target: Path) -> None:
        """An opaque card -> h264 clip of exactly spec["duration"] seconds."""
        target.parent.mkdir(parents=True, exist_ok=True)
        ff = subprocess.Popen(
            [FFMPEG, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
             # MJPEG decodes to full-range yuvj420p. Left as is, card beats and footage beats (TV range) alternate
             # pixel formats inside one scene file; ffmpeg rebuilds its filter graph at every switch, and the
             # assembly's trim stopped each scene after its first beat (Vietnam master: 3.8 of 12.6 min).
             "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
             "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-r", str(FPS), str(target)],
            stdin=subprocess.PIPE)
        for frame in self.frames(spec):
            ff.stdin.write(frame)
        ff.stdin.close()
        if ff.wait() != 0:
            raise RuntimeError(f"ffmpeg failed rendering {target.name}")

    def render_over(self, spec: dict, base_filter: str, media: list[str], target: Path,
                    video_at: tuple[int, int] | None = None) -> None:
        """Composite a card with footage prepared by `base_filter`.

        `media` is the ffmpeg input argument list for the footage (-ss/-t/-i ...). `base_filter` turns input 0
        into the labelled stream [base]; the card frames arrive as input 1. By default the card is laid over the
        footage at 0,0 (a lower-third). With `video_at` the footage goes on top of the card at that position
        instead (a proof frame whose window the footage fills).
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        overlay = bool(spec.get("overlay"))
        codec = "png" if overlay else "mjpeg"
        join = (f"[1:v]scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[card];[card][base]overlay={video_at[0]}:{video_at[1]},"
                "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[out]"
                if video_at else "[base][1:v]overlay=0:0:format=auto,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[out]")
        ff = subprocess.Popen(
            [FFMPEG, "-y", "-loglevel", "error", *media, "-f", "image2pipe", "-framerate", str(FPS), "-c:v", codec, "-i", "-",
             "-filter_complex", f"{base_filter};{join}",
             "-map", "[out]", "-an", "-t", f"{float(spec['duration']):.3f}", "-r", str(FPS),
             "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-c:v", "libx264", "-preset", "medium", "-crf", "16", str(target)],
            stdin=subprocess.PIPE)
        for frame in self.frames(spec):
            ff.stdin.write(frame)
        ff.stdin.close()
        if ff.wait() != 0:
            raise RuntimeError(f"ffmpeg failed compositing {target.name}")
