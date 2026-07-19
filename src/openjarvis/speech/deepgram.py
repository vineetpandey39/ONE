"""Deepgram speech-to-text backend (cloud).

Confirmed live (2026-07-19): the SDK installed here is deepgram-sdk 7.5.0,
a ground-up rewrite from the v3.x API this file was originally written
against. `PrerecordedOptions` no longer exists at all -- the old code
imported it in the same `try` block as `DeepgramClient`, so that single
missing name silently disabled the whole backend (both fell back to None)
even with the SDK installed and a valid key. Rewritten against the real
7.5.0 surface: `client.listen.v1.media.transcribe_file(request=<bytes>,
model=..., ...)` takes options as direct keyword arguments now, no
separate options object.
"""

from __future__ import annotations

import os
from typing import List, Optional

from openjarvis.core.registry import SpeechRegistry
from openjarvis.speech._stubs import SpeechBackend, TranscriptionResult

try:
    from deepgram import DeepgramClient
except ImportError:
    DeepgramClient = None  # type: ignore[assignment, misc]

# Same purpose as faster_whisper.py's hotwords list: bias recognition
# toward ONE's own vocabulary. Deepgram's `keywords` param boosts these
# terms without forcing them -- directly targets the confirmed real
# failure mode where "ONE" was misheard as "when" (traces.db, 2026-07-19).
_ONE_KEYWORDS = [
    "ONE", "JARVIS", "Vineet", "HEPHAISTOS", "TITAN", "ALFA", "BETA",
    "HERMES", "ARES", "APOLLO", "ATHENA", "POSEIDON", "ZEUS",
]


@SpeechRegistry.register("deepgram")
class DeepgramSpeechBackend(SpeechBackend):
    """Cloud speech-to-text using Deepgram's REST (prerecorded) API."""

    backend_id = "deepgram"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or os.environ.get("DEEPGRAM_API_KEY", "")
        self._client = None
        if self._api_key and DeepgramClient is not None:
            self._client = DeepgramClient(api_key=self._api_key)

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio using Deepgram's API."""
        if self._client is None:
            raise RuntimeError("Deepgram client not initialized (missing API key?)")

        mime_map = {
            "wav": "audio/wav",
            "mp3": "audio/mpeg",
            "ogg": "audio/ogg",
            "flac": "audio/flac",
            "webm": "audio/webm",
            "m4a": "audio/mp4",
        }
        mime_type = mime_map.get(format, "audio/wav")

        kwargs: dict = {
            "request": audio,
            "model": "nova-2",
            "smart_format": True,
            "keywords": _ONE_KEYWORDS,
            "request_options": {"additional_headers": {"Content-Type": mime_type}},
        }
        if language:
            kwargs["language"] = language
        else:
            kwargs["detect_language"] = True

        response = self._client.listen.v1.media.transcribe_file(**kwargs)

        channels = response.results.channels if response.results else []
        if channels and channels[0].alternatives:
            alt = channels[0].alternatives[0]
            text = alt.transcript or ""
            confidence = alt.confidence
        else:
            text = ""
            confidence = None

        detected_lang = channels[0].detected_language if channels else None
        duration = getattr(response.metadata, "duration", 0.0) if response.metadata else 0.0

        return TranscriptionResult(
            text=text,
            language=detected_lang,
            confidence=confidence,
            duration_seconds=duration,
            segments=[],
        )

    def health(self) -> bool:
        return self._client is not None and bool(self._api_key)

    def supported_formats(self) -> List[str]:
        return ["wav", "mp3", "ogg", "flac", "webm", "m4a"]


__all__ = ["DeepgramSpeechBackend"]
