"""Automatic quality check for a rendered reel: catches flicker before publish.

Flicker = pixels that jump for one frame and come straight back (a sparkle on a
glossy facet, a one-frame flash of another camera angle). Smooth camera moves,
cuts, blinks and lip sync change pixels in one direction or over several
frames, so they do not count.

  python3 qc.py out/ep01/reel.mp4            # prints a report, exit 1 on failure
"""

from __future__ import annotations

import json
import subprocess
import sys

import numpy as np

SW, SH = 180, 320          # analysed at quarter size: fast, still sees 4x4 px sparkles
JUMP = 40                  # grey-level jump that counts as a spike
FLASH_FRAC = 0.06          # >6% of the frame spiking = one-frame flash of another shot
SPARKLE_PX = 120           # a cluster of spike pixels this big = visible sparkle
MAX_BAD_FRAMES = 0


def frames(path: str) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={SW}:{SH},format=gray",
                          "-f", "rawvideo", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, SH, SW).astype(np.int16)


def check(path: str, fps: int = 30) -> dict:
    fr = frames(path)
    a, b, c = fr[:-2], fr[1:-1], fr[2:]
    up, down = b - a, b - c
    # a true flicker returns to where it was: frame before ~= frame after at that
    # pixel. Edges sliding past during a pan fail this test, so pans don't count.
    spike = ((np.sign(up) == np.sign(down)) & (np.minimum(np.abs(up), np.abs(down)) > JUMP)
             & (np.abs(a - c) < 12))
    # ignore the caption band and the CTA card area: text pops in on purpose
    spike[:, int(SH * 0.10):int(SH * 0.25), :] = False
    spike[:, int(SH * 0.70):, :] = False
    counts = spike.sum(axis=(1, 2))
    # During a fast camera move many pixels legitimately change; a one-frame
    # pop is only visible against a mostly still picture, so the allowance
    # grows with how much of the frame is moving (frame before vs after).
    moving = (np.abs(a - c) > 20).sum(axis=(1, 2))
    bad = []
    for i, n in enumerate(counts):
        allow = SPARKLE_PX + 0.3 * moving[i]
        kind = "flash" if n > FLASH_FRAC * SW * SH + 0.3 * moving[i] else "sparkle" if n > allow else None
        if kind:
            bad.append({"frame": i + 1, "time": round((i + 1) / fps, 2), "kind": kind, "pixels": int(n)})
    return {"video": path, "frames": int(len(fr)), "bad_frames": bad, "ok": len(bad) <= MAX_BAD_FRAMES,
            "median_spike_px": float(np.median(counts))}


if __name__ == "__main__":
    rep = check(sys.argv[1])
    print(json.dumps(rep, indent=1)[:3000])
    sys.exit(0 if rep["ok"] else 1)
