"""Tiny local FLUX image server for ONE.

The server is intentionally small and OpenAI-independent. It lazy-loads the
diffusers pipeline on the first generation request so ONE startup stays fast.
"""

from __future__ import annotations

import base64
import io
import os
import random
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="ONE Local FLUX", version="0.1")

_PIPELINE: Any | None = None
_MODEL_ID = ""


def _one_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _configure_cache() -> None:
    try:
        from pip_system_certs.wrapt_requests import inject_truststore

        inject_truststore()
    except Exception:
        pass

    root = _one_root()
    cache_root = root.parent / "data" / "model_cache"
    runtime_home = root.parent / "data" / "runtime_home"
    openjarvis_home = root.parent / "data"
    cache_root.mkdir(parents=True, exist_ok=True)
    runtime_home.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("OPENJARVIS_HOME", str(openjarvis_home))
    os.environ.setdefault("HF_HOME", str(cache_root / "huggingface"))
    os.environ.setdefault("TORCH_HOME", str(cache_root / "torch"))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_root / "xdg"))
    os.environ.setdefault("HOME", str(runtime_home))
    os.environ.setdefault("USERPROFILE", str(runtime_home))
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    if hf_token:
        os.environ.setdefault("HUGGINGFACE_HUB_TOKEN", hf_token)
    try:
        from openjarvis.core.credentials import inject_credentials

        inject_credentials()
    except Exception:
        pass
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    if hf_token:
        os.environ["HUGGINGFACE_HUB_TOKEN"] = hf_token


def _load_pipeline() -> Any:
    global _PIPELINE, _MODEL_ID
    if _PIPELINE is not None:
        return _PIPELINE

    _configure_cache()
    model_id = os.environ.get("ONE_FLUX_MODEL", "black-forest-labs/FLUX.1-schnell").strip()
    if not model_id:
        raise RuntimeError("ONE_FLUX_MODEL is empty")

    import torch
    from diffusers import FluxPipeline

    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    pipe = FluxPipeline.from_pretrained(model_id, torch_dtype=dtype)

    if torch.cuda.is_available():
        pipe.enable_model_cpu_offload()
        try:
            pipe.enable_vae_slicing()
            pipe.enable_vae_tiling()
        except Exception:
            pass
    else:
        pipe = pipe.to("cpu")

    _PIPELINE = pipe
    _MODEL_ID = model_id
    return pipe


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    size: str = "1024x1024"
    output_path: str | None = None
    reference_image_path: str | None = None
    steps: int | None = None
    guidance_scale: float | None = None
    seed: int | None = None


def _parse_size(size: str) -> tuple[int, int]:
    remap = {
        "1024x1792": "1024x1536",
        "1792x1024": "1536x1024",
        "auto": os.environ.get("ONE_FLUX_DEFAULT_SIZE", "1024x1024"),
    }
    normalized = remap.get(size, size)
    try:
        width_s, height_s = normalized.lower().split("x", 1)
        width = int(width_s)
        height = int(height_s)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid size: {size}") from exc
    if width < 256 or height < 256 or width > 1536 or height > 1536:
        raise HTTPException(status_code=400, detail="Size must stay between 256 and 1536 px per side")
    return width, height


@app.get("/health")
def health() -> dict[str, Any]:
    _configure_cache()
    return {
        "status": "ok",
        "model": os.environ.get("ONE_FLUX_MODEL", "black-forest-labs/FLUX.1-schnell"),
        "loaded": _PIPELINE is not None,
        "hf_token_configured": bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")),
        "hf_home": os.environ.get("HF_HOME", ""),
    }


@app.post("/v1/images/generate")
def generate(req: GenerateRequest) -> dict[str, Any]:
    width, height = _parse_size(req.size)
    try:
        pipe = _load_pipeline()
    except Exception as exc:
        detail = str(exc)
        if "certificate_verify_failed" in detail.lower() or "ssl" in detail.lower():
            detail = (
                "FLUX could not reach Hugging Face because Windows certificate trust "
                "was not available to the Python process. Restart ONE/FLUX so the "
                "trust-store injection can take effect."
            )
        if "gated repo" in detail.lower() or "401" in detail:
            detail = (
                "FLUX model access is gated. Accept the model license on Hugging Face "
                "and save your Hugging Face token to the ONE credential vault with "
                "set-flux-hf-token.ps1, then restart ONE/FLUX."
            )
        raise HTTPException(status_code=503, detail=detail) from exc

    steps = req.steps or int(os.environ.get("ONE_FLUX_STEPS", "4"))
    guidance_scale = req.guidance_scale
    if guidance_scale is None:
        guidance_scale = float(os.environ.get("ONE_FLUX_GUIDANCE_SCALE", "0.0"))
    seed = req.seed if req.seed is not None else random.randint(0, 2**31 - 1)

    import torch

    generator = torch.Generator("cuda" if torch.cuda.is_available() else "cpu").manual_seed(seed)
    image = pipe(
        prompt=req.prompt,
        width=width,
        height=height,
        num_inference_steps=steps,
        guidance_scale=guidance_scale,
        generator=generator,
    ).images[0]

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    image_bytes = buffer.getvalue()

    saved_path = None
    if req.output_path:
        out = Path(req.output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(image_bytes)
        saved_path = str(out)

    return {
        "b64_json": base64.b64encode(image_bytes).decode("ascii"),
        "path": saved_path,
        "model": _MODEL_ID,
        "size": f"{width}x{height}",
        "seed": seed,
        "steps": steps,
        "guidance_scale": guidance_scale,
        "reference_image_used": False,
    }
