"""Image generation tool — generate images via OpenAI gpt-image-1."""

from __future__ import annotations

import base64
import os
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# gpt-image-1 (the only model this tool calls) only accepts these sizes.
# dall-e-3's "1024x1792"/"1792x1024" portrait/landscape sizes are NOT valid
# for gpt-image-1 — its equivalents are "1024x1536"/"1536x1024". We accept
# the old dall-e-3 size strings too and remap them below, so callers built
# against the previous dall-e-3-based tool keep working unchanged.
_VALID_SIZES = {"1024x1024", "1024x1792", "1792x1024", "1024x1536", "1536x1024", "auto"}

# dall-e-3 size -> gpt-image-1 equivalent size.
_SIZE_REMAP = {
    "1024x1792": "1024x1536",
    "1792x1024": "1536x1024",
}


@ToolRegistry.register("image_generate")
class ImageGenerateTool(BaseTool):
    """Generate images from text descriptions via OpenAI DALL-E."""

    tool_id = "image_generate"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="image_generate",
            description=(
                "Generate an image from a text description. Returns the image URL."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Text description of the image to generate.",
                    },
                    "size": {
                        "type": "string",
                        "description": (
                            "Image size: '1024x1024' (square), '1024x1792'"
                            " (9:16 portrait, for Reels/Shorts), or '1792x1024'"
                            " (16:9 landscape). Default '1024x1024'."
                        ),
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional file path to save the image to.",
                    },
                    "provider": {
                        "type": "string",
                        "description": (
                            "Image generation provider: 'openai' or 'flux'."
                            " Defaults to ONE_IMAGE_PROVIDER/openai."
                        ),
                    },
                    "reference_image_path": {
                        "type": "string",
                        "description": (
                            "Optional path to an existing image to edit instead of"
                            " generating from scratch. When set, this calls the"
                            " image-edit API with that image as the base, so the"
                            " camera framing/composition is preserved exactly --"
                            " use this to keep a sequence of frames visually"
                            " locked to the same shot."
                        ),
                    },
                },
                "required": ["prompt"],
            },
            category="media",
            required_capabilities=["network:fetch"],
            # gpt-image-2 at quality="high" and portrait sizes can sometimes
            # take a very long time to respond -- 240s and even 300s have
            # both been observed to time out in production despite being
            # well above the typical case. Per the user's explicit call:
            # don't fight this with ever-bigger-but-still-finite numbers --
            # give it effectively the whole run's budget (30 minutes) so a
            # slow ChatGPT response never kills the pipeline. The
            # pipeline-level retry in ia.py still applies on top
            # of this for genuine errors (not just slowness).
            timeout_seconds=1800.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        prompt = params.get("prompt", "")
        if not prompt:
            return ToolResult(
                tool_name="image_generate",
                content="No prompt provided.",
                success=False,
            )

        size = params.get("size", "1024x1024")
        if size not in _VALID_SIZES:
            return ToolResult(
                tool_name="image_generate",
                content=(
                    f"Invalid size '{size}'."
                    f" Must be one of: {', '.join(sorted(_VALID_SIZES))}."
                ),
                success=False,
            )

        provider = params.get("provider") or os.environ.get("ONE_IMAGE_PROVIDER", "openai")
        provider = str(provider).strip().lower()
        output_path = params.get("output_path")
        reference_image_path = params.get("reference_image_path")

        if provider == "flux":
            flux_result = self._execute_flux(
                prompt=prompt,
                size=size,
                output_path=output_path,
                reference_image_path=reference_image_path,
            )
            if flux_result.success:
                return flux_result
            if os.environ.get("ONE_IMAGE_FALLBACK_OPENAI", "false").strip().lower() not in {"1", "true", "yes"}:
                return flux_result
            if not os.environ.get("OPENAI_API_KEY"):
                return flux_result
            provider = "openai"

        if provider != "openai":
            return ToolResult(
                tool_name="image_generate",
                content=(
                    f"Unsupported provider '{provider}'. Supported providers: openai, flux."
                ),
                success=False,
            )

        try:
            import openai
        except ImportError:
            return ToolResult(
                tool_name="image_generate",
                content=(
                    "openai package not installed. Install with: pip install openai"
                ),
                success=False,
            )

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return ToolResult(
                tool_name="image_generate",
                content="No API key configured. Set OPENAI_API_KEY.",
                success=False,
            )

        api_size = _SIZE_REMAP.get(size, size)

        if reference_image_path:
            from pathlib import Path as _Path

            ref_path = _Path(reference_image_path)
            if not ref_path.is_file():
                return ToolResult(
                    tool_name="image_generate",
                    content=f"Reference image not found: {reference_image_path}",
                    success=False,
                )

        try:
            client = openai.OpenAI()
            if reference_image_path:
                # Edit mode: condition on an existing image so the camera
                # framing/composition is preserved exactly across a
                # sequence of frames, instead of each frame being an
                # independent (and differently-framed) generation.
                with open(reference_image_path, "rb") as ref_file:
                    response = client.images.edit(
                        model="gpt-image-2",
                        image=ref_file,
                        prompt=prompt,
                        size=api_size,
                        quality="high",
                        n=1,
                    )
            else:
                response = client.images.generate(
                    model="gpt-image-2",
                    prompt=prompt,
                    size=api_size,
                    quality="high",
                    n=1,
                )
            b64_data = response.data[0].b64_json
        except Exception as exc:
            return ToolResult(
                tool_name="image_generate",
                content=f"Image generation error: {exc}",
                success=False,
            )

        image_bytes = base64.b64decode(b64_data)

        # Optionally save to file
        if output_path:
            try:
                from pathlib import Path

                Path(output_path).write_bytes(image_bytes)
            except Exception as exc:
                return ToolResult(
                    tool_name="image_generate",
                    content=f"Image generated but failed to save: {exc}.",
                    success=False,
                    metadata={"size": size, "provider": provider},
                )
            return ToolResult(
                tool_name="image_generate",
                content=output_path,
                success=True,
                metadata={"path": output_path, "size": size, "provider": provider},
            )

        # No output_path requested: return the raw bytes as a data URL so
        # callers that expect a usable image reference still get one.
        data_url = f"data:image/png;base64,{b64_data}"
        return ToolResult(
            tool_name="image_generate",
            content=data_url,
            success=True,
            metadata={"size": size, "provider": provider},
        )

    def _execute_flux(
        self,
        *,
        prompt: str,
        size: str,
        output_path: str | None,
        reference_image_path: str | None,
    ) -> ToolResult:
        try:
            import httpx
        except ImportError:
            return ToolResult(
                tool_name="image_generate",
                content="httpx package not installed; local FLUX provider cannot call its server.",
                success=False,
            )

        endpoint = os.environ.get("ONE_FLUX_URL", "http://127.0.0.1:8188").rstrip("/")
        payload: dict[str, Any] = {
            "prompt": prompt,
            "size": _SIZE_REMAP.get(size, size),
            "output_path": output_path,
        }
        if reference_image_path:
            payload["reference_image_path"] = reference_image_path

        try:
            with httpx.Client(timeout=float(os.environ.get("ONE_FLUX_TIMEOUT_SECONDS", "1800"))) as client:
                response = client.post(f"{endpoint}/v1/images/generate", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            return ToolResult(
                tool_name="image_generate",
                content=(
                    f"Local FLUX generation error: HTTP {exc.response.status_code}."
                    f" {detail}"
                ),
                success=False,
                metadata={"provider": "flux", "endpoint": endpoint},
            )
        except Exception as exc:
            return ToolResult(
                tool_name="image_generate",
                content=(
                    f"Local FLUX generation error: {exc}. "
                    "Start it with start-flux.ps1 or enable ONE_FLUX_AUTOSTART=true."
                ),
                success=False,
                metadata={"provider": "flux", "endpoint": endpoint},
            )

        saved_path = data.get("path")
        if saved_path:
            return ToolResult(
                tool_name="image_generate",
                content=str(saved_path),
                success=True,
                metadata={**data, "provider": "flux", "endpoint": endpoint},
            )

        b64_data = data.get("b64_json", "")
        return ToolResult(
            tool_name="image_generate",
            content=f"data:image/png;base64,{b64_data}",
            success=True,
            metadata={**data, "provider": "flux", "endpoint": endpoint},
        )


__all__ = ["ImageGenerateTool"]
