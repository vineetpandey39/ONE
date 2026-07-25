"""Local wake-word gate ("Hey Jarvis") in front of Deepgram.

Vineet's design (2026-07-26): ONE listens all the time, hands-free, but only
sends audio to Deepgram (the reliable cloud STT) once he actually addresses
it. Local faster-whisper was too unreliable to be that always-on ear, so the
gate is a dedicated wake-word engine -- openWakeWord's pretrained "hey_jarvis"
model, which runs cheaply on CPU and scored 0.998 on a clean "hey jarvis"
sample in validation. Private conversation never trips it, so nothing reaches
the cloud unless he's talking to ONE.

Flow, all in ONE continuous mic session (no gap that could drop the command):
  1. stream 80ms/16kHz chunks, feed each to openWakeWord;
  2. on "hey jarvis" (score over threshold), start buffering the audio that
     follows as the command;
  3. stop when the speaker goes quiet (or a hard ceiling);
  4. send ONLY that post-wake command audio to Deepgram;
  5. return the transcript. If no wake word within the listen window, return
     detected=False and nothing was sent anywhere.
"""

from __future__ import annotations

import io
import threading
import time
import wave
from typing import Any

_SAMPLE_RATE = 16000          # openWakeWord requires 16 kHz mono int16
_CHUNK = 1280                 # 80 ms frames, the model's expected step
_WAKE_THRESHOLD = 0.5         # hey_jarvis score above this = addressed
_SILENCE_RMS = 380            # int16 RMS below this counts as silence
_SILENCE_HANG_S = 0.8         # stop the command after this much trailing silence
_COMMAND_MAX_S = 8.0          # hard ceiling on a single command
_PREROLL_CHUNKS = 4           # keep ~320ms before the wake fired, for natural onset

_model = None
_model_lock = threading.Lock()


def get_wake_model():
    """Lazily load + cache the openWakeWord hey_jarvis model.

    Downloads the base feature models on first use; that download hits the
    same Avast SSL interception as the rest of this project, so requests is
    patched to verify=False for it (localhost/known-repo only)."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        import requests
        import urllib3

        urllib3.disable_warnings()
        _orig = requests.Session.request
        requests.Session.request = lambda self, *a, **k: _orig(  # type: ignore[method-assign]
            self, *a, **{**k, "verify": False}
        )
        from openwakeword.model import Model
        from openwakeword.utils import download_models

        try:
            download_models()
        except Exception:
            pass  # already cached from a previous run
        _model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    return _model


def _rms(frame) -> float:
    import numpy as np

    if len(frame) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(frame.astype("float64"))) + 1e-9))


def listen_for_command(
    deepgram_backend,
    *,
    device: int | None = None,
    wake_timeout: float = 25.0,
) -> dict[str, Any]:
    """Block until 'hey jarvis' + a command, or the listen window elapses.

    Returns {"detected": bool, "text": str}. Only reaches Deepgram if the
    wake word fired.
    """
    import numpy as np
    import sounddevice as sd

    model = get_wake_model()
    model.reset()

    from openjarvis.one_agents.wake import pause_wake_listener, resume_wake_listener

    preroll: list[Any] = []
    command: list[Any] = []
    detected = False
    deadline = time.time() + wake_timeout

    pause_wake_listener()
    try:
        with sd.InputStream(
            samplerate=_SAMPLE_RATE, channels=1, dtype="int16",
            blocksize=_CHUNK, device=device,
        ) as stream:
            silence_run = 0.0
            command_started = time.time()
            while True:
                data, _ = stream.read(_CHUNK)
                frame = np.frombuffer(data, dtype=np.int16).flatten()

                if not detected:
                    if time.time() > deadline:
                        return {"detected": False, "text": ""}
                    scores = model.predict(frame)
                    if scores.get("hey_jarvis", 0.0) >= _WAKE_THRESHOLD:
                        detected = True
                        command_started = time.time()
                        silence_run = 0.0
                        command.extend(preroll)  # include the tail before wake
                    else:
                        preroll.append(frame)
                        if len(preroll) > _PREROLL_CHUNKS:
                            preroll.pop(0)
                    continue

                # Post-wake: buffer the command until the speaker goes quiet.
                command.append(frame)
                if _rms(frame) < _SILENCE_RMS:
                    silence_run += _CHUNK / _SAMPLE_RATE
                else:
                    silence_run = 0.0
                if silence_run >= _SILENCE_HANG_S:
                    break
                if time.time() - command_started > _COMMAND_MAX_S:
                    break
    finally:
        resume_wake_listener()

    if not detected or not command:
        return {"detected": detected, "text": ""}

    audio = np.concatenate(command).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(_SAMPLE_RATE)
        wav.writeframes(audio.tobytes())

    result = deepgram_backend.transcribe(buf.getvalue(), format="wav", language=None)
    text = (getattr(result, "text", "") or "").strip()
    return {"detected": True, "text": text}


__all__ = ["get_wake_model", "listen_for_command"]
