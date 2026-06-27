"""Lip-sync talking-head video tool -- VEED Fabric 1.0 via fal.ai.

Turns a single reference image (e.g. a JE/politician standing at a
restoration site) plus a separately-generated voice-over audio file into a
talking video with lip movement synced to the audio. Same FAL_KEY
credential as video_tool.py/image_tool.py -- no new API key needed.

Picked VEED Fabric 1.0 over Kling AI Avatar v2 Pro as the default for this
first cut of the storytelling-intro feature: materially cheaper per second
of output, and good enough to validate whether the dialogue-generation +
TTS + lip-sync pipeline reads as believable before spending more per run on
the pricier gesture-realism upgrade.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_MODEL_ID = "fal-ai/veed/fabric-1.0"


@ToolRegistry.register("lipsync_video_generate")
class LipsyncVideoGenerateTool(BaseTool):
    """Generate a lip-synced talking video from one image + one audio file."""

    tool_id = "lipsync_video_generate"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="lipsync_video_generate",
            description=(
                "Generate a talking-head video from a single reference image"
                " and a voice-over audio file, with lip movement synced to"
                " the audio (VEED Fabric 1.0 via fal.ai). Returns the local"
                " output video path."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "Local file path to the reference image (the speaking character).",
                    },
                    "audio_path": {
                        "type": "string",
                        "description": "Local file path to the voice-over audio to lip-sync to.",
                    },
                    "resolution": {
                        "type": "string",
                        "description": "Output resolution, e.g. '480p' or '720p'. Default '720p'.",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional local file path to download the resulting video to.",
                    },
                    "provider": {
                        "type": "string",
                        "description": "Lip-sync provider. Default 'fal'.",
                    },
                },
                "required": ["image_path", "audio_path"],
            },
            category="media",
            required_capabilities=["network:fetch"],
            # Same reasoning as video_tool.py's VideoGenerateTool: fal's
            # subscribe() call (queue + generate + poll) for a video model
            # routinely outruns the executor's 30s default timeout, and a
            # firing timeout doesn't even stop the background work -- it
            # just stops us from seeing the result. Use the same generous
            # budget so a slow-but-successful generation isn't reported as
            # a failure.
            timeout_seconds=1800.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        image_path = params.get("image_path", "")
        audio_path = params.get("audio_path", "")
        if not image_path or not audio_path:
            return ToolResult(
                tool_name="lipsync_video_generate",
                content="Both image_path and audio_path are required.",
                success=False,
            )

        if not Path(image_path).exists():
            return ToolResult(
                tool_name="lipsync_video_generate",
                content=f"image_path does not exist: {image_path}",
                success=False,
            )
        if not Path(audio_path).exists():
            return ToolResult(
                tool_name="lipsync_video_generate",
                content=f"audio_path does not exist: {audio_path}",
                success=False,
            )

        resolution = params.get("resolution", "720p")
        provider = params.get("provider", "fal")
        output_path = params.get("output_path")

        if provider != "fal":
            return ToolResult(
                tool_name="lipsync_video_generate",
                content=f"Unsupported provider '{provider}'. Only 'fal' is supported.",
                success=False,
            )

        try:
            import fal_client
        except ImportError:
            return ToolResult(
                tool_name="lipsync_video_generate",
                content=(
                    "fal_client package not installed. Install with: pip install fal-client"
                ),
                success=False,
            )

        api_key = os.environ.get("FAL_KEY")
        if not api_key:
            return ToolResult(
                tool_name="lipsync_video_generate",
                content="No API key configured. Set FAL_KEY.",
                success=False,
            )

        try:
            image_url = fal_client.upload_file(image_path)
            audio_url = fal_client.upload_file(audio_path)
            result = fal_client.subscribe(
                _MODEL_ID,
                arguments={
                    "image_url": image_url,
                    "audio_url": audio_url,
                    "resolution": resolution,
                },
            )
            video_url = result["video"]["url"]
        except Exception as exc:
            return ToolResult(
                tool_name="lipsync_video_generate",
                content=f"Lip-sync video generation error: {exc}",
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
                    tool_name="lipsync_video_generate",
                    content=(
                        f"Video generated but failed to save: {exc}. URL: {video_url}"
                    ),
                    success=False,
                    metadata={"url": video_url, "resolution": resolution, "provider": provider},
                )

        return ToolResult(
            tool_name="lipsync_video_generate",
            content=output_path or video_url,
            success=True,
            metadata={"url": video_url, "resolution": resolution, "provider": provider},
        )


__all__ = ["LipsyncVideoGenerateTool"]
