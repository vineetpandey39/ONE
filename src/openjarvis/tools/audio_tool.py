"""Audio transcription tool — transcribe audio via OpenAI Whisper."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.speech.normalize import normalize_one_transcript
from openjarvis.tools._stubs import BaseTool, ToolSpec

_SUPPORTED_FORMATS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm"}
_MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB


@ToolRegistry.register("audio_transcribe")
class AudioTranscribeTool(BaseTool):
    """Transcribe audio files using OpenAI Whisper or a local provider."""

    tool_id = "audio_transcribe"
    is_local = True
    _local_backend = None

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="audio_transcribe",
            description=(
                "Transcribe an audio file to text."
                " Supports mp3, wav, m4a, ogg, flac, and webm formats."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the audio file to transcribe.",
                    },
                    "language": {
                        "type": "string",
                        "description": "Optional language code (e.g. 'en', 'es').",
                    },
                    "provider": {
                        "type": "string",
                        "description": (
                            "Transcription provider: 'openai' or 'local'."
                            " Default 'local' (free Faster-Whisper)."
                        ),
                    },
                },
                "required": ["file_path"],
            },
            category="media",
            required_capabilities=["file:read"],
        )

    def execute(self, **params: Any) -> ToolResult:
        file_path = params.get("file_path", "")
        if not file_path:
            return ToolResult(
                tool_name="audio_transcribe",
                content="No file_path provided.",
                success=False,
            )

        path = Path(file_path)

        if not path.exists():
            return ToolResult(
                tool_name="audio_transcribe",
                content=f"File not found: {file_path}",
                success=False,
            )

        # Validate format
        suffix = path.suffix.lower()
        if suffix not in _SUPPORTED_FORMATS:
            return ToolResult(
                tool_name="audio_transcribe",
                content=(
                    f"Unsupported audio format '{suffix}'."
                    f" Supported: {', '.join(sorted(_SUPPORTED_FORMATS))}."
                ),
                success=False,
            )

        # Validate file size
        try:
            file_size = path.stat().st_size
        except OSError as exc:
            return ToolResult(
                tool_name="audio_transcribe",
                content=f"Cannot stat file: {exc}",
                success=False,
            )

        if file_size > _MAX_FILE_SIZE_BYTES:
            return ToolResult(
                tool_name="audio_transcribe",
                content=(
                    f"File too large: {file_size} bytes"
                    f" (max {_MAX_FILE_SIZE_BYTES} bytes / 25 MB)."
                ),
                success=False,
            )

        provider = str(params.get("provider", "local")).lower()
        language = params.get("language")

        if provider == "local":
            try:
                if self.__class__._local_backend is None:
                    from openjarvis.core.config import load_config
                    from openjarvis.speech._discovery import get_speech_backend

                    backend = get_speech_backend(load_config())
                    if backend is None or backend.backend_id != "faster-whisper":
                        raise RuntimeError("Local Faster-Whisper is not configured")
                    self.__class__._local_backend = backend
                backend = self.__class__._local_backend
                result = backend.transcribe(
                    path.read_bytes(),
                    format=suffix.lstrip("."),
                    language=str(language) if language else None,
                )
                return ToolResult(
                    tool_name="audio_transcribe",
                    content=normalize_one_transcript(result.text),
                    success=True,
                    metadata={
                        "file_path": str(path.resolve()),
                        "provider": "local",
                        "language": result.language,
                        "duration_ms": int(result.duration_seconds * 1000),
                    },
                )
            except Exception as exc:
                return ToolResult(
                    tool_name="audio_transcribe",
                    content=f"Local transcription error: {type(exc).__name__}: {exc}",
                    success=False,
                )

        if provider != "openai":
            return ToolResult(
                tool_name="audio_transcribe",
                content=(
                    f"Unsupported provider '{provider}'. Supported: 'openai', 'local'."
                ),
                success=False,
            )

        # OpenAI Whisper provider
        try:
            import openai
        except ImportError:
            return ToolResult(
                tool_name="audio_transcribe",
                content=(
                    "openai package not installed. Install with: pip install openai"
                ),
                success=False,
            )

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return ToolResult(
                tool_name="audio_transcribe",
                content="No API key configured. Set OPENAI_API_KEY.",
                success=False,
            )

        try:
            client = openai.OpenAI()
            kwargs: dict[str, Any] = {"model": "whisper-1"}
            if language:
                kwargs["language"] = language

            with open(file_path, "rb") as f:
                kwargs["file"] = f
                transcription = client.audio.transcriptions.create(**kwargs)

            text = transcription.text
            metadata: dict[str, Any] = {
                "file_path": str(path.resolve()),
                "provider": provider,
            }
            if language:
                metadata["language"] = language
            if hasattr(transcription, "duration"):
                metadata["duration_ms"] = int(transcription.duration * 1000)

            return ToolResult(
                tool_name="audio_transcribe",
                content=text,
                success=True,
                metadata=metadata,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="audio_transcribe",
                content=f"Transcription error: {exc}",
                success=False,
            )


__all__ = ["AudioTranscribeTool"]
