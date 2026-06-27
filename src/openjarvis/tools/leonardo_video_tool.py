"""Image-to-video tool — start/end-frame motion via Leonardo.ai.

Leonardo's image-to-video endpoint takes a *start* image (``imageId``) and,
for true start->end frame interpolation (what the restoration-reel pipeline
needs so labor/machinery looks continuous rather than "teleporting"), an
``endFrameImage`` reference. Both images must first be uploaded through
Leonardo's presigned-URL init-image flow before they have an ``imageId``.

API reference (per Leonardo's docs, June 2026):
  POST /init-image                      -> presigned upload URL + imageId
  PUT  <presigned url>                  -> upload raw image bytes
  POST /generations-image-to-video      -> kick off generation, returns generationId
  GET  /generations/{id}                -> poll until status == COMPLETE
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_BASE_URL = "https://cloud.leonardo.ai/api/rest/v1"
_V2_BASE_URL = "https://cloud.leonardo.ai/api/rest/v2"
_VALID_RESOLUTIONS = {"480p", "RESOLUTION_480", "720p", "RESOLUTION_720", "1080p", "RESOLUTION_1080"}

# Cost comparison gathered from Leonardo's live Pricing Calculator + published
# Veo3.1 credit table (June 2026), for ONE clip with true start/end-frame
# interpolation:
#   VEO3_1       8s (forced when endFrameImage is set) -> 2140 credits, ~$4.78
#   VEO3_1FAST   8s (forced when endFrameImage is set) -> 1092 credits, ~$2.44
#   kling-3.0    5s (duration is NOT forced w/ start+end frame) -> ~$1.26
#   kling-3.0    8s                                    -> ~$2.01
# Across a 4-clip reel that's ~$19.12 (Veo full) / ~$9.76 (Veo Fast) / ~$5.04
# (Kling @5s) -- Kling is what blew through the user's manual UI test for
# only "504 coins" on one 6s clip, and is the cheapest model that still does
# real start->end interpolation, so it's the default. Veo3.1 family is kept
# as an opt-in via the `model` param for whoever wants its sharper motion at
# a known higher cost.
_DEFAULT_MODEL = "kling-3.0"
_KLING_MODELS = {"kling-3.0", "kling-3.0-turbo"}

# Leonardo's GraphQL schema wants the *enum token* for resolution (e.g.
# "RESOLUTION_720"), not a plain string like "720p" -- sending "720p"
# produces "expected an enum value for type 'VideoGenerationResolution',
# but found a string". Accept the friendly forms callers/prompts use and
# remap to the enum token the API actually requires.
_RESOLUTION_REMAP = {
    "480p": "RESOLUTION_480",
    "720p": "RESOLUTION_720",
    "1080p": "RESOLUTION_1080",
}

# Leonardo's Veo3.1 docs are explicit: "Dimensions will default to 16:9,
# height and width are not required." Without an explicit width/height pair
# the API silently renders landscape (e.g. 1280x720) even though the source
# keyframes are portrait 9:16 -- this (not a start/end-frame fallback) is why
# prior runs came back as 1280x720 instead of vertical-reel 720x1280. Kling
# 3.0 auto-detects orientation from the start frame image if width/height are
# omitted, but we send them explicitly for both families so behavior never
# depends on an undocumented default.
_PORTRAIT_DIMENSIONS = {
    "RESOLUTION_720": (720, 1280),
    "RESOLUTION_1080": (1080, 1920),
}
_LANDSCAPE_DIMENSIONS = {
    "RESOLUTION_720": (1280, 720),
    "RESOLUTION_1080": (1920, 1080),
}


class _LeonardoError(RuntimeError):
    """Raised internally to short-circuit to a ToolResult failure."""


def _upload_image(client: "Any", image_path: str, headers: dict) -> str:
    """Upload one local image to Leonardo, return its ``imageId``."""
    import httpx

    ext = Path(image_path).suffix.lstrip(".").lower() or "png"
    init_resp = client.post(
        f"{_BASE_URL}/init-image",
        headers=headers,
        json={"extension": ext},
    )
    if init_resp.status_code >= 400:
        raise _LeonardoError(f"init-image failed ({init_resp.status_code}): {init_resp.text[:300]}")
    init_data = init_resp.json().get("uploadInitImage", {})
    image_id = init_data.get("id")
    upload_url = init_data.get("url")
    fields = init_data.get("fields")
    if not image_id or not upload_url or not fields:
        raise _LeonardoError(f"Unexpected init-image response: {init_resp.text[:300]}")

    import json as _json

    fields_dict = fields if isinstance(fields, dict) else _json.loads(fields)
    with open(image_path, "rb") as fh:
        # Presigned-URL multipart upload — uses its own httpx client (no auth
        # header; the S3-style fields carry the authorization).
        upload_resp = httpx.post(
            upload_url,
            data=fields_dict,
            files={"file": (Path(image_path).name, fh, f"image/{ext}")},
            timeout=60.0,
        )
    if upload_resp.status_code not in (200, 204):
        raise _LeonardoError(
            f"Presigned upload failed ({upload_resp.status_code}): {upload_resp.text[:300]}"
        )
    return image_id


def _poll_generation(client: "Any", generation_id: str, headers: dict, timeout: float) -> dict:
    """Poll GET /generations/{id} until COMPLETE or FAILED, or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"{_BASE_URL}/generations/{generation_id}", headers=headers)
        if resp.status_code >= 400:
            raise _LeonardoError(f"Poll failed ({resp.status_code}): {resp.text[:300]}")
        data = resp.json().get("generations_by_pk", {})
        status = data.get("status")
        if status == "COMPLETE":
            return data
        if status == "FAILED":
            raise _LeonardoError(f"Generation failed: {data}")
        time.sleep(4.0)
    raise _LeonardoError(f"Timed out after {timeout:.0f}s waiting for generation {generation_id}")


def _extract_video_url(generation_data: dict) -> Optional[str]:
    """Pull a video URL out of Leonardo's generation response.

    Response shapes for video generations aren't fully nailed down without a
    live key to test against, so this tries the field names documented for
    Motion/image-to-video responses, in order of likelihood, instead of
    assuming one exact path.
    """
    if generation_data.get("motionMP4URL"):
        return generation_data["motionMP4URL"]
    images = generation_data.get("generated_images") or []
    for img in images:
        for key in ("motionMP4URL", "url", "videoUrl"):
            if img.get(key):
                return img[key]
    for key in ("videoUrl", "video_url", "url"):
        if generation_data.get(key):
            return generation_data[key]
    return None


def _build_payload(
    model: str,
    prompt: str,
    start_id: str,
    end_id: str,
    api_resolution: str,
    dims: Optional[tuple],
) -> tuple[str, dict]:
    """Return (full_url, json_payload) for the given model family.

    Veo3.1 and Kling 3.0 use entirely different request shapes -- Veo posts
    flat fields to the v1 image-to-video endpoint, Kling posts a nested
    ``parameters.guidances`` block to the v2 generations endpoint -- per
    Leonardo's own per-model API docs (June 2026).
    """
    if model in _KLING_MODELS:
        kling_model = "kling-3.0" if model == "kling-3.0" else "kling-3.0-turbo"
        mode = "RESOLUTION_1080" if api_resolution == "RESOLUTION_1080" else "RESOLUTION_720"
        parameters: dict = {
            "prompt": prompt[:1500],
            "duration": 5,
            "mode": mode,
            "motion_has_audio": False,
            "guidances": {
                "start_frame": [{"image": {"id": start_id, "type": "UPLOADED"}}],
                "end_frame": [{"image": {"id": end_id, "type": "UPLOADED"}}],
            },
        }
        if dims:
            parameters["width"], parameters["height"] = dims
        return (
            f"{_V2_BASE_URL}/generations",
            {"model": kling_model, "public": False, "parameters": parameters},
        )

    # Veo3.1 / Veo3.1 Fast (opt-in, kept for callers who explicitly want it).
    payload = {
        "prompt": prompt[:1500],
        "imageId": start_id,
        "imageType": "UPLOADED",
        "endFrameImage": {"id": end_id, "type": "UPLOADED"},
        "resolution": api_resolution,
        # Leonardo forces 8s whenever endFrameImage is set (true start->end
        # interpolation requires it) -- send it explicitly so behavior
        # doesn't depend on an undocumented default.
        "duration": 8,
        "model": model,
    }
    if dims:
        payload["width"], payload["height"] = dims
    return f"{_BASE_URL}/generations-image-to-video", payload


def _extract_generation_id(gen_data: dict) -> Optional[str]:
    """Pull the generationId out of either v1 or v2 submit responses."""
    return (
        gen_data.get("motionVideoGenerationJob", {}).get("generationId")
        or gen_data.get("sdGenerationJob", {}).get("generationId")
        or gen_data.get("generationId")
        or gen_data.get("generation", {}).get("id")
        or gen_data.get("id")
    )


@ToolRegistry.register("leonardo_video_generate")
class LeonardoVideoGenerateTool(BaseTool):
    """Generate a start->end frame motion video clip via Leonardo.ai."""

    tool_id = "leonardo_video_generate"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="leonardo_video_generate",
            description=(
                "Generate a short video clip that animates FROM a start image"
                " TO an end image (true start/end-frame interpolation, not a"
                " single-image motion guess) via Leonardo.ai. Returns the"
                " hosted video URL. Designed for continuity-style time-lapse"
                " clips where labor/machinery must look continuous rather"
                " than teleporting between two states."
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
                    "resolution": {
                        "type": "string",
                        "description": "Output resolution: '720p' or '1080p'. Default '720p'.",
                    },
                    "orientation": {
                        "type": "string",
                        "description": (
                            "'portrait' (9:16, default — vertical reels) or 'landscape'"
                            " (16:9). Leonardo defaults to landscape unless width/height"
                            " are explicitly sent, so this tool sends them for you."
                        ),
                    },
                    "model": {
                        "type": "string",
                        "description": (
                            "'kling-3.0' (default — cheapest model with real start/end-frame"
                            " interpolation, ~$1.26/clip at 5s) or 'VEO3_1' / 'VEO3_1FAST'"
                            " (Google Veo, sharper motion but forces 8s clips and costs"
                            " ~$4.78 / ~$2.44 per clip respectively)."
                        ),
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional local file path to download the resulting video to.",
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": "Max seconds to wait for generation to complete. Default 300.",
                    },
                },
                "required": ["start_image_path", "end_image_path", "prompt"],
            },
            category="media",
            required_capabilities=["network:fetch"],
            timeout_seconds=360.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        start_image_path = params.get("start_image_path", "")
        end_image_path = params.get("end_image_path", "")
        prompt = params.get("prompt", "")
        if not start_image_path or not end_image_path or not prompt:
            return ToolResult(
                tool_name="leonardo_video_generate",
                content="start_image_path, end_image_path, and prompt are all required.",
                success=False,
            )
        for label, p in (("start_image_path", start_image_path), ("end_image_path", end_image_path)):
            if not Path(p).exists():
                return ToolResult(
                    tool_name="leonardo_video_generate",
                    content=f"{label} does not exist: {p}",
                    success=False,
                )

        api_key = os.environ.get("LEONARDO_API_KEY")
        if not api_key:
            return ToolResult(
                tool_name="leonardo_video_generate",
                content="No API key configured. Set LEONARDO_API_KEY.",
                success=False,
            )

        try:
            import httpx
        except ImportError:
            return ToolResult(
                tool_name="leonardo_video_generate",
                content="httpx package not installed. Install with: pip install httpx",
                success=False,
            )

        resolution = params.get("resolution", "720p")
        api_resolution = _RESOLUTION_REMAP.get(resolution, resolution)
        orientation = str(params.get("orientation", "portrait")).strip().lower()
        dims_map = _LANDSCAPE_DIMENSIONS if orientation == "landscape" else _PORTRAIT_DIMENSIONS
        dims = dims_map.get(api_resolution)
        model = params.get("model", _DEFAULT_MODEL)
        output_path = params.get("output_path")
        timeout_seconds = float(params.get("timeout_seconds", 300))

        headers = {"Authorization": f"Bearer {api_key}", "accept": "application/json"}

        try:
            with httpx.Client(timeout=60.0) as client:
                start_id = _upload_image(client, start_image_path, headers)
                end_id = _upload_image(client, end_image_path, headers)

                gen_url, gen_payload = _build_payload(
                    model, prompt, start_id, end_id, api_resolution, dims
                )

                gen_resp = client.post(gen_url, headers=headers, json=gen_payload)
                if gen_resp.status_code >= 400:
                    return ToolResult(
                        tool_name="leonardo_video_generate",
                        content=(
                            f"{gen_url} failed"
                            f" ({gen_resp.status_code}): {gen_resp.text[:500]}"
                        ),
                        success=False,
                    )
                gen_data = gen_resp.json()
                generation_id = _extract_generation_id(gen_data)
                if not generation_id:
                    return ToolResult(
                        tool_name="leonardo_video_generate",
                        content=f"Could not find generationId in response: {gen_resp.text[:500]}",
                        success=False,
                    )

                generation_data = _poll_generation(client, generation_id, headers, timeout_seconds)
                video_url = _extract_video_url(generation_data)
                if not video_url:
                    return ToolResult(
                        tool_name="leonardo_video_generate",
                        content=(
                            "Generation completed but no video URL was found in the"
                            f" response. Raw response: {generation_data}"
                        ),
                        success=False,
                        metadata={"generation_id": generation_id},
                    )
        except _LeonardoError as exc:
            return ToolResult(
                tool_name="leonardo_video_generate",
                content=f"Leonardo error: {exc}",
                success=False,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_name="leonardo_video_generate",
                content=f"Video generation error: {exc}",
                success=False,
            )

        if output_path:
            try:
                resp = httpx.get(video_url, follow_redirects=True, timeout=120.0)
                resp.raise_for_status()
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(resp.content)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(
                    tool_name="leonardo_video_generate",
                    content=f"Video generated but failed to save: {exc}. URL: {video_url}",
                    success=False,
                    metadata={"url": video_url, "resolution": resolution},
                )

        return ToolResult(
            tool_name="leonardo_video_generate",
            content=output_path or video_url,
            success=True,
            metadata={
                "url": video_url,
                "resolution": resolution,
                "orientation": orientation,
                "dimensions": dims,
                "model": model,
                "generation_id": generation_id,
            },
        )


__all__ = ["LeonardoVideoGenerateTool"]
