"""PostForge's verified content cockpit, rebuilt on ONE's own research plane.

The Vercel app this ports (``vineetpandey39/postforge-ai``) discovered sources
with OpenAI's ``gpt-4o-search-preview`` and wrote copy with Anthropic. A floor
run inside ONE may spend neither: ``runtime._research_synthesis`` states that
as a hard product boundary, not a preference. Discovery here goes through
Sanjeevani's self-hosted SearXNG and its bounded page fetcher, and copy through
the same local-only synthesis every floor head already uses.
"""

from openjarvis.postforge.feed import (
    FRESH_HOURS,
    PILLARS,
    Freshness,
    SanjeevaniUnavailable,
    freshness,
    pillar_by_id,
    refresh,
)
from openjarvis.postforge.writer import FORMATS, generate

__all__ = [
    "FORMATS",
    "FRESH_HOURS",
    "PILLARS",
    "Freshness",
    "SanjeevaniUnavailable",
    "freshness",
    "generate",
    "pillar_by_id",
    "refresh",
]
