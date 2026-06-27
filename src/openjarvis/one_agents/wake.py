"""Local clap + wake-phrase listener for ONE."""

from __future__ import annotations

import io
import json
import math
import os
import re
import sqlite3
import threading
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


def _home() -> Path:
    return Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))


def _events_db() -> sqlite3.Connection:
    path = _home() / "wake_events.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE IF NOT EXISTS wake_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        transcript TEXT NOT NULL,
        recognized INTEGER NOT NULL,
        summary TEXT NOT NULL
        )"""
    )
    db.commit()
    return db


def recent_wake_events(limit: int = 10) -> list[dict[str, Any]]:
    with _events_db() as db:
        rows = db.execute("SELECT * FROM wake_events ORDER BY id DESC LIMIT ?", (max(1, min(limit, 50)),)).fetchall()
    return [dict(row) for row in rows]


def _save_event(transcript: str, recognized: bool, summary: str) -> None:
    with _events_db() as db:
        db.execute(
            "INSERT INTO wake_events (created_at, transcript, recognized, summary) VALUES (?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), transcript[:1000], int(recognized), summary[:5000]),
        )


def _daily_summary() -> str:
    local_now = datetime.now().astimezone()
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    jobs = []
    queue_path = _home() / "agent_queue.db"
    if queue_path.exists():
        with sqlite3.connect(queue_path) as db:
            db.row_factory = sqlite3.Row
            for row in db.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall():
                try:
                    created = datetime.fromisoformat(row["created_at"]).astimezone()
                except ValueError:
                    continue
                if created >= day_start:
                    jobs.append(dict(row))
    completed = [job for job in jobs if job["status"] == "completed"]
    failed = [job for job in jobs if job["status"] == "failed"]
    active = [job for job in jobs if job["status"] in {"queued", "running"}]
    agents = sorted({job["agent_id"].upper() for job in completed})
    details = []
    alfa = next((job for job in completed if job["agent_id"] == "alfa" and job.get("result")), None)
    if alfa:
        try:
            result = json.loads(alfa["result"])
            details.append(
                f"ALFA scanned {result.get('scanned', 0)} public posts and retained {result.get('qualified', 0)} qualified lead, "
                f"with an estimated pipeline of {result.get('estimated_usd_low', 0)} to {result.get('estimated_usd_high', 0)} US dollars."
            )
        except json.JSONDecodeError:
            pass
    try:
        from openjarvis.one_agents.obsidian import obsidian_status

        memories = obsidian_status().get("notes", 0)
    except Exception:
        memories = 0
    greeting = "Good morning" if local_now.hour < 12 else "Good afternoon" if local_now.hour < 17 else "Good evening"
    agent_text = ", ".join(agents) if agents else "no agents"
    summary = (
        f"{greeting}, Vineet. Welcome home. Since the start of today, I completed {len(completed)} mission"
        f"{'s' if len(completed) != 1 else ''} across {agent_text}. "
        f"There are {len(active)} active and {len(failed)} failed missions. "
        + " ".join(details)
        + f" Your permanent memory currently contains {memories} notes."
    )
    if failed:
        failed_agents = ", ".join(sorted({job["agent_id"].upper() for job in failed}))
        summary += f" Attention is required for {failed_agents}."
    return " ".join(summary.split())


def _speak(text: str) -> None:
    """Notify locally; the open ONE cockpit voices the persisted wake event."""
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_OK)
    except Exception:
        pass


def _matches_wake_phrase(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    normalized = " ".join(normalized.split())
    wake = "wake up one" in normalized or "wake up 1" in normalized
    home = any(phrase in normalized for phrase in ("daddy s home", "daddys home", "daddy is home", "daddy home"))
    return wake and home


def _preferred_device(sd) -> int | None:
    configured = os.environ.get("ONE_WAKE_DEVICE", "").strip()
    if configured:
        return int(configured)
    # A USB device with an unrecognized audio-terminal descriptor can raise
    # PortAudioError ("GetNameFromCategory: usbTerminalGUID = ...") when its
    # info is queried, which would otherwise crash this whole lookup even
    # though we only want the Realtek mic. Query one index at a time and
    # skip whichever device errors.
    try:
        count = len(sd.query_devices())
    except Exception:
        count = 0
    for index in range(count):
        try:
            device = sd.query_devices(index)
        except Exception:
            continue
        if device.get("max_input_channels", 0) < 1 or "realtek" not in str(device.get("name", "")).lower():
            continue
        try:
            host_name = sd.query_hostapis(device["hostapi"])["name"]
        except Exception:
            continue
        if "WASAPI" in host_name:
            return index
    try:
        return int(sd.default.device[0])
    except Exception:
        return None


def _load_wake_whisper_model():
    """Load ONE's speech-to-text model, preferring the GPU if available.

    Defaults to ``large-v3-turbo`` on CUDA/float16 — multilingual (keeps
    Hindi/Hinglish support, unlike the English-only distil-whisper
    checkpoints) and the closest faster-whisper currently ships to "best in
    market" while still running comfortably on a single consumer GPU. If
    CUDA/cuDNN aren't actually usable on this machine, loading raises here
    rather than mid-listen, so we catch it and fall back to the original
    CPU/base/int8 setup — the wake listener keeps working either way.
    All three knobs are env-overridable without a code change.
    """
    from openjarvis.speech.faster_whisper import FasterWhisperBackend

    model_size = os.environ.get("ONE_WHISPER_MODEL", "large-v3-turbo")
    device = os.environ.get("ONE_WHISPER_DEVICE", "cuda")
    compute_type = os.environ.get("ONE_WHISPER_COMPUTE_TYPE", "float16")
    try:
        backend = FasterWhisperBackend(model_size=model_size, device=device, compute_type=compute_type)
        backend.warmup()
        print(
            f"ONE wake listener: loaded Whisper '{model_size}' on {device} ({compute_type}).",
            flush=True,
        )
        return backend
    except Exception as exc:
        print(
            f"ONE wake listener: could not load '{model_size}' on {device} ({exc}); "
            "falling back to the CPU 'base' model. If you have an NVIDIA GPU, install "
            "cuBLAS for CUDA 12 and cuDNN 9 to use the upgraded model — see "
            "ONE Vault/Docs/Whisper Capabilities.md.",
            flush=True,
        )
        fallback = FasterWhisperBackend(model_size="base", device="cpu", compute_type="int8")
        fallback.warmup()
        return fallback


def run_wake_listener() -> None:
    if os.environ.get("ONE_WAKE_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        return
    import sounddevice as sd

    device = _preferred_device(sd)
    info = sd.query_devices(device, "input")
    sample_rate = int(info.get("default_samplerate", 48000))
    blocksize = max(512, int(sample_rate * 0.05))
    threshold = float(os.environ.get("ONE_CLAP_THRESHOLD", "0.22"))
    phrase_seconds = float(os.environ.get("ONE_WAKE_WINDOW_SECONDS", "6.5"))
    model = None
    noise_floor = 0.01
    collecting: list[np.ndarray] | None = None
    collect_started = 0.0
    cooldown_until = 0.0
    print(f"ONE wake listener online: {info['name']} (device {device})", flush=True)

    while True:
        if _pause_path().exists():
            _stream_released.set()
            _released_path().touch()
            time.sleep(0.05)
            continue
        _stream_released.clear()
        _released_path().unlink(missing_ok=True)
        with sd.InputStream(device=device, samplerate=sample_rate, channels=1, dtype="float32", blocksize=blocksize) as stream:
          while not _pause_path().exists():
            frames, overflowed = stream.read(blocksize)
            if overflowed:
                continue
            mono = frames[:, 0].copy()
            peak = float(np.max(np.abs(mono)))
            rms = float(math.sqrt(float(np.mean(mono * mono)) + 1e-12))
            now = time.monotonic()
            if collecting is None:
                noise_floor = noise_floor * 0.98 + min(rms, 0.08) * 0.02
                clap_level = max(threshold, noise_floor * 8)
                crest = peak / max(rms, 0.001)
                if now >= cooldown_until and peak >= clap_level and crest >= 3.0:
                    collecting = []
                    collect_started = now
                    print(f"ONE clap detected (peak={peak:.2f}, noise={noise_floor:.3f})", flush=True)
                continue
            collecting.append(mono)
            if now - collect_started < phrase_seconds:
                continue
            audio = np.concatenate(collecting)
            collecting = None
            cooldown_until = now + 5
            pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes(pcm.tobytes())
            if model is None:
                model = _load_wake_whisper_model()
            try:
                result = model.transcribe(output.getvalue(), format="wav", language=None)
                transcript = result.text.strip()
            except Exception as exc:
                print(f"ONE wake transcription failed: {exc}", flush=True)
                continue
            recognized = _matches_wake_phrase(transcript)
            summary = _daily_summary() if recognized else ""
            _save_event(transcript, recognized, summary)
            print(f"ONE wake heard: {transcript!r}; recognized={recognized}", flush=True)
            if recognized:
                try:
                    from openjarvis.one_agents.obsidian import remember_exchange

                    remember_exchange(transcript, summary)
                except Exception:
                    pass
                _speak(summary)
        _stream_released.set()
        _released_path().touch()


def start_wake_listener() -> threading.Thread | None:
    if os.environ.get("ONE_WAKE_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        return None
    thread = threading.Thread(target=run_wake_listener, name="one-wake-listener", daemon=True)
    thread.start()
    return thread
_capture_paused = threading.Event()
_stream_released = threading.Event()


def _pause_path() -> Path:
    return _home() / "one-microphone.pause"


def _released_path() -> Path:
    return _home() / "one-microphone.released"


def pause_wake_listener(timeout: float = 2.0) -> bool:
    """Temporarily release the input device for an explicit voice command."""
    _capture_paused.set()
    pause_path = _pause_path()
    pause_path.parent.mkdir(parents=True, exist_ok=True)
    _released_path().unlink(missing_ok=True)
    pause_path.touch()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _released_path().exists():
            return True
        time.sleep(0.05)
    return _stream_released.wait(0.1)


def resume_wake_listener() -> None:
    _capture_paused.clear()
    _pause_path().unlink(missing_ok=True)
    _released_path().unlink(missing_ok=True)
