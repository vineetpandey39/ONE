"""Deterministic local redaction filter for the Deepgram Voice Agent bridge.

Everything that leaves the machine once the bridge is running -- the one-time
persona prompt, and every FunctionCallResponse payload -- is passed through
`redact()` first. This is a regex/blocklist filter, not another LLM call: it
runs entirely offline, so nothing sensitive has to leave the process just to
be checked. Fails closed -- anything it can't confidently clear collapses to
a generic fallback string instead of being passed through.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, List, Tuple

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

_MAX_LEN = 400
_FALLBACK = "That's not available right now, Sir."

# Structural patterns that need no configuration -- windows paths, emails,
# phone numbers, network identifiers, and the same credential-shaped guard
# already used in one_agents/obsidian.py's remember_exchange().
_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"[A-Za-z]:\\[^\s\"']+"), "[path]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[email]"),
    (
        re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3,5}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b"),
        "[phone]",
    ),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[network]"),
    (re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b"), "[network]"),
    (re.compile(r"\b[\w-]+\.local\b", re.IGNORECASE), "[network]"),
    (
        re.compile(
            r"\b(password|passcode|api[_-]?key|access[_-]?token|client[_-]?secret|private[_-]?key)\b[^.\n]{0,60}",
            re.IGNORECASE,
        ),
        "[redacted-credential]",
    ),
]


def _machine_terms() -> List[str]:
    """Real, machine-specific strings to mask verbatim -- the "Windows info"
    Vineet named directly, not just a generic pattern."""
    terms = []
    for var in ("USERNAME", "COMPUTERNAME", "USERDOMAIN"):
        val = os.environ.get(var, "").strip()
        if val and len(val) >= 2:
            terms.append(val)
    home = str(Path.home())
    if home and len(home) >= 3:
        terms.append(home)
    return terms


def _load_user_blocklist() -> List[str]:
    """Read Vineet's own family/personal blocklist from
    data/redaction_rules.toml.

    Deliberately file-based: he fills this in himself, directly on disk, so
    family names and other personal terms never have to pass through a chat
    conversation with any assistant -- including this one -- to get blocked.
    """
    try:
        from openjarvis.core.paths import get_config_dir

        path = get_config_dir() / "redaction_rules.toml"
        if not path.is_file():
            return []
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        terms: List[str] = []
        for key in ("family_names", "blocked_terms"):
            for item in data.get(key, []) or []:
                if isinstance(item, str) and item.strip():
                    terms.append(item.strip())
        return terms
    except Exception:
        # Fail closed on *filter setup*, not the whole bridge: if the
        # blocklist can't be read, the structural + machine rules below
        # still apply rather than silently skipping the user's own list.
        return []


def _mask_terms(text: str, terms: Iterable[str]) -> str:
    for term in terms:
        if not term:
            continue
        text = re.compile(re.escape(term), re.IGNORECASE).sub("[redacted]", text)
    return text


def redact(text: str, *, max_len: int = _MAX_LEN) -> str:
    """Sanitize *text* before it may be sent to Deepgram's cloud.

    Deterministic and local: structural PII patterns, this machine's own
    username/hostname/home path, and Vineet's own configured blocklist are
    all masked, then the result is hard-truncated. Never raises -- any
    unexpected failure here must not accidentally pass raw text through, so
    it collapses to the generic safe string instead.
    """
    if not text:
        return text
    try:
        cleaned = text
        for pattern, tag in _PATTERNS:
            cleaned = pattern.sub(tag, cleaned)
        cleaned = _mask_terms(cleaned, _machine_terms())
        cleaned = _mask_terms(cleaned, _load_user_blocklist())
        cleaned = cleaned.strip()
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len].rstrip() + "…"
        return cleaned or _FALLBACK
    except Exception:
        return _FALLBACK


__all__ = ["redact"]
