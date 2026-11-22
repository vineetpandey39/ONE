"""Offline mastering, diagnostic lyric timing and beat preparation for DIVYA.

This module never certifies sung pronunciation.  It binds exact authored Hindi
caption spelling to measured local ASR word times and keeps a scored diagnostic
receipt so low-confidence alignments remain visible to human review.
"""
from __future__ import annotations

import math
import re
import subprocess
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from .core import Blocked, digest, read, write
from .local_finish import master


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    return "".join(ch for ch in value if unicodedata.category(ch)[0] in "LMN")


def _analysis_audio(root: Path) -> Path:
    target = root / "audio" / "analysis.wav"
    command = [
        "ffmpeg", "-y", "-v", "error", "-i", str(root / "audio" / "composition.mp3"),
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(target),
    ]
    subprocess.run(command, check=True)
    return target


def _words(transcript: dict) -> list[dict]:
    return [
        {"word": word["word"], "start": float(word["start"]), "end": float(word["end"])}
        for segment in transcript["segments"]
        for word in segment.get("words", [])
        if _norm(word.get("word", ""))
    ]


def align_lyrics(root: Path) -> list[dict]:
    mission = read(root / "mission.json")
    words = _words(read(root / "audio" / "local-transcript.json"))
    if not words:
        raise Blocked("Local transcript has no measured word timestamps")
    pointer = 0
    prior_end = 0.0
    cues: list[dict] = []
    diagnostic: list[dict] = []
    for occurrence, line in enumerate(mission["lyrics"], 1):
        expected = _norm(line)
        expected_words = max(1, len(re.findall(r"[\w\u0900-\u097f]+", line)))
        best = None
        # A bounded monotonic search tolerates ASR insertions while preventing a
        # repeated refrain from stealing an earlier lyric occurrence.
        for start in range(pointer, min(len(words), pointer + 20)):
            for count in range(max(2, expected_words - 3), expected_words + 6):
                end = start + count
                if end > len(words):
                    continue
                observed = _norm(" ".join(item["word"] for item in words[start:end]))
                ratio = SequenceMatcher(None, expected, observed, autojunk=False).ratio()
                length_fit = 1 - min(1, abs(len(expected) - len(observed)) / max(len(expected), 1))
                duration = words[end - 1]["end"] - words[start]["start"]
                duration_fit = 1 if 1.5 <= duration <= 12 else 0.5
                score = ratio * 0.82 + length_fit * 0.13 + duration_fit * 0.05 - (start - pointer) * 0.004
                candidate = (score, ratio, start, end, observed)
                if best is None or candidate > best:
                    best = candidate
        if best is None or best[1] < 0.34:
            raise Blocked(f"Unable to derive a defensible local timing for lyric occurrence {occurrence}")
        score, ratio, start, end, observed = best
        cue_start = max(prior_end + 0.015, words[start]["start"])
        cue_end = max(cue_start + 0.25, words[end - 1]["end"])
        cues.append(
            {
                "start": round(cue_start, 3),
                "end": round(cue_end, 3),
                "text": line,
                "timing_source": "local_faster_whisper",
            }
        )
        diagnostic.append(
            {
                "occurrence": occurrence,
                "expected": line,
                "observed_asr": " ".join(item["word"] for item in words[start:end]),
                "character_similarity": round(ratio, 4),
                "selection_score": round(score, 4),
                "start": round(cue_start, 3),
                "end": round(cue_end, 3),
                "status": "LISTENING_REQUIRED",
            }
        )
        pointer = end
        prior_end = cue_end
    write(root / "lyrics-cues.json", cues)
    write(
        root / "qa" / "caption-alignment-diagnostic.json",
        {
            "status": "LISTENING_REQUIRED",
            "audio_sha256": digest(root / "audio" / "composition.mp3"),
            "transcript_sha256": digest(root / "audio" / "local-transcript.json"),
            "caption_spelling": "authoritative mission lyrics; ASR never rewrites Devanagari",
            "occurrences": diagnostic,
        },
    )
    return cues


def beat_map(root: Path, analysis: Path) -> dict:
    rate, samples = wavfile.read(analysis)
    signal = samples.astype(np.float32)
    signal /= max(float(np.max(np.abs(signal))), 1.0)
    frame, hop = 1024, 256
    count = max(0, 1 + (len(signal) - frame) // hop)
    if count < 20:
        raise Blocked("Audio is too short for local beat analysis")
    window = np.hanning(frame).astype(np.float32)
    spectra = np.empty((count, frame // 2 + 1), np.float32)
    for index in range(count):
        spectra[index] = np.abs(np.fft.rfft(signal[index * hop:index * hop + frame] * window))
    flux = np.maximum(0, np.diff(spectra, axis=0)).sum(axis=1)
    flux = np.concatenate(([0.0], flux))
    smooth = np.convolve(flux, np.ones(17) / 17, mode="same")
    onset = np.maximum(0, flux - smooth)
    onset /= max(float(np.quantile(onset, 0.98)), 1e-9)
    onset_rate = rate / hop
    lag_min = max(1, round(onset_rate * 60 / 150))
    lag_max = max(lag_min + 1, round(onset_rate * 60 / 55))
    correlation = np.zeros(lag_max + 1, dtype=np.float64)
    for candidate_lag in range(lag_min, lag_max + 1):
        correlation[candidate_lag] = float(np.dot(onset[:-candidate_lag], onset[candidate_lag:]))
    lags = np.arange(lag_min, min(lag_max + 1, len(correlation)))
    if not len(lags):
        raise Blocked("No valid beat lags")
    # Favor the devotional 65–110 BPM range without fabricating a fixed tempo.
    bpms = 60 * onset_rate / lags
    weights = np.where((bpms >= 65) & (bpms <= 110), 1.08, 1.0)
    lag = int(lags[np.argmax(correlation[lags] * weights)])
    bpm = float(60 * onset_rate / lag)
    peak_indices = np.flatnonzero(onset >= np.quantile(onset, 0.86))
    phase_scores = [float(onset[np.arange(phase, len(onset), lag)].sum()) for phase in range(lag)]
    phase = int(np.argmax(phase_scores))
    duration = len(signal) / rate
    raw = np.arange(phase, len(onset), lag)
    beats = []
    for index in raw:
        neighborhood = peak_indices[np.abs(peak_indices - index) <= max(1, round(onset_rate * 0.09))]
        chosen = int(neighborhood[np.argmax(onset[neighborhood])]) if len(neighborhood) else int(index)
        moment = round(chosen * hop / rate, 3)
        if 0 <= moment <= duration and (not beats or moment - beats[-1] > 0.15):
            beats.append(moment)
    result = {
        "source_sha256": digest(root / "audio" / "composition.mp3"),
        "method": "local spectral-flux autocorrelation with transient snapping",
        "bpm": round(bpm, 4),
        "phase": round(phase * hop / rate, 4),
        "beats": beats,
        "metrical_downbeats_verified": False,
        "duration": duration,
    }
    write(root / "edit" / "v2" / "beat-map.json", result)
    return result


def prepare(root: Path) -> dict:
    root = Path(root).resolve()
    master(root)
    analysis = _analysis_audio(root)
    cues = align_lyrics(root)
    beats = beat_map(root, analysis)
    return {
        "status": "REVIEW_REQUIRED",
        "master": str(root / "audio" / "master.wav"),
        "cue_count": len(cues),
        "beat_count": len(beats["beats"]),
        "bpm": beats["bpm"],
        "pronunciation_review": "PENDING",
        "additional_credits": 0,
    }

