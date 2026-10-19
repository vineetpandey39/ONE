"""Post-LYRA YouTube completion owned by Floor 12's ECHO worker.

ARES stops after SEO and thumbnail packaging.  This module creates the timed
subtitle track (Hindi or English, as the video is spoken) from FABULA's measured narration, backfills requested
metadata languages, and finishes the existing private upload (captions and the
channel comment).  Pinning is explicitly handed to Studio UI because the
YouTube Data API can create a comment but cannot pin it.
"""
from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from openjarvis.one_agents import youtube_publish, youtube_seo

WHISPER_MODEL = Path(os.environ.get("ONE_SUBTITLE_WHISPER_MODEL") or
                     r"E:\ONE-Suite\data\model_cache\huggingface\hub\models--Systran--faster-whisper-small"
                     r"\snapshots\536b0662742c02347bc0e980a01041f333bce120")


def _stamp(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def spoken_language(pkg: dict[str, Any]) -> str:
    """The language Sonia speaks in this video: hi for a Hinglish story, en for one from outside India."""
    return str((pkg.get("upload") or {}).get("defaultAudioLanguage") or "hi")


def _caption_chunks(text: str, *, max_words: int = 9, max_chars: int = 72) -> list[str]:
    """Split narration into television-sized captions, preferably at punctuation.

    A scene used to become one 30-40 second SRT cue containing an entire
    paragraph. YouTube rendered that as a large wall of text over the picture.
    Keep each cue to roughly two short lines while preserving every word.
    """
    words = re.sub(r"\s+", " ", text).strip().split()
    chunks: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and (len(current) >= max_words or len(candidate) > max_chars):
            chunks.append(" ".join(current))
            current = []
        current.append(word)
        if len(current) >= 4 and re.search(r"[.!?][\"']?$", word):
            chunks.append(" ".join(current))
            current = []
    if current:
        chunks.append(" ".join(current))
    return chunks or [""]


def _timed_chunks(text: str, start: float, end: float) -> list[tuple[float, float, str]]:
    """Distribute compact captions over the measured voice segment.

    Word counts approximate speech duration better than equal-sized time
    slices. Boundaries remain contiguous and the final cue ends exactly at the
    FABULA segment boundary, so subtitles cannot drift into the next scene.
    """
    chunks = _caption_chunks(text)
    weights = [max(1, len(chunk.split())) for chunk in chunks]
    total = sum(weights)
    duration = max(0.001, end - start)
    cursor = start
    timed: list[tuple[float, float, str]] = []
    for index, (chunk, weight) in enumerate(zip(chunks, weights)):
        cue_end = end if index == len(chunks) - 1 else cursor + duration * weight / total
        timed.append((cursor, max(cursor + 0.001, cue_end), chunk))
        cursor = cue_end
    return timed


def _word_key(word: str) -> str:
    return "".join(re.findall(r"[\w]+", word.casefold(), re.UNICODE))


def _force_align(original_text: str, heard: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    """Put approved script words on ASR word times without accepting ASR spelling."""
    original = re.sub(r"\s+", " ", original_text).strip().split()
    if not original or not heard:
        return []
    mapping: list[tuple[float, float] | None] = [None] * len(original)
    matcher = SequenceMatcher(None, [_word_key(w) for w in original], [_word_key(w[2]) for w in heard], autojunk=False)
    for kind, a0, a1, b0, b1 in matcher.get_opcodes():
        if kind == "equal":
            for ai, bi in zip(range(a0, a1), range(b0, b1)):
                mapping[ai] = (heard[bi][0], heard[bi][1])
        elif kind == "replace" and b1 > b0:
            for offset, ai in enumerate(range(a0, a1)):
                bi = b0 + min(b1 - b0 - 1, int(offset * (b1 - b0) / max(1, a1 - a0)))
                mapping[ai] = (heard[bi][0], heard[bi][1])
    index = 0
    while index < len(mapping):
        if mapping[index] is not None:
            index += 1
            continue
        end = index
        while end < len(mapping) and mapping[end] is None:
            end += 1
        left = mapping[index - 1][1] if index else heard[0][0]
        right = mapping[end][0] if end < len(mapping) else heard[-1][1]
        step = max(0.04, (right - left) / max(1, end - index))
        for pos in range(index, end):
            start = left + (pos - index) * step
            mapping[pos] = (start, min(right, start + step))
        index = end
    words = [(mapping[i][0], mapping[i][1], word) for i, word in enumerate(original)]
    chunks: list[list[tuple[float, float, str]]] = []
    current: list[tuple[float, float, str]] = []
    for item in words:
        candidate = " ".join([x[2] for x in current] + [item[2]])
        if current and (len(current) >= 9 or len(candidate) > 72):
            chunks.append(current)
            current = []
        current.append(item)
        if len(current) >= 4 and re.search(r"[.!?][\"']?$", item[2]):
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return [(chunk[0][0], chunk[-1][1], " ".join(x[2] for x in chunk)) for chunk in chunks]


def _audio_aligned_chunks(text: str, audio: Path, language: str) -> list[tuple[float, float, str]]:
    from faster_whisper import WhisperModel

    device = os.environ.get("ONE_SUBTITLE_WHISPER_DEVICE", "cpu")
    model = WhisperModel(str(WHISPER_MODEL), device=device, compute_type="float16" if device == "cuda" else "int8")
    # Whisper takes a bare language ("en"); YouTube's tag may carry a region ("en-US").
    segments, _info = model.transcribe(str(audio), language=language.split("-")[0], beam_size=5, word_timestamps=True,
                                       vad_filter=True, condition_on_previous_text=False)
    heard = [(float(word.start), float(word.end), word.word.strip())
             for segment in segments for word in (segment.words or []) if word.word.strip()]
    return _force_align(text, heard)


def build_srt(package_path: Path) -> Path:
    """Build compact captions; use audio word times and fall back to measured scene times."""
    pkg = json.loads(Path(package_path).read_text(encoding="utf-8"))
    plan_path = Path(pkg["source_plan"])
    record = (json.loads(plan_path.read_text(encoding="utf-8")) or [{}])[0]
    cues = youtube_seo.script_cues(record.get("full_script", ""))
    manifest_path = plan_path.parent / "narration" / "narration.segments.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    segments = manifest.get("segments", manifest)
    if len(cues) != len(segments):
        raise RuntimeError(f"subtitle cue mismatch: {len(cues)} script scenes vs {len(segments)} narration segments")
    out = plan_path.parent / "subtitles" / f"{spoken_language(pkg)}.srt"
    alignment = out.with_suffix(".alignment.json")
    audio = plan_path.parent / "edit" / "narration.m4a"
    # A completed caption checkpoint is deterministic for a fixed narration
    # and script. Re-running Whisper on the same 10+ minute track delayed the
    # final upload for several minutes on every ECHO retry. Reuse the SRT only
    # when both its receipt and source audio exist and neither source is newer.
    if out.is_file() and alignment.is_file() and audio.is_file():
        source_mtime = max(audio.stat().st_mtime, plan_path.stat().st_mtime,
                           manifest_path.stat().st_mtime)
        if out.stat().st_mtime >= source_mtime and alignment.stat().st_mtime >= source_mtime:
            return out
    out.parent.mkdir(parents=True, exist_ok=True)
    full_text = " ".join(re.sub(r"\s+", " ", cue[2]).strip() for cue in cues)
    aligned: list[tuple[float, float, str]] = []
    if audio.is_file() and WHISPER_MODEL.is_dir():
        try:
            aligned = _audio_aligned_chunks(full_text, audio, spoken_language(pkg))
        except Exception:  # noqa: BLE001 - measured segment timing remains a safe fallback
            aligned = []
    blocks = []
    index = 1
    source = "whisper_word_alignment" if aligned else "measured_segment_fallback"
    timed = aligned
    if not timed:
        timed = []
        for (_, _, text), segment in zip(cues, segments):
            clean = re.sub(r"\s+", " ", text).strip()
            timed.extend(_timed_chunks(clean, float(segment["start"]), float(segment["end"])))
    for start, end, caption in timed:
        blocks.append(f"{index}\n{_stamp(start)} --> {_stamp(end)}\n{caption}")
        index += 1
    out.write_text("\n\n".join(blocks) + "\n", encoding="utf-8-sig")
    alignment.write_text(json.dumps({
        "source": source, "audio": str(audio), "cues": len(blocks),
        "first_start": timed[0][0] if timed else None, "last_end": timed[-1][1] if timed else None,
    }, indent=2), encoding="utf-8")
    return out


def complete(package_path: Path, *, localization_budget: float = 3600) -> dict[str, Any]:
    package_path = Path(package_path)
    pkg = json.loads(package_path.read_text(encoding="utf-8"))
    requested = youtube_publish.required_locales(pkg)
    added, failed = youtube_publish.ensure_localizations(
        package_path, requested, budget_seconds=localization_budget)
    subtitle = build_srt(package_path)
    uploader = youtube_publish._load("youtube_api_upload")
    policy = youtube_publish.load_policy()
    report = uploader.run(package_path, video=None, thumbnail=None,
                          synthetic=policy.get("synthetic_disclosure", "yes"),
                          execute=True, finish=True, post_comment=True,
                          caption=subtitle, caption_language=spoken_language(pkg))
    return {"status": "distribution_complete", "subtitle": str(subtitle),
            "localizations_added": sorted(added), "localizations_failed": failed,
            "youtube": report,
            "pin_comment_in_studio": bool((pkg.get("pinned_comment_draft") or "").strip())}


build_hindi_srt = build_srt  # the original name, kept for callers that still use it
