"""HTTP surface for the PostForge cockpit tab.

Three endpoints, mirroring what the Vercel app exposed: the pillar list the tab
strip is built from, a refresh that returns only source-verified items from the
last 24 hours, and a generate that refuses anything else.

Every handler is a plain ``def``: refresh spends most of its time waiting on
searches and page fetches, and FastAPI runs sync handlers in a worker thread, so
a long refresh never blocks the event loop the way an ``async def`` doing
blocking I/O would.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from openjarvis.postforge import feed, writer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/postforge", tags=["postforge"])


class RefreshRequest(BaseModel):
    pillar: str = Field(default="news", description="One of the five pillar ids")
    force: bool = Field(default=False, description="Bypass the refresh cache")


class GenerateRequest(BaseModel):
    pillar: str = Field(default="news")
    format: str = Field(default="Carousel")
    items: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/pillars")
def list_pillars() -> dict[str, Any]:
    """What the tab strip renders, and the window it promises."""
    return {
        "pillars": [dict(pillar) for pillar in feed.PILLARS],
        "formats": list(writer.FORMATS),
        "freshnessHours": feed.fresh_hours(),
        "researcher": "sanjeevani",
    }


@router.post("/refresh")
def refresh_pillar(request: RefreshRequest) -> dict[str, Any]:
    """Verified sources for one pillar.

    An empty ``items`` list with a non-zero ``rejected`` count is a real answer,
    not an error: it means nothing published in the window survived verification.
    """
    try:
        return feed.refresh(request.pillar, force=request.force)
    except KeyError as exc:
        raise HTTPException(
            status_code=400, detail=f"Unknown pillar: {request.pillar}"
        ) from exc
    except feed.SanjeevaniUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - the cockpit shows the reason verbatim
        logger.exception("PostForge refresh failed for pillar %s", request.pillar)
        raise HTTPException(
            status_code=502, detail=f"{type(exc).__name__}: {exc}"
        ) from exc


@router.post("/generate")
def generate_post(request: GenerateRequest) -> dict[str, Any]:
    """A post plan from selected items, written by the local model only."""
    try:
        return writer.generate(request.pillar, request.format, request.items)
    except KeyError as exc:
        raise HTTPException(
            status_code=400, detail=f"Unknown format: {request.format}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except writer.GenerationBlocked as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except feed.SanjeevaniUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - same contract as refresh
        logger.exception("PostForge generation failed for pillar %s", request.pillar)
        raise HTTPException(
            status_code=502, detail=f"{type(exc).__name__}: {exc}"
        ) from exc
