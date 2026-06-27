"""Faster-Whisper speech-to-text backend (local, CTranslate2-based)."""

from __future__ import annotations

import os
import tempfile
from typing import List, Optional

from openjarvis.core.registry import SpeechRegistry
from openjarvis.speech._stubs import Segment, SpeechBackend, TranscriptionResult

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None  # type: ignore[assignment, misc]


_ONE_VOCABULARY_PROMPT = (
    "The wake name ONE is pronounced one and must be written ONE, never 1. "
    "JARVIS, Vineet, PostForge, Obsidian, TITAN, ALFA, BETA, HERMES, "
    "ARES, APOLLO, ATHENA, HEPHAISTOS, POSEIDON, and ZEUS. Commands may be "
    "spoken in English, Hindi, or Hinglish."
)


@SpeechRegistry.register("faster-whisper")
class FasterWhisperBackend(SpeechBackend):
    """Local speech-to-text using Faster-Whisper (CTranslate2)."""

    backend_id = "faster-whisper"

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "float16",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model: Optional[WhisperModel] = None

    def _ensure_model(self) -> WhisperModel:
        """Lazy-load the Whisper model on first use."""
        if self._model is None:
            if WhisperModel is None:
                raise ImportError(
                    "faster-whisper is not installed. "
                    "Install with: uv sync --extra speech"
                )
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
        return self._model

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes using Faster-Whisper."""
        model = self._ensure_model()

        # Write audio to a temp file (faster-whisper needs a file path)
        suffix = f".{format}" if not format.startswith(".") else format
        # Windows locks an open NamedTemporaryFile, so PyAV cannot reopen it.
        # Close the file before transcription and remove it explicitly after.
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio)
            tmp.flush()
            temp_path = tmp.name

        # Voice commands are short. Greedy decoding and VAD preserve command
        # accuracy while avoiding the slower multi-beam search path.
        kwargs = {
            "beam_size": 1,
            "best_of": 1,
            "temperature": 0.0,
            "condition_on_previous_text": False,
            "word_timestamps": False,
            "initial_prompt": _ONE_VOCABULARY_PROMPT,
            "vad_filter": True,
            "vad_parameters": {
                "min_silence_duration_ms": 300,
                "speech_pad_ms": 180,
            },
        }
        if language:
            kwargs["language"] = language

        try:
            segments_iter, info = model.transcribe(temp_path, **kwargs)
            segments_list = list(segments_iter)
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

        # Build result
        text = "".join(seg.text for seg in segments_list).strip()
        segments = [
            Segment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                confidence=None,
            )
            for seg in segments_list
        ]

        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            confidence=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", 0.0),
            segments=segments,
        )

    def health(self) -> bool:
        """Check if model is loaded or loadable."""
        if self._model is not None:
            return True
        return WhisperModel is not None

    def warmup(self) -> bool:
        """Load the model before the first voice command arrives."""
        self._ensure_model()
        return True

    def supported_formats(self) -> List[str]:
        """Supported audio formats (same as ffmpeg/Whisper)."""
        return ["wav", "mp3", "m4a", "ogg", "flac", "webm"]
