"""Video merge tool — ffmpeg concat + text-overlay hook for reel assembly.

Stitches an ordered list of local video clips into one file (re-encoding,
not stream-copy, so clips with slightly different codecs/resolutions from
different generation providers still concatenate cleanly) and optionally
burns in a hook/location text overlay for the first N seconds.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _resolve_fontfile() -> "str | None":
    """Find a real bold font file on this machine, formatted for ffmpeg's
    drawtext filter (forward slashes, drive-colon escaped with backslash).

    The previous version hardcoded a Linux path
    (/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf) and, when that
    didn't exist, fell back to omitting ``fontfile`` entirely so drawtext
    would resolve a default font via fontconfig. That fallback only works
    if fontconfig is actually configured -- on Windows ffmpeg builds it's
    compiled in but has no config file, so omitting fontfile fails with
    "Fontconfig error: Cannot load default config file: No such file:
    (null)" instead of silently using a built-in default. Always supplying
    a real, existing font path sidesteps fontconfig entirely on every OS.
    """
    system = platform.system()
    if system == "Windows":
        windir = os.environ.get("WINDIR", "C:\\Windows")
        candidates = [
            f"{windir}\\Fonts\\arialbd.ttf",
            f"{windir}\\Fonts\\segoeuib.ttf",
            f"{windir}\\Fonts\\calibrib.ttf",
            f"{windir}\\Fonts\\arial.ttf",
        ]
    elif system == "Darwin":
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]
    for candidate in candidates:
        if Path(candidate).exists():
            # ffmpeg filter option syntax uses ':' to separate key=value
            # pairs, so a Windows drive-letter colon must be escaped; forward
            # slashes work fine on every OS and avoid backslash-escaping.
            return candidate.replace("\\", "/").replace(":", "\\:")
    return None


def _escape_drawtext(text: str) -> str:
    """Escape text for ffmpeg's drawtext filter (colons, quotes, backslashes)."""
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "’")
        .replace("%", "\\%")
    )


def _probe_dimensions(path: Path) -> "tuple[int, int]":
    """Return (width, height) of *path*'s video stream via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    width_str, height_str = result.stdout.strip().split(",")[:2]
    return int(width_str), int(height_str)


def _probe_video_specs(path: Path) -> "tuple[int, int, str]":
    """Return (width, height, r_frame_rate) of *path*'s video stream."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    width_str, height_str, fps_str = result.stdout.strip().split(",")[:3]
    return int(width_str), int(height_str), fps_str


def _normalize_clip(src: Path, dst: Path, width: int, height: int, fps: str) -> "tuple[bool, str]":
    """Re-encode *src* to a canonical resolution/fps with audio stripped.

    Different generation backends/models (and even different fal.ai models
    within the same run -- e.g. wan-flf2v for clips A-D vs the single-image
    model for clip E) can return clips at different resolutions, frame
    rates, and with/without an audio track. Feeding mismatched clips
    straight into ffmpeg's concat demuxer doesn't error loudly -- it just
    silently breaks at the point the stream layout changes, which is why a
    clip can look "merged" in the command output but actually be missing
    from the final reel. Normalizing every clip to the first clip's
    resolution/fps and dropping all audio (these reels get music added
    separately, never voiceover) before concatenation avoids that entirely.
    """
    # Uses scale-to-cover + center-crop (NOT pad/letterbox). A clip whose
    # source aspect ratio differs from the canonical one (e.g. clip E's
    # 784x1176 vs clips A-D's 720x1280) would otherwise get black bars and
    # end up visibly smaller/"zoomed out" inside the frame -- same pixel
    # canvas size, but less of it filled with image, which looks like an
    # inconsistent zoom level when clips play back to back. Scaling up to
    # cover the full canonical frame and cropping the overflow keeps every
    # clip filling the frame edge-to-edge at a consistent apparent scale.
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps={fps}",
        "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.returncode == 0, result.stderr[-1500:]


def _generate_pin_icon(out_path: Path, size: int = 240) -> None:
    """Render a red map-pin (teardrop + white center hole) PNG with alpha,
    used as the location-hook icon burned into the opening of the reel.
    Drawn at high resolution and scaled down by ffmpeg so it stays crisp.
    """
    from PIL import Image, ImageDraw

    w = size
    head_d = w
    h = int(size * 1.3)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    red = (235, 47, 36, 255)
    cx = w // 2
    cy = head_d // 2

    # Teardrop pin: circular head + triangular tip pointing down.
    draw.ellipse([0, 0, w - 1, head_d - 1], fill=red)
    tip_half = int(w * 0.30)
    neck_y = int(head_d * 0.62)
    draw.polygon(
        [(cx - tip_half, neck_y), (cx + tip_half, neck_y), (cx, h - 1)],
        fill=red,
    )
    # White hole in the center of the head, like a classic map-pin glyph.
    hole_r = int(w * 0.20)
    draw.ellipse(
        [cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r],
        fill=(255, 255, 255, 255),
    )

    img.save(out_path)


@ToolRegistry.register("video_merge")
class VideoMergeTool(BaseTool):
    """Concatenate video clips and optionally burn in a text hook overlay."""

    tool_id = "video_merge"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="video_merge",
            description=(
                "Concatenate an ordered list of local video clips into one"
                " file via ffmpeg, with an optional burned-in text overlay"
                " (e.g. a location name / hook line) for the opening seconds."
                " Requires ffmpeg to be installed and on PATH."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "clip_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered local file paths of the clips to concatenate.",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Local file path to write the merged video to.",
                    },
                    "overlay_text": {
                        "type": "string",
                        "description": "Optional hook/location text to burn in over the opening seconds.",
                    },
                    "overlay_seconds": {
                        "type": "number",
                        "description": "How many seconds the location-pin overlay stays on screen. Default 3.",
                    },
                    "hook_text": {
                        "type": "string",
                        "description": (
                            "Optional 1-2 line attention hook shown for the opening"
                            " hook_seconds, joined with '||' if 2 lines (e.g."
                            " 'This ghat was drowning in trash.||Watch till the end.')."
                            " Shown above the location-pin badge, both kept inside"
                            " Instagram Reels' safe zone (clear of the top header,"
                            " the right-side engagement icons, and the bottom"
                            " caption/audio area)."
                        ),
                    },
                    "hook_seconds": {
                        "type": "number",
                        "description": "How many seconds the hook text stays on screen. Default 2.",
                    },
                },
                "required": ["clip_paths", "output_path"],
            },
            category="media",
            timeout_seconds=300.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        clip_paths = params.get("clip_paths") or []
        output_path = params.get("output_path", "")
        overlay_text = params.get("overlay_text", "")
        overlay_seconds = float(params.get("overlay_seconds", 3))
        hook_text = params.get("hook_text", "")
        hook_seconds = float(params.get("hook_seconds", 2))
        hook_lines = [ln for ln in hook_text.split("||") if ln.strip()][:2]

        if not clip_paths or not output_path:
            return ToolResult(
                tool_name="video_merge",
                content="clip_paths (non-empty) and output_path are required.",
                success=False,
            )

        missing = [p for p in clip_paths if not Path(p).exists()]
        if missing:
            return ToolResult(
                tool_name="video_merge",
                content=f"Clip(s) not found: {', '.join(missing)}",
                success=False,
            )

        if shutil.which("ffmpeg") is None:
            return ToolResult(
                tool_name="video_merge",
                content="ffmpeg not found on PATH. Install ffmpeg and ensure it's on PATH.",
                success=False,
            )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        try:
            with tempfile.TemporaryDirectory() as tmp_str:
                tmp = Path(tmp_str)

                # Normalize every clip to the first clip's resolution/fps
                # and strip audio before concatenation -- see _normalize_clip
                # for why: mismatched clips (different model/backend per
                # clip, e.g. clip E) otherwise silently fail to concatenate
                # past the point where the stream layout changes, instead
                # of erroring, which is what was causing the final reel to
                # come up short by exactly the last clip's duration.
                canon_w, canon_h, canon_fps = _probe_video_specs(Path(clip_paths[0]))
                normalized_paths = []
                for i, p in enumerate(clip_paths):
                    norm_path = tmp / f"norm_{i}.mp4"
                    ok, err = _normalize_clip(Path(p), norm_path, canon_w, canon_h, canon_fps)
                    if not ok:
                        return ToolResult(
                            tool_name="video_merge",
                            content=f"Normalizing clip {p} failed: {err}",
                            success=False,
                        )
                    normalized_paths.append(norm_path)

                concat_list = tmp / "concat.txt"
                concat_list.write_text(
                    "\n".join(f"file '{p.resolve().as_posix()}'" for p in normalized_paths),
                    encoding="utf-8",
                )

                concatenated = tmp / "concatenated.mp4"
                concat_cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(concat_list),
                    # fal.ai's wan-flf2v clips come out at a native 16fps,
                    # which reads as jerky/"rugged" motion in the final
                    # reel. minterpolate does real motion-compensated frame
                    # interpolation up to 30fps so the timelapse motion
                    # actually looks smooth and visible instead of choppy --
                    # this costs nothing extra (no re-generation), it's a
                    # one-time ffmpeg pass during merge.
                    "-vf", "minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:vsbmc=1",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    str(concatenated),
                ]
                result = subprocess.run(
                    concat_cmd, capture_output=True, text=True, timeout=240
                )
                if result.returncode != 0:
                    return ToolResult(
                        tool_name="video_merge",
                        content=f"ffmpeg concat failed: {result.stderr[-1500:]}",
                        success=False,
                    )

                final_src = concatenated
                if overlay_text or hook_lines:
                    width, height = _probe_dimensions(concatenated)

                    # Instagram Reels safe-zone margins (per Meta's published
                    # Reels template guidance): keep on-screen text out of the
                    # top header strip, the right-side engagement-icon column
                    # (like/comment/share/save), and the bottom caption/audio
                    # info band. Expressed as fractions of width/height so this
                    # holds regardless of the actual render resolution.
                    safe_top = int(height * 0.14)
                    safe_right = int(width * 0.88)
                    margin_left = int(width * 0.06)

                    # --- Pin icon sizing (scales with frame height) ---
                    icon_path = tmp / "pin_icon.png"
                    _generate_pin_icon(icon_path)
                    icon_h = max(40, int(height * 0.045))

                    # --- Hook block (0 - hook_seconds): the only thing doing
                    # the "stop scrolling" job since these reels have no
                    # voiceover/dialogue, just music. Sized down automatically
                    # if a line would run into the right-side safe boundary. ---
                    hook_fontsize = max(22, int(height * 0.034))
                    safe_width_px = safe_right - margin_left
                    if hook_lines:
                        longest = max(len(ln) for ln in hook_lines)
                        max_fit = int(safe_width_px / (longest * 0.56)) if longest else hook_fontsize
                        hook_fontsize = max(20, min(hook_fontsize, max_fit))
                    hook_line_height = int(hook_fontsize * 1.35)

                    hook_y_start = safe_top
                    label_row_y = hook_y_start + len(hook_lines) * hook_line_height + int(height * 0.015)

                    # --- Location-pin label (0 - overlay_seconds), font size
                    # auto-shrunk to fit whatever the location name's length
                    # is within the remaining safe width next to the icon. ---
                    label_fontsize = max(18, int(height * 0.028))
                    escaped = _escape_drawtext(overlay_text) if overlay_text else ""
                    text_x = margin_left + icon_h + int(width * 0.025)
                    if overlay_text:
                        label_safe_width = max(1, safe_right - text_x)
                        max_fit_label = int(label_safe_width / (len(overlay_text) * 0.56))
                        label_fontsize = max(16, min(label_fontsize, max_fit_label))
                    text_y = f"{label_row_y}+({icon_h}-text_h)/2"

                    def _hook_filters(font_clause: str) -> "list[str]":
                        parts = []
                        for i, line in enumerate(hook_lines):
                            y = hook_y_start + i * hook_line_height
                            parts.append(
                                "drawtext="
                                f"text='{_escape_drawtext(line)}':fontcolor=white:"
                                f"fontsize={hook_fontsize}{font_clause}:"
                                "box=1:boxcolor=black@0.6:boxborderw=14:"
                                f"x={margin_left}:y={y}:enable='lt(t,{hook_seconds})'"
                            )
                        return parts

                    def _build_filter(font_clause: str) -> str:
                        stages = []
                        if overlay_text:
                            stages.append(f"[1:v]scale=-1:{icon_h}[pin]")
                            stages.append(
                                f"[0:v][pin]overlay=x={margin_left}:y={label_row_y}:"
                                f"enable='lt(t,{overlay_seconds})'[base]"
                            )
                            prev = "base"
                        else:
                            prev = "0:v"
                        hook_filters = _hook_filters(font_clause)
                        last_idx = len(hook_filters) - 1
                        for i, hook_filter in enumerate(hook_filters):
                            is_last_stage = (i == last_idx) and not overlay_text
                            if is_last_stage:
                                stages.append(f"[{prev}]{hook_filter}")
                            else:
                                nxt = f"h{i}"
                                stages.append(f"[{prev}]{hook_filter}[{nxt}]")
                                prev = nxt
                        if overlay_text:
                            stages.append(
                                f"[{prev}]drawtext=text='{escaped}':fontcolor=white:"
                                f"fontsize={label_fontsize}{font_clause}:"
                                "box=1:boxcolor=black@0.6:boxborderw=16:"
                                f"x={text_x}:y={text_y}:enable='lt(t,{overlay_seconds})'"
                            )
                        elif not hook_filters:
                            # Neither hook nor label -- shouldn't reach here
                            # since the outer guard requires at least one,
                            # but stay defensive: pass video through as-is.
                            stages.append(f"[{prev}]null")
                        return ";".join(stages)

                    resolved_font = _resolve_fontfile()
                    font_attempts = [
                        f":fontfile={resolved_font}" if resolved_font else ""
                    ]
                    # Only add the no-fontfile fallback (relies on fontconfig
                    # resolving a default) when we couldn't find a real font
                    # file ourselves -- on a box with no fontconfig.conf
                    # (common on Windows ffmpeg builds) that fallback fails
                    # outright, so don't waste a second ffmpeg pass on it
                    # when we already have a concrete, existing font path.
                    if not resolved_font:
                        font_attempts.append("")

                    result = None
                    for font_clause in font_attempts:
                        overlay_cmd = [
                            "ffmpeg", "-y",
                            "-i", str(concatenated),
                            "-i", str(icon_path),
                            "-filter_complex", _build_filter(font_clause),
                            str(output_path),
                        ]
                        result = subprocess.run(
                            overlay_cmd, capture_output=True, text=True, timeout=240
                        )
                        if result.returncode == 0:
                            break
                    if result is None or result.returncode != 0:
                        stderr = result.stderr[-1500:] if result else "no ffmpeg attempt ran"
                        return ToolResult(
                            tool_name="video_merge",
                            content=f"ffmpeg overlay failed: {stderr}",
                            success=False,
                        )
                else:
                    shutil.copyfile(final_src, output_path)
        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name="video_merge",
                content="ffmpeg timed out.",
                success=False,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_name="video_merge",
                content=f"Video merge error: {exc}",
                success=False,
            )

        return ToolResult(
            tool_name="video_merge",
            content=output_path,
            success=True,
            metadata={"clip_count": len(clip_paths), "overlay_text": overlay_text},
        )


__all__ = ["VideoMergeTool"]
