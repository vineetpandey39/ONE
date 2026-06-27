"""Deprecated — superseded by ``punarnirman.py``.

This module was the first, single-city (Selampur-only) version of the
restoration-reel pipeline. It has been replaced by the universal,
location-rotating ``PunarnirmanAgent`` (registered as ``"punarnirman"``),
which generates prompts on the fly for any city instead of requiring a
hand-written JSON file per location. Kept as an import-safe stub (not
registered) so any stale references don't hard-crash.
"""

from __future__ import annotations

from openjarvis.agents.punarnirman import PunarnirmanAgent as RestorationReelPipelineAgent

__all__ = ["RestorationReelPipelineAgent"]
