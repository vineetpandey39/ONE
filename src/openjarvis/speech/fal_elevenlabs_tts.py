"""ElevenLabs (multilingual v3) text-to-speech backend, served via fal.ai.

Runs through fal's hosted ElevenLabs endpoint rather than ElevenLabs' own
API directly, so this re-uses the FAL_KEY credential the rest of the
IA pipeline already authenticates with (video_tool.py,
image_tool.py) -- no separate ElevenLabs account/API key needs to be
configured. Picked over Kokoro/Cartesia specifically for the storytelling
intro clip because eleven-v3 has materially better Hindi/Hinglish
pronunciation and natural delivery, which matters once a real human voice
is the centerpiece of a clip (unlike the silent drone-photography clips,
which never needed TTS at all).
"""

from __future__ import annotations

import os
from typing import List

import httpx

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

_MODEL_ID = "fal-ai/elevenlabs/tts/eleven-v3"

# A default multilingual voice id -- callers should normally pass their own
# voice_id once they've picked one from fal's voice list for this model, but
# this keeps the backend usable out of the box.
_DEFAULT_VOICE_ID = "Rachel"


@TTSRegistry.register("fal_elevenlabs")
class FalElevenLabsTTSBackend(TTSBackend):
    """ElevenLabs eleven-v3 TTS, called through fal.ai's hosted endpoint."""

    backend_id = "fal_elevenlabs"

    def __init__(self, *, api_key: str = "") -> None:
        self._api_key = api_key or os.environ.get("FAL_KEY", "")

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
        language: str = "",
    ) -> TTSResult:
        if not self._api_key:
            raise RuntimeError("FAL_KEY not set")

        try:
            import fal_client
        except ImportError as exc:
            raise RuntimeError(
                "fal_client package not installed. Install with: pip install fal-client"
            ) from exc

        arguments = {
            "text": text,
            "voice": voice_id or _DEFAULT_VOICE_ID,
        }
        # fal's stable_speed knob -- only send it when the caller deviates
        # from real-time pace, same convention video_tool/image_tool follow
        # of not sending defaults the model already assumes.
        if speed != 1.0:
            arguments["speed"] = speed

        result = fal_client.subscribe(_MODEL_ID, arguments=arguments)
        audio_url = result["audio"]["url"]

        resp = httpx.get(audio_url, follow_redirects=True, timeout=120.0)
        resp.raise_for_status()

        return TTSResult(
            audio=resp.content,
            format=output_format or "mp3",
            voice_id=voice_id or _DEFAULT_VOICE_ID,
            metadata={"backend": "fal_elevenlabs", "model": _MODEL_ID, "url": audio_url},
        )

    def available_voices(self) -> List[str]:
        # fal's hosted endpoint doesn't expose a voices-list call the same
        # way ElevenLabs' own API does -- voice ids are picked from fal's
        # model page / ElevenLabs' published voice library and passed in
        # directly as voice_id.
        return [_DEFAULT_VOICE_ID]

    def health(self) -> bool:
        return bool(self._api_key)


__all__ = ["FalElevenLabsTTSBackend"]
