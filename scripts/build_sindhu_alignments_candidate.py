from __future__ import annotations

import json
import re
from pathlib import Path

from faster_whisper import WhisperModel
from openjarvis.one_agents.chandan_alignment import align_words, character_alignment

MISSION = Path(r"E:\ONE-SUITE\data\youtube\origin_to_ovation\missions\pv-sindhu-2026-10-26")
MASTER = MISSION / "production" / "master-v1"
SOURCE = MASTER / "narration-george"
DEST = MASTER / "audio"


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def main() -> None:
    if any((DEST / f"chapter-{chapter:02d}.json").exists() for chapter in range(1, 16)):
        raise FileExistsError("Existing alignment checkpoint preserved")
    receipt = json.loads((MASTER / "narration-receipt.json").read_text(encoding="utf-8"))
    scale = float(receipt.get("documentary_pacing_scale") or 1.0)
    model = WhisperModel(r"E:\ONE-SUITE\data\models\faster-whisper-base-en", device="cpu", compute_type="int8", local_files_only=True)
    summary = []
    pending = []
    for chapter in range(1, 16):
        text = (SOURCE / f"chapter-{chapter:02d}.txt").read_text(encoding="utf-8").strip()
        audio = SOURCE / f"chapter-{chapter:02d}.mp3"
        segments, info = model.transcribe(str(audio), language="en", word_timestamps=True, vad_filter=False, beam_size=5)
        measured = []
        for segment in segments:
            for word in segment.words or []:
                measured.append({"word": word.word.strip(), "start": word.start, "end": word.end})
        expected_matches = list(re.finditer(r"\S+", text))
        expected_words = [match.group() for match in expected_matches]
        result = align_words(expected_words, measured, float(info.duration))
        # Fail before writing any chapter if measured timing needs review.
        alignment = character_alignment(text, result, pacing_scale=scale)
        pending.append((DEST / f"chapter-{chapter:02d}.json", {"alignment": alignment}))
        summary.append({"chapter": chapter, "expected_words": len(expected_words),
                        "recognized_words": len(measured), "timing_methods": list(result.methods),
                        "review_reasons": list(result.review_reasons)})
    # Never replace an existing owner's alignment checkpoint implicitly.
    if any(path.exists() for path, _ in pending):
        raise FileExistsError("Existing alignment checkpoint preserved; owner must select a reviewed output destination")
    DEST.mkdir(exist_ok=True)
    for path, payload in pending:
        with path.open("x", encoding="utf-8") as output:
            output.write(json.dumps(payload, indent=2))
    (MISSION / "runtime" / "forced-alignment-receipt.json").write_text(
        json.dumps({"status": "editorial_review_required", "engine": "faster-whisper base.en", "source": "existing George chapter audio",
                    "documentary_pacing_scale": scale, "chapters": summary}, indent=2), encoding="utf-8")
    print(json.dumps({"status": "complete", "chapters": 15, "engine": "faster-whisper base.en"}))


if __name__ == "__main__":
    main()
