"""Video generation tool — image-to-video via fal.ai (Wan 2.5 / Wan FLF2V).

Two distinct modes, picked automatically based on whether ``end_image_path``
is supplied:

  * Single image + motion prompt -> ``fal-ai/wan-25-preview/image-to-video``.
    The model has no idea what should happen at the end of the clip; it just
    animates *around* the one frame per the text prompt. Fine for generic
    b-roll motion, but NOT a start/end keyframe interpolation -- confirmed
    live on 2026-06-23 that feeding it a single "before" frame with a
    transformation-style prompt produces an unrelated, mostly-static result.
  * Start image + end image + prompt -> ``fal-ai/wan-flf2v`` (Wan 2.1
    First-Last-Frame-to-Video), which actually bridges the two given frames
    with coherent motion -- this is the mode Punarnirman's continuity clips
    need (same shape as the Leonardo start/end-frame tools). Resolution is
    limited to 480p/720p for this model (no 1080p tier).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_VALID_DURATIONS = {"5", "10"}
_VALID_RESOLUTIONS = {"480p", "720p", "1080p"}
_VALID_FLF2V_RESOLUTIONS = {"480p", "720p"}
_MODEL_ID = "fal-ai/wan-25-preview/image-to-video"
_FLF2V_MODEL_ID = "fal-ai/wan-flf2v"


@ToolRegistry.register("video_generate")
class VideoGenerateTool(BaseTool):
    """Generate a short image-to-video clip from a starting frame via fal.ai."""

    tool_id = "video_generate"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="video_generate",
            description=(
                "Generate a short video clip from a starting image (optionally"
                " bridging to an end image) and a motion prompt. Returns the"
                " hosted video URL. If end_image_path is supplied, uses the"
                " Wan first-last-frame model so the clip actually morphs from"
                " the start frame to the end frame; otherwise it just animates"
                " around the single start frame per the prompt, with no"
                " guaranteed end state."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": (
                            "Local file path to the starting frame image. Will be"
                            " uploaded to the provider's CDN automatically."
                        ),
                    },
                    "end_image_path": {
                        "type": "string",
                        "description": (
                            "Optional local file path to the ending frame image."
                            " When supplied, switches to the first-last-frame"
                            " model so the clip bridges start -> end with"
                            " coherent motion (resolution capped at 720p for"
                            " this mode)."
                        ),
                    },
                    "prompt": {
                        "type": "string",
                        "description": (
                            "Text description of the motion/camera movement for"
                            " the clip (max 800 chars)."
                        ),
                    },
                    "duration": {
                        "type": "string",
                        "description": "Clip length in seconds: '5' or '10'. Default '5'.",
                    },
                    "resolution": {
                        "type": "string",
                        "description": (
                            "Output resolution: '480p', '720p', or '1080p'."
                            " Default '720p'."
                        ),
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional local file path to download the resulting video to.",
                    },
                    "provider": {
                        "type": "string",
                        "description": "Video generation provider. Default 'fal'.",
                    },
                },
                "required": ["image_path", "prompt"],
            },
            category="media",
            required_capabilities=["network:fetch"],
            # No timeout_seconds override here meant this silently fell back
            # to the executor's 30s default (see ToolSpec.timeout_seconds in
            # tools/_stubs.py) -- nowhere near enough for fal.ai's subscribe
            # (queue + generate + poll) plus the download. The executor's
            # future.result(timeout=...) firing early doesn't even stop the
            # underlying work -- the background thread keeps running and
            # writes the clip to disk anyway, which is why all 4 clips
            # existed on disk even though the run reported FAILED. Same
            # generous budget as image_generate so this can't happen again.
            timeout_seconds=1800.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        image_path = params.get("image_path", "")
        end_image_path = params.get("end_image_path", "")
        prompt = params.get("prompt", "")
        if not image_path or not prompt:
            return ToolResult(
                tool_name="video_generate",
                content="Both image_path and prompt are required.",
                success=False,
            )

        if not Path(image_path).exists():
            return ToolResult(
                tool_name="video_generate",
                content=f"image_path does not exist: {image_path}",
                success=False,
            )

        use_flf2v = bool(end_image_path)
        if use_flf2v and not Path(end_image_path).exists():
            return ToolResult(
                tool_name="video_generate",
                content=f"end_image_path does not exist: {end_image_path}",
                success=False,
            )

        duration = str(params.get("duration", "5"))
        if not use_flf2v and duration not in _VALID_DURATIONS:
            return ToolResult(
                tool_name="video_generate",
                content=(
                    f"Invalid duration '{duration}'."
                    f" Must be one of: {', '.join(sorted(_VALID_DURATIONS))}."
                ),
                success=False,
            )

        resolution = params.get("resolution", "720p")
        valid_resolutions = _VALID_FLF2V_RESOLUTIONS if use_flf2v else _VALID_RESOLUTIONS
        if resolution not in valid_resolutions:
            if use_flf2v and resolution == "1080p":
                resolution = "720p"  # flf2v has no 1080p tier; downgrade instead of failing
            else:
                return ToolResult(
                    tool_name="video_generate",
                    content=(
                        f"Invalid resolution '{resolution}'."
                        f" Must be one of: {', '.join(sorted(valid_resolutions))}."
                    ),
                    success=False,
                )

        provider = params.get("provider", "fal")
        output_path = params.get("output_path")

        if provider != "fal":
            return ToolResult(
                tool_name="video_generate",
                content=f"Unsupported provider '{provider}'. Only 'fal' is supported.",
                success=False,
            )

        try:
            import fal_client
        except ImportError:
            return ToolResult(
                tool_name="video_generate",
                content=(
                    "fal_client package not installed. Install with: pip install fal-client"
                ),
                success=False,
            )

        api_key = os.environ.get("FAL_KEY")
        if not api_key:
            return ToolResult(
                tool_name="video_generate",
                content="No API key configured. Set FAL_KEY.",
                success=False,
            )

        try:
            image_url = fal_client.upload_file(image_path)
            if use_flf2v:
                end_image_url = fal_client.upload_file(end_image_path)
                result = fal_client.subscribe(
                    _FLF2V_MODEL_ID,
                    arguments={
                        "prompt": prompt[:800],
                        "start_image_url": image_url,
                        "end_image_url": end_image_url,
                        "resolution": resolution,
                    },
                )
            else:
                result = fal_client.subscribe(
                    _MODEL_ID,
                    arguments={
                        "prompt": prompt[:800],
                        "image_url": image_url,
                        "duration": duration,
                        "resolution": resolution,
                    },
                )
            video_url = result["video"]["url"]
        except Exception as exc:
            return ToolResult(
                tool_name="video_generate",
                content=f"Video generation error: {exc}",
                success=False,
            )

        if output_path:
            try:
                import httpx

                resp = httpx.get(video_url, follow_redirects=True, timeout=120.0)
                resp.raise_for_status()
                Path(output_path).write_bytes(resp.content)
            except Exception as exc:
                return ToolResult(
                    tool_name="video_generate",
                    content=(
                        f"Video generated but failed to save: {exc}. URL: {video_url}"
                    ),
                    success=False,
                    metadata={
                        "url": video_url,
                        "duration": duration,
                        "resolution": resolution,
                        "provider": provider,
                    },
                )

        return ToolResult(
            tool_name="video_generate",
            content=output_path or video_url,
            success=True,
            metadata={
                "url": video_url,
                "duration": duration,
                "resolution": resolution,
                "provider": provider,
            },
        )


__all__ = ["VideoGenerateTool"]
