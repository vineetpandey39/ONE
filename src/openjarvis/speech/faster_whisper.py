"""Faster-Whisper speech-to-text backend (local, CTranslate2-based)."""

from __future__ import annotations

import os
import tempfile
import threading
from typing import List, Optional

from openjarvis.core.registry import SpeechRegistry
from openjarvis.speech._stubs import Segment, SpeechBackend, TranscriptionResult

try:
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio
except ImportError:
    WhisperModel = None  # type: ignore[assignment, misc]
    decode_audio = None  # type: ignore[assignment, misc]

# Confirmed live (2026-07-20): unconstrained language auto-detect
# misclassified a short, clear English phrase ("How are you JARVIS?") as
# Turkish -- a well-known Whisper failure mode on short audio (too little
# phonetic evidence for reliable language ID across the model's 90+
# languages). Vineet's household only ever speaks English/Hindi/Hinglish,
# so when no language is pinned in config.toml, restrict auto-detect's
# choice to just these two instead of the full set.
_SUPPORTED_LANGUAGES = ("en", "hi")


_ONE_VOCABULARY_PROMPT = (
    "The wake name ONE is pronounced one and must be written ONE, never 1. "
    "JARVIS, Vineet, PostForge, Obsidian, TITAN, ALFA, BETA, HERMES, "
    "ARES, APOLLO, ATHENA, HEPHAISTOS, POSEIDON, and ZEUS. Commands may be "
    "spoken in English, Hindi, or Hinglish."
)

# Short proper nouns are the words most likely to get mis-heard. `hotwords`
# biases recognition toward these without changing decoding behavior the way
# `initial_prompt` does, so it is additive on top of the prompt above rather
# than a replacement for it.
_ONE_HOTWORDS = (
    "ONE, JARVIS, Vineet, ALFA, BETA, TITAN, HERMES, ARES, APOLLO, ATHENA, "
    "HEPHAISTOS, POSEIDON, ZEUS, JOBHUNT, status, Obsidian, PostForge"
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
        cpu_threads: int = 0,
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._cpu_threads = cpu_threads
        self._model: Optional[WhisperModel] = None
        # /transcribe now runs off the event loop via run_in_threadpool, and
        # /native-record already did -- both can genuinely overlap now (e.g. a
        # button-press command arriving while an always-listening window is
        # still transcribing). CTranslate2 model instances aren't documented
        # as safe for concurrent .transcribe() calls from multiple threads;
        # serialize access rather than risk interleaved/corrupted output.
        self._lock = threading.Lock()

    def _ensure_model(self) -> WhisperModel:
        """Lazy-load the Whisper model on first use."""
        if self._model is None:
            if WhisperModel is None:
                raise ImportError(
                    "faster-whisper is not installed. "
                    "Install with: uv sync --extra speech"
                )
            kwargs: dict = {
                "device": self._device,
                "compute_type": self._compute_type,
            }
            # Only pass cpu_threads when explicitly set (>0) -- 0 means "let
            # faster-whisper pick its own default", and it errors if given 0
            # directly. Irrelevant on GPU, but harmless to include either way.
            if self._cpu_threads > 0:
                kwargs["cpu_threads"] = self._cpu_threads
            self._model = WhisperModel(self._model_size, **kwargs)
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

        # Write audio to a temp file (faster-whisper/PyAV needs a file path
        # to decode from), then decode it once up front into a raw array so
        # it can be reused for both language detection and the real
        # transcription pass below without decoding twice.
        suffix = f".{format}" if not format.startswith(".") else format
        # Windows locks an open NamedTemporaryFile, so PyAV cannot reopen it.
        # Close the file before decoding and remove it explicitly after.
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio)
            tmp.flush()
            temp_path = tmp.name
        try:
            audio_array = decode_audio(temp_path)
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

        # Voice commands are short. Greedy decoding and VAD preserve command
        # accuracy while avoiding the slower multi-beam search path.
        kwargs = {
            "beam_size": 1,
            "best_of": 1,
            # A bare 0.0 here (not a list) silently disabled faster-whisper's
            # own hallucination-recovery mechanism: internally it only
            # retries at a higher temperature when compression_ratio /
            # log_prob_threshold flag a bad segment, and it can only do that
            # if `temperature` is a list with more than one value to fall
            # back through (see faster_whisper/transcribe.py's `for
            # temperature in options.temperatures: ... if not needs_fallback:
            # break / else: return the best of only what was tried`). With a
            # single float, the thresholds below still correctly *detect* a
            # repetition-loop hallucination but then return it anyway, since
            # there's nothing else to fall back to — confirmed via a real
            # "two, one, two, one, ..." transcript that got returned despite
            # exceeding compression_ratio_threshold. This is the library's
            # own documented default fallback ladder, not a guess.
            "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            "condition_on_previous_text": False,
            "word_timestamps": False,
            "initial_prompt": _ONE_VOCABULARY_PROMPT,
            "hotwords": _ONE_HOTWORDS,
            "vad_filter": True,
            "vad_parameters": {
                "min_silence_duration_ms": 300,
                "speech_pad_ms": 180,
            },
            # Anti-hallucination decode guards. no_speech_threshold/
            # log_prob_threshold are faster-whisper's own library defaults,
            # made explicit here so they're visible and tunable in one place
            # rather than implicit. compression_ratio_threshold is tightened
            # from the 2.4 default to 2.2 — the repeated-phrase hallucination
            # pattern (e.g. a room-noise clip transcribed as the same word
            # looping) shows up as a high compression ratio, so catching it
            # earlier trades a slightly higher chance of dropping a genuine
            # fast/repetitive utterance for a lower chance of ONE inventing
            # text on a noisy mic. hallucination_silence_threshold actively
            # zeroes out audio in segments the model flags as likely silence
            # being hallucinated over — new in this pass, previously unset
            # (None = disabled).
            "no_speech_threshold": 0.6,
            "log_prob_threshold": -1.0,
            "compression_ratio_threshold": 2.2,
            "hallucination_silence_threshold": 2.0,
        }
        if language:
            kwargs["language"] = language
        else:
            # No language pinned in config.toml -- restrict auto-detect to
            # English/Hindi (see _SUPPORTED_LANGUAGES above) instead of
            # trusting Whisper's single top guess across its full language
            # set, which is what produced the Turkish misfire.
            try:
                with self._lock:
                    _, _, all_probs = model.detect_language(
                        audio=audio_array,
                        vad_filter=True,
                        vad_parameters=kwargs["vad_parameters"],
                    )
                probs = dict(all_probs)
                kwargs["language"] = max(_SUPPORTED_LANGUAGES, key=lambda lang: probs.get(lang, 0.0))
            except Exception:
                pass  # fall through to full auto-detect if detection itself fails

        with self._lock:
            segments_iter, info = model.transcribe(audio_array, **kwargs)
            segments_list = list(segments_iter)

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
