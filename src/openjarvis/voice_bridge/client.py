"""Deepgram Voice Agent WebSocket client.

Connects ONE, as an outbound client, to `wss://agent.deepgram.com/v1/agent/converse`
(Flux STT + a managed LLM + Aura-2 TTS, all over one socket) so voice
conversations feel like the Deepgram playground demo instead of ONE's
existing multi-hop REST pipeline. Runs as an asyncio task inside the FastAPI
app, started/stopped on demand from /v1/voice-bridge/* in server/routes.py --
never as an always-on daemon, since Deepgram bills per connected minute.

Protocol confirmed live against Deepgram's docs (2026-08-09):
- Welcome -> Settings -> SettingsApplied -> stream binary PCM both ways.
- agent.think.functions entries with no `endpoint` are executed client-side:
  the server sends FunctionCallRequest and expects a FunctionCallResponse
  back on the same socket (see voice_bridge/functions.py).
- UserStartedSpeaking means the user is interrupting -- drop whatever's
  queued for playback immediately (barge-in).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import time
from typing import Any, Dict, Optional

import numpy as np
import websockets

from openjarvis.one_agents.wake import pause_wake_listener, resume_wake_listener
from openjarvis.voice_bridge.functions import deepgram_function_schemas, execute_function
from openjarvis.voice_bridge.redact import redact

logger = logging.getLogger("openjarvis.voice_bridge")

_AGENT_WS_URL = "wss://agent.deepgram.com/v1/agent/converse"
_SAMPLE_RATE_IN = 16000
_SAMPLE_RATE_OUT = 24000
_BLOCK_SECONDS = 0.02

# Deliberately generic: no name, no household details -- this prompt leaves
# the machine and is read by Deepgram's managed cloud LLM. The full,
# detailed local persona (data/config.toml's default_system_prompt) is
# unaffected and keeps being used everywhere else.
_GENERIC_PROMPT = (
    "You are ONE, a private voice assistant. Always address the user as "
    "'Sir' -- never by name, never guess a name. Be calm, precise, warm, "
    "and concise: short spoken sentences, no filler, no corporate hedging. "
    "You may call get_current_time, agent_stats, or recall_memory when "
    "asked about the time, how the agents are doing, or a past "
    "conversation -- never invent an answer to those without calling the "
    "function first. For anything else, just answer naturally; you have no "
    "other tools available in this conversation."
)


class VoiceBridgeSession:
    """One live Deepgram Voice Agent conversation. Not reusable -- create a
    fresh instance per start/stop cycle."""

    def __init__(
        self,
        *,
        speak_model: str = "aura-2-thalia-en",
        think_model: str = "claude-haiku-4-5",
        silence_timeout_seconds: float = 90.0,
    ) -> None:
        self.speak_model = speak_model
        self.think_model = think_model
        self.silence_timeout_seconds = silence_timeout_seconds
        self.state = "idle"  # idle | listening | thinking | speaking
        self.error: Optional[str] = None
        self._ws: Any = None
        self._stop = asyncio.Event()
        self._last_activity = time.monotonic()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Mic-in: producer (PortAudio thread) -> consumer (asyncio task).
        # asyncio.Queue is safe here because the producer only ever touches
        # it via call_soon_threadsafe, which hops onto the loop thread first.
        self._audio_in_queue: "asyncio.Queue[bytes]" = asyncio.Queue(maxsize=64)
        # Speaker-out: producer (asyncio task) -> consumer (PortAudio
        # thread). asyncio.Queue is NOT safe to read from a non-loop thread,
        # so this is a plain thread-safe stdlib queue instead.
        self._audio_out_queue: "queue.SimpleQueue[bytes]" = queue.SimpleQueue()

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    # -- sounddevice callbacks (run on PortAudio's own thread, not asyncio) --

    def _mic_callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        try:
            pcm = np.clip(indata[:, 0] * 32767, -32768, 32767).astype(np.int16).tobytes()
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._queue_mic_chunk, pcm)
        except Exception:
            logger.debug("voice bridge mic callback error", exc_info=True)

    def _queue_mic_chunk(self, pcm: bytes) -> None:
        try:
            self._audio_in_queue.put_nowait(pcm)
        except asyncio.QueueFull:
            pass  # drop under backpressure rather than block the audio thread

    def _play_callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        try:
            needed = frames * 2  # 2 bytes/sample, mono int16
            chunk = b""
            while len(chunk) < needed:
                try:
                    chunk += self._audio_out_queue.get_nowait()
                except queue.Empty:
                    break
            if not chunk:
                outdata.fill(0)
                return
            if len(chunk) < needed:
                chunk += b"\x00" * (needed - len(chunk))
            elif len(chunk) > needed:
                self._audio_out_queue.put(chunk[needed:])
                chunk = chunk[:needed]
            outdata[:] = np.frombuffer(chunk, dtype=np.int16).reshape(-1, 1)
        except Exception:
            logger.debug("voice bridge playback callback error", exc_info=True)
            outdata.fill(0)

    def _drain_playback(self) -> None:
        """Barge-in: the user started talking, stop whatever ONE was saying."""
        while True:
            try:
                self._audio_out_queue.get_nowait()
            except queue.Empty:
                break

    # -- main session --

    async def run(self) -> None:
        import sounddevice as sd

        self._loop = asyncio.get_running_loop()
        api_key = os.environ.get("DEEPGRAM_API_KEY", "")
        if not api_key:
            self.error = "DEEPGRAM_API_KEY is not set."
            raise RuntimeError(self.error)

        # Redaction is not optional safety here -- confirm it actually
        # imports and runs before ever opening the socket. Fail closed.
        redact("startup self-check")

        pause_wake_listener()
        try:
            async with websockets.connect(
                _AGENT_WS_URL,
                additional_headers={"Authorization": f"Token {api_key}"},
                max_size=None,
            ) as ws:
                self._ws = ws
                await self._handshake(ws)
                self._touch()

                with sd.InputStream(
                    samplerate=_SAMPLE_RATE_IN,
                    channels=1,
                    dtype="float32",
                    blocksize=int(_SAMPLE_RATE_IN * _BLOCK_SECONDS),
                    callback=self._mic_callback,
                ), sd.OutputStream(
                    samplerate=_SAMPLE_RATE_OUT,
                    channels=1,
                    dtype="int16",
                    blocksize=int(_SAMPLE_RATE_OUT * _BLOCK_SECONDS),
                    callback=self._play_callback,
                ):
                    await asyncio.gather(
                        self._send_audio_loop(ws),
                        self._receive_loop(ws),
                        self._idle_watchdog(),
                        return_exceptions=True,
                    )
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            logger.warning("voice bridge session ended with error: %s", exc)
        finally:
            self.state = "idle"
            self._ws = None
            resume_wake_listener()

    async def _handshake(self, ws: Any) -> None:
        welcome = json.loads(await ws.recv())
        if welcome.get("type") != "Welcome":
            raise RuntimeError(f"Unexpected first message from Deepgram: {welcome}")

        settings = {
            "type": "Settings",
            "audio": {
                "input": {"encoding": "linear16", "sample_rate": _SAMPLE_RATE_IN},
                "output": {"encoding": "linear16", "sample_rate": _SAMPLE_RATE_OUT, "container": "none"},
            },
            "agent": {
                "listen": {
                    "provider": {"type": "deepgram", "model": "flux-general-en", "version": "v2"}
                },
                "think": {
                    "provider": {"type": "anthropic", "model": self.think_model, "temperature": 0.5},
                    "prompt": redact(_GENERIC_PROMPT),
                    "functions": deepgram_function_schemas(),
                },
                "speak": {"provider": {"type": "deepgram", "model": self.speak_model}},
            },
        }
        await ws.send(json.dumps(settings))
        applied = json.loads(await ws.recv())
        if applied.get("type") != "SettingsApplied":
            raise RuntimeError(f"Deepgram rejected Settings: {applied}")
        self.state = "listening"

    async def _send_audio_loop(self, ws: Any) -> None:
        while not self._stop.is_set():
            pcm = await self._audio_in_queue.get()
            await ws.send(pcm)

    async def _receive_loop(self, ws: Any) -> None:
        try:
            async for message in ws:
                if self._stop.is_set():
                    break
                self._touch()
                if isinstance(message, (bytes, bytearray)):
                    self._audio_out_queue.put(bytes(message))
                    self.state = "speaking"
                    continue
                await self._handle_event(ws, message)
        finally:
            self._stop.set()

    async def _handle_event(self, ws: Any, raw: str) -> None:
        try:
            event: Dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            return
        etype = event.get("type")
        if etype == "UserStartedSpeaking":
            self.state = "listening"
            self._drain_playback()
        elif etype == "AgentThinking":
            self.state = "thinking"
        elif etype == "AgentStartedSpeaking":
            self.state = "speaking"
        elif etype == "AgentAudioDone":
            self.state = "listening"
        elif etype == "FunctionCallRequest":
            await self._handle_function_calls(ws, event)
        elif etype in ("Error", "Warning"):
            logger.warning("voice bridge: Deepgram %s: %s", etype, event)

    async def _handle_function_calls(self, ws: Any, event: Dict[str, Any]) -> None:
        for call in event.get("functions", []):
            if call.get("client_side") is False:
                continue  # server handled it internally, no action needed
            name = call.get("name", "")
            try:
                arguments = json.loads(call.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            content = await self._loop.run_in_executor(None, execute_function, name, arguments)
            await ws.send(
                json.dumps(
                    {
                        "type": "FunctionCallResponse",
                        "id": call.get("id", ""),
                        "name": name,
                        "content": content,
                    }
                )
            )

    async def _idle_watchdog(self) -> None:
        """Auto-disconnect after a period of silence -- Deepgram bills per
        connected minute, so an idle session left open is wasted credit."""
        while not self._stop.is_set():
            await asyncio.sleep(2.0)
            if time.monotonic() - self._last_activity > self.silence_timeout_seconds:
                logger.info(
                    "voice bridge: idle for %.0fs, auto-disconnecting to save credit.",
                    self.silence_timeout_seconds,
                )
                self._stop.set()
                if self._ws is not None:
                    await self._ws.close()
                break

    def request_stop(self) -> None:
        self._stop.set()


__all__ = ["VoiceBridgeSession"]
