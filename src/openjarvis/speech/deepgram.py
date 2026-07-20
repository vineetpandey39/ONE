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
            # Confirmed live (2026-07-20): every real transcribe() call
            # failed with "SSL: CERTIFICATE_VERIFY_FAILED: unable to get
            # local issuer certificate" -- the same Avast SSL-interception
            # issue already fixed for the DuckDuckGo backend
            # (web_search.py's DDGS(verify=False)). __init__ itself never
            # touches the network, so "Speech: deepgram" printed as healthy
            # at every startup this whole time despite this backend never
            # having completed a single real call.
            import httpx

            self._client = DeepgramClient(
                api_key=self._api_key, httpx_client=httpx.Client(verify=False)
            )

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
            # "multi" is Deepgram's own bounded code-switching mode for
            # nova-2/nova-3 (confirmed live, 2026-07-20 -- see SDK's
            # deepgram_listen_provider_v1.py docstring), not full
            # unconstrained detect_language across every supported
            # language. Same reasoning as faster_whisper.py's
            # _SUPPORTED_LANGUAGES restriction: a short utterance has too
            # little signal for reliable free-form language ID, and this
            # household only ever speaks English/Hindi/Hinglish.
            kwargs["language"] = "multi"

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
