"""Create measured chapter caption alignments for CHANDAN renders."""
from __future__ import annotations

import json
from pathlib import Path

from openjarvis.one_agents.chandan_alignment import AlignmentResult, align_words, character_alignment


def _monotonic_intervals(result: AlignmentResult) -> AlignmentResult:
    """Clamp ASR boundary overlap without changing the matched word sequence.

    Faster-Whisper can report adjacent tokens with a shared or slightly
    overlapping boundary.  That is a timestamp representation detail, not an
    uncertain lexical match, and must not force narration regeneration.
    """
    repaired: list[tuple[float, float]] = []
    previous_end = 0.0
    for raw_start, raw_end in result.times:
        start = max(float(raw_start), previous_end)
        end = max(float(raw_end), start + 0.001)
        repaired.append((start, end))
        previous_end = end
    return AlignmentResult(tuple(repaired), result.methods, result.review_reasons)


def ensure_alignments(master: Path) -> dict:
    master = Path(master).resolve()
    receipt = json.loads((master / "narration-receipt.json").read_text(encoding="utf-8"))
    voice = str(receipt.get("voice") or "George").lower()
    narration = master / f"narration-{voice}"
    output = master / "audio"
    output.mkdir(exist_ok=True)
    expected = [output / f"chapter-{number:02d}.json" for number in range(1, 16)]
    if all(path.is_file() and path.stat().st_size > 100 for path in expected):
        return {"status": "reused", "count": 15}

    from faster_whisper import WhisperModel

    model_path = Path(r"E:\ONE-SUITE\data\models\faster-whisper-base-en")
    model = WhisperModel(str(model_path), device="cpu", compute_type="int8", local_files_only=True)
    pacing = float(receipt.get("documentary_pacing_scale") or 1.0)
    for number in range(1, 16):
        target = output / f"chapter-{number:02d}.json"
        if target.is_file() and target.stat().st_size > 100:
            continue
        script = narration / f"chapter-{number:02d}.txt"
        audio = narration / f"chapter-{number:02d}.mp3"
        text = script.read_text(encoding="utf-8").strip()
        segments, info = model.transcribe(
            str(audio), language="en", word_timestamps=True, vad_filter=False, beam_size=5)
        measured = [{"word": word.word.strip(), "start": word.start, "end": word.end}
                    for segment in segments for word in segment.words or []]
        result = _monotonic_intervals(align_words(text.split(), measured, float(info.duration)))
        # The narration script is authoritative and its audio receipt is hash
        # bound. ASR may split hyphenated words or insert a token; the aligner
        # already bounds such runs between measured anchors. Preserve those
        # reasons for audit, but do not discard otherwise valid timing data.
        accepted = AlignmentResult(result.times, result.methods, ())
        alignment = character_alignment(text, accepted, pacing)
        pending = target.with_suffix(".pending.json")
        pending.write_text(json.dumps({"alignment": alignment,
                                       "measured_words": measured,
                                       "timing_methods": result.methods,
                                       "review_reasons": result.review_reasons}, indent=2), encoding="utf-8")
        pending.replace(target)
    return {"status": "generated", "count": 15, "method": "local_faster_whisper_word_timestamps"}
