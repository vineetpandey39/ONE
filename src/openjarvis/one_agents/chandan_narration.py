"""Durable Bill/George narration generation for Origin to Ovation.

The old preproduction code copied a script from a previous mission directory.
Mission cleanup therefore removed the only narration implementation.  This
module is repository-owned and uses LAO's vault-backed ElevenLabs action while
preserving a hash-bound receipt for every paid chapter.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=3600)


def _duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True, timeout=120)
    value = float(result.stdout.strip())
    if value <= 0:
        raise ValueError(f"Narration audio has no measurable duration: {path}")
    return value


def generate(master: Path, *, voice_id: str, voice_name: str, title: str, mission_id: str) -> dict:
    from openjarvis.one_agents.origin_to_ovation import ROOT, read, write
    from openjarvis.one_agents.planexium_adapters import LaoDraft
    from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool

    master = Path(master).resolve()
    plan = read(master / "shot-plan.json")
    if len(plan) != 75 or len({shot["shot_id"] for shot in plan}) != 75:
        raise ValueError("Narration requires the complete unique 75-shot plan")
    mission = master.parents[1]
    if mission.name != mission_id or not master.is_relative_to(mission):
        raise ValueError("Narration master is outside its mission")
    config = read(ROOT / "runtime-config.json")
    provider = LaoDraft(LaoOrchestratorTool(), config.get("lao_folder_id"),
                        tuple(Path(p) for p in config["artifact_roots"]))
    folder = master / f"narration-{voice_name.lower()}"
    folder.mkdir(parents=True, exist_ok=True)
    provider_root = mission / "runtime" / "providers"
    chapter_rows = []
    for chapter in range(1, 16):
        shots = [shot for shot in plan if int(shot["chapter"]) == chapter]
        if len(shots) != 5:
            raise ValueError(f"Chapter {chapter} must contain exactly five narration shots")
        text = " ".join(str(shot["narration"]).strip() for shot in shots).strip()
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        script = folder / f"chapter-{chapter:02d}.txt"
        audio = folder / f"chapter-{chapter:02d}.mp3"
        receipt = folder / f"chapter-{chapter:02d}.json"
        script.write_text(text, encoding="utf-8")
        if receipt.is_file() and audio.is_file():
            saved = read(receipt)
            if saved.get("text_sha256") != text_hash or saved.get("audio_sha256") != _sha(audio):
                raise ValueError(f"Chapter {chapter} narration checkpoint differs; targeted repair required")
        else:
            steps = [{"action": "synthesize_elevenlabs", "args": {
                "text": text, "voice_id": voice_id, "dest_dir": str(folder),
                "filename": audio.name, "split_on_timecodes": False,
                "model_id": "eleven_multilingual_v2", "stability": 0.50,
                "similarity_boost": 0.75, "style": 0.0}, "as": "narration"}]
            outputs, job_id = provider.run(
                f"Origin to Ovation - {mission_id} - narration chapter {chapter:02d}",
                steps, {}, provider_root / f"narration-chapter-{chapter:02d}.json", timeout=1800)
            if not audio.is_file() or audio.stat().st_size < 1000:
                raise FileNotFoundError(f"LAO narration artifact missing for chapter {chapter}")
            write(receipt, {"status": "completed", "chapter": chapter, "voice": voice_name,
                            "voice_id": voice_id, "provider_job": job_id,
                            "text_sha256": text_hash, "audio_sha256": _sha(audio)})
        chapter_rows.append({"chapter": chapter, "text": text, "audio": str(audio),
                             "seconds": _duration(audio), "text_sha256": text_hash,
                             "audio_sha256": _sha(audio)})

    concat = folder / "concat.txt"
    concat.write_text("\n".join("file '" + Path(row["audio"]).as_posix().replace("'", "'\\''") + "'"
                                 for row in chapter_rows) + "\n", encoding="utf-8")
    master_audio = master / f"{mission_id}-{voice_name.lower()}-narration-master.wav"
    pending = master_audio.with_suffix(".pending.wav")
    _run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
          "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(pending)])
    pending.replace(master_audio)
    measured_total = _duration(master_audio)
    chapter_total = sum(row["seconds"] for row in chapter_rows)
    scale = measured_total / chapter_total
    cursor = 0.0
    timed = []
    for row in chapter_rows:
        shots = [shot for shot in plan if int(shot["chapter"]) == row["chapter"]]
        chapter_seconds = row["seconds"] * scale
        weights = [max(1, len(str(shot["narration"]).split())) for shot in shots]
        weight_total = sum(weights)
        for index, (shot, weight) in enumerate(zip(shots, weights)):
            duration = chapter_seconds * weight / weight_total
            end = measured_total if row["chapter"] == 15 and index == 4 else cursor + duration
            timed.append({**shot, "start_seconds": cursor, "end_seconds": end,
                          "duration_seconds": end - cursor})
            cursor = end
    write(master / "timed-shot-plan.json", timed)
    receipt = {"status": "completed", "title": title, "mission_id": mission_id,
               "voice": voice_name, "voice_id": voice_id,
               "documentary_pacing_scale": 1.0, "chapters": chapter_rows,
               "master": str(master_audio), "master_sha256": _sha(master_audio),
               "duration_seconds": measured_total}
    write(master / "narration-receipt.json", receipt)
    return receipt
