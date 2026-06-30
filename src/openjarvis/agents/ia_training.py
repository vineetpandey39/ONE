"""Runtime access to the canonical IA knowledge pack.

The Markdown files in ``ia_knowledge`` are the source of truth for the
Imagine India agent. They are deliberately loaded at runtime instead of being
duplicated across prompt strings so updating the pack changes the agent's
behavior in one place.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict

_PACK_FILES = (
    "01_IA_Bible_v4.0.md",
    "02_IA_Prompt_Playbook.md",
    "03_IA_SEO_Playbook.md",
    "04_IA_Strategy_Engine.md",
    "05_IA_Memory_System.md",
)


def _pack_dir() -> Path:
    return Path(__file__).resolve().parent / "ia_knowledge"


@lru_cache(maxsize=1)
def load_ia_knowledge_pack() -> Dict[str, str]:
    """Return the canonical IA Markdown files keyed by file name."""
    pack: Dict[str, str] = {}
    for filename in _PACK_FILES:
        path = _pack_dir() / filename
        try:
            pack[filename] = path.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError:
            pack[filename] = path.read_text(encoding="utf-8-sig").strip()
    return pack


@lru_cache(maxsize=1)
def ia_runtime_capsule() -> str:
    """Compact, exact runtime capsule injected into IA prompts and scout calls."""
    sections = []
    for filename, content in load_ia_knowledge_pack().items():
        sections.append(f"[{filename}]\n{content}")
    return "\n\n".join(sections)


@lru_cache(maxsize=1)
def ia_generation_contract() -> str:
    """Short contract used in every visual generation prompt."""
    return (
        " FINAL IA v4 CONTRACT: Follow the canonical IA knowledge pack exactly. "
        "Restore the experience, never the identity. Use one instantly recognizable "
        "hero object occupying 65-75% of every frame. Restore the full surrounding "
        "ecosystem, with roughly 80% of construction activity directly touching the "
        "hero. Keep active workers within 250-600 maximum; no idle workers, no idle "
        "or parked machinery, no side-road distraction, no fantasy architecture, no "
        "readable signs/logos/political posters. Preserve regional identity and make "
        "the neighbourhood visibly better. Sequence: Reality -> Mobilization -> Peak "
        "Engineering -> Finishing -> Public Activation -> Hero Reveal. People should "
        "watch what is transforming, not the workers."
    )


@lru_cache(maxsize=1)
def ia_scout_contract() -> str:
    """Location-selection contract used by scout LLM prompts."""
    return (
        ia_runtime_capsule()
        + "\n\nSCOUT OUTPUT RULES:\n"
        "- Pick only real, specific, named places.\n"
        "- Prefer locations with Recognition 25, Emotion 20, Visible Problem 20, "
        "Transformation 20, Comment Potential 10, Human Experience 5.\n"
        "- Generate only if the calculated viral_score_100 is >= 85.\n"
        "- The hero object must be specific enough to be recognized in under 1 second.\n"
        "- The location must support a full ecosystem restoration, not just cosmetic cleanup."
    )


__all__ = [
    "ia_generation_contract",
    "ia_runtime_capsule",
    "ia_scout_contract",
    "load_ia_knowledge_pack",
]
