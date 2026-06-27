"""Conservative transcript normalization for ONE voice commands."""

from __future__ import annotations

import re


def normalize_one_transcript(text: str) -> str:
    """Repair short, high-confidence ONE/JARVIS command mishearings."""
    cleaned = " ".join(str(text or "").strip().split())
    if not cleaned:
        return cleaned

    compact = re.sub(r"[^a-z0-9]+", " ", cleaned.lower()).strip()
    words = compact.split()
    known_check_ins = {
        "jai abhis arirabh",
        "jai abish arirabh",
        "jarvis are you up",
        "jervis are you up",
        "jarvish are you up",
        "hey jarvis are you up",
        "one are you up",
    }
    if len(words) <= 7 and (
        compact in known_check_ins
        or (
            "are you up" in compact
            and any(name in compact for name in ("jarvis", "jervis", "jarvish", "one"))
        )
    ):
        return "ONE, are you up?"

    alias_match = re.match(
        r"^(?:hey\s+)?(?:jarvis|jervis|jarvish)\b[,:]?\s*(.*)$",
        cleaned,
        re.IGNORECASE,
    )
    if alias_match:
        remainder = alias_match.group(1).strip()
        return f"ONE, {remainder}" if remainder else "ONE"

    # Speech models sometimes format the wake name "ONE" as a numbered-list
    # prefix. Only repair it when a clear command verb immediately follows.
    numbered_command = re.match(
        r"^1[\s.,:;-]+(?=(?:activate|run|start|search|find|open|show|create|"
        r"generate|publish|post|remember|save|tell|ask)\b)(.*)$",
        cleaned,
        re.IGNORECASE,
    )
    if numbered_command:
        return f"ONE, {numbered_command.group(1).strip()}"
    return cleaned


__all__ = ["normalize_one_transcript"]
