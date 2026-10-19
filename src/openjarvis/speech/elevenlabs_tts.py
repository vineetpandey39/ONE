"""ElevenLabs text-to-speech, called against ElevenLabs' own API.

This is the primary narration backend, and it exists because the fal-hosted
route ([[fal_elevenlabs_tts]]) cannot reach it: a cloned voice lives inside the
owner's ElevenLabs account, and fal only exposes its own public voice list.
Sonia's narration therefore has to authenticate as the account that holds the
clone. Every other backend is a fallback for generic speech, never for her
voice -- a clone cannot be reproduced elsewhere.

The key and voice id must be supplied by the caller. They live in LAO's asset
vault, and only a robot token can resolve a secret there -- LAO's admin API
deliberately returns `has_secret: true` and never the value. So narration is
driven by the LAO workflow action `synthesize_elevenlabs`, which resolves both
by name and passes them in. This module never fetches a secret itself, which
is what keeps one copy of it in one place.
"""

from __future__ import annotations

import os
from typing import List

import httpx

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

_API_ROOT = "https://api.elevenlabs.io/v1"
# eleven_multilingual_v2 handles Hinglish code-switching markedly better than
# the English-only models, which matters when a line mixes Hindi and English
# inside one sentence. It is also the model the approved test render used (m2).
_DEFAULT_MODEL = "eleven_multilingual_v2"


@TTSRegistry.register("elevenlabs")
class ElevenLabsTTSBackend(TTSBackend):
    """ElevenLabs' own API, so account-scoped cloned voices are reachable."""

    backend_id = "elevenlabs"

    def __init__(self, *, api_key: str = "", voice_id: str = "", model_id: str = "") -> None:
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self._voice_id = voice_id
        self._model_id = model_id or _DEFAULT_MODEL

    def _key(self) -> str:
        if not self._api_key:
            raise RuntimeError(
                "No ElevenLabs API key was supplied. LAO's vault holds it as "
                "'elevenLabsApiKey' and only a robot can resolve it, so run narration "
                "through the synthesize_elevenlabs workflow action rather than calling "
                "this backend directly."
            )
        return self._api_key

    def _voice(self, voice_id: str = "") -> str:
        voice = voice_id or self._voice_id
        if not voice:
            raise RuntimeError(
                "No voice id was supplied. Sonia's clone is stored in LAO's vault as "
                "'elevenLabsVoiceIdSonia'; a generic fallback voice can never stand in "
                "for it, because a clone only exists inside its own account."
            )
        return voice

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
        stability: float = 0.50,
        similarity_boost: float = 0.75,
        style: float = 0.0,
    ) -> TTSResult:
        voice = self._voice(voice_id)
        # These defaults are the Chairman's own verified settings, taken from
        # the ElevenLabs test render he approved (sp100 s50 sb75 se0 b m2), not
        # values invented here. Changing them changes how Sonia sounds.
        settings = {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "use_speaker_boost": True,
        }
        if speed != 1.0:
            settings["speed"] = speed

        response = httpx.post(
            f"{_API_ROOT}/text-to-speech/{voice}",
            headers={"xi-api-key": self._key(), "accept": "audio/mpeg"},
            json={"text": text, "model_id": self._model_id, "voice_settings": settings},
            timeout=600.0,
        )
        if response.status_code >= 400:
            # ElevenLabs reports quota and voice-permission problems in the body;
            # surfacing it verbatim is what tells a caller whether to fall back.
            raise RuntimeError(
                f"ElevenLabs returned {response.status_code}: {response.text[:300]}"
            )

        return TTSResult(
            audio=response.content,
            format="mp3",
            voice_id=voice,
            metadata={"backend": self.backend_id, "model": self._model_id,
                      "characters": len(text)},
        )

    def available_voices(self) -> List[str]:
        response = httpx.get(f"{_API_ROOT}/voices",
                             headers={"xi-api-key": self._key()}, timeout=60.0)
        response.raise_for_status()
        return [v.get("voice_id", "") for v in response.json().get("voices", [])]

    def health(self) -> bool:
        try:
            return bool(self._key())
        except Exception:  # noqa: BLE001
            return False


__all__ = ["ElevenLabsTTSBackend"]
