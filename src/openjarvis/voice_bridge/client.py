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

from openjarvis.one_agents.wake import (
    _preferred_device,
    pause_wake_listener,
    resume_wake_listener,
)
from openjarvis.voice_bridge.functions import deepgram_function_schemas, execute_function
from openjarvis.voice_bridge.redact import redact

logger = logging.getLogger("openjarvis.voice_bridge")

_AGENT_WS_URL = "wss://agent.deepgram.com/v1/agent/converse"
# Playback prebuffer: confirmed live (2026-08-09) that draining Deepgram's
# incoming audio into the speaker callback as it trickles in, with no
# buffer ahead of the play head, produces audible fluctuation/humming --
# the callback outruns the network and fills the gap with silence, over
# and over. Holding back ~150ms of audio before starting playback (and
# re-priming after every silence gap) gives the network a cushion so the
# callback is never starved mid-utterance. Computed per-session from the
# actually-resolved output rate (see run()), not a fixed constant.
_PLAYBACK_PREBUFFER_SECONDS = 0.15
# Confirmed live (2026-08-09): repeated controlled tests (device selection,
# buffer size, full-duplex vs input-only) all ruled out as the cause of a
# consistently weak captured signal (~0.01-0.03 peak on a 0-1 scale, vs the
# ~0.3-0.6 a normal speaking voice should produce) on this mic/room setup.
# The signal is real, just quiet -- so it's boosted in software rather than
# depending on Windows mic-boost/OS gain settings. First live conversation
# at gain=16 worked (real replies came back) but peaked at 1.13-1.48 --
# audibly clipping, and likely feeding Flux's turn-detector distorted noise
# that triggered extra false turns (reported live as replies overlapping
# within milliseconds). Backed off to leave headroom against that same
# loud-moment peak (~0.09 raw * 9 =~ 0.8, under the 1.0 clip ceiling).
_DEFAULT_MIC_GAIN = 9.0

# Deepgram Aura v1 speed control (agent.speak.provider.speed), valid range
# 0.7-1.5, default 1.0. Requested live (2026-08-09) to slow the reply pace
# down a notch as a further mitigation against the fluctuation/humming
# reported earlier -- a gentler pace gives the playback prebuffer/network
# more slack per word, on top of the buffering and device fixes already in.
_DEFAULT_SPEAK_SPEED = 0.85

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


def _preferred_output_device(sd: Any) -> Optional[int]:
    """Mirrors one_agents.wake._preferred_device, for the speaker side.

    Confirmed live (2026-08-09): the input side used the plain OS-default
    device until it was pointed at the WASAPI-hosted Realtek instance
    specifically; the output side had the same class of bug -- it was never
    given a device at all, so it fell back to Windows' default speaker
    entry (an older, non-WASAPI, 44.1kHz-native path) while the Settings
    message told Deepgram to expect 24kHz. That mismatch is the most likely
    cause of the "deep, pitch-distorted" voice reported live. Walking to the
    WASAPI Realtek output, same as the input side, keeps both directions on
    the same reliable host API.
    """
    configured = os.environ.get("ONE_VOICE_OUTPUT_DEVICE", "").strip()
    if configured:
        return int(configured)
    try:
        count = len(sd.query_devices())
    except Exception:
        count = 0
    for index in range(count):
        try:
            device = sd.query_devices(index)
        except Exception:
            continue
        if device.get("max_output_channels", 0) < 1 or "realtek" not in str(device.get("name", "")).lower():
            continue
        try:
            host_name = sd.query_hostapis(device["hostapi"])["name"]
        except Exception:
            continue
        if "WASAPI" in host_name:
            return index
    try:
        return int(sd.default.device[1])
    except Exception:
        return None


class VoiceBridgeSession:
    """One live Deepgram Voice Agent conversation. Not reusable -- create a
    fresh instance per start/stop cycle."""

    def __init__(
        self,
        *,
        speak_model: str = "aura-2-thalia-en",
        think_model: str = "claude-haiku-4-5",
        silence_timeout_seconds: float = 90.0,
        mic_gain: float = _DEFAULT_MIC_GAIN,
        speak_speed: float = _DEFAULT_SPEAK_SPEED,
    ) -> None:
        self.speak_model = speak_model
        self.think_model = think_model
        self.silence_timeout_seconds = silence_timeout_seconds
        self.mic_gain = mic_gain
        self.speak_speed = speak_speed
        self.state = "idle"  # idle | listening | thinking | speaking
        self.error: Optional[str] = None
        self._ws: Any = None
        self._stop = asyncio.Event()
        self._last_activity = time.monotonic()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Resolved at run() time to the real input/output devices' own
        # native rates -- see run()'s device-selection comment for why
        # these can't be hardcoded constants.
        self._sample_rate_in = 16000
        self._sample_rate_out = 24000
        self._playback_prebuffer_bytes = int(self._sample_rate_out * 2 * _PLAYBACK_PREBUFFER_SECONDS)
        # Mic-in: producer (PortAudio thread) -> consumer (asyncio task).
        # asyncio.Queue is safe here because the producer only ever touches
        # it via call_soon_threadsafe, which hops onto the loop thread first.
        self._audio_in_queue: "asyncio.Queue[bytes]" = asyncio.Queue(maxsize=64)
        # Speaker-out: producer (asyncio task) -> consumer (PortAudio
        # thread). asyncio.Queue is NOT safe to read from a non-loop thread,
        # so this is a plain thread-safe stdlib queue instead.
        self._audio_out_queue: "queue.SimpleQueue[bytes]" = queue.SimpleQueue()
        # Prebuffer bookkeeping -- see _PLAYBACK_PREBUFFER_SECONDS above.
        self._audio_out_queued_bytes = 0
        self._playback_primed = False
        # Diagnostics, all logged periodically by _idle_watchdog so a live
        # session leaves a real trail of where the pipeline actually got to
        # instead of a bare "nothing happened".
        self._last_mic_peak = 0.0
        self._bytes_sent = 0
        self._bytes_received_audio = 0
        self._events_seen: list[str] = []
        self._mic_status_flags = 0
        # Half-duplex gate: no AEC (acoustic echo cancellation) exists on
        # this raw sounddevice path (unlike a browser's getUserMedia, which
        # gets it for free), so on a desktop with open mic + open speakers
        # ONE's own TTS output was being picked up by the mic and read back
        # to Deepgram as if Sir were talking -- a self-sustaining feedback
        # loop (confirmed live: continuous back-to-back replies, audio
        # cutting in and out from false barge-in). Mic capture is suppressed
        # while state=="speaking" and for a short cooldown after, so ONE
        # can't hear itself. Trade-off: true mid-sentence barge-in is off
        # for now -- ONE finishes speaking, then listens. Real headphones
        # would remove the acoustic coupling entirely and let barge-in come
        # back safely later if wanted.
        self._mic_gate_until = 0.0

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    # -- sounddevice callbacks (run on PortAudio's own thread, not asyncio) --

    def _mic_callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        try:
            if status:
                # PortAudio overflow/underflow flags -- silently ignored
                # until now. If this counter climbs during a live session,
                # the callback thread isn't being scheduled promptly enough
                # inside the busy multi-threaded server, and that (not the
                # device or buffer size) is what's attenuating/corrupting
                # what actually gets captured.
                self._mic_status_flags += 1
            # Half-duplex gate -- see __init__'s comment. Don't send ONE's
            # own voice back to Deepgram as if it were Sir talking. Gated on
            # self.state for the window between "Deepgram started sending
            # audio" and "playback actually started", and on
            # _audio_out_queued_bytes for as long as there's still buffered
            # audio actually coming out of the speaker -- NOT on
            # AgentAudioDone, which only means the server finished SENDING,
            # not that playback has finished being heard (confirmed live:
            # gating on that signal alone reopened the mic mid-playback and
            # produced a self-sustaining feedback loop). See _play_callback
            # for where the cooldown actually starts once the speaker goes
            # quiet for real.
            if self.state == "speaking" or self._audio_out_queued_bytes > 0 or time.monotonic() < self._mic_gate_until:
                return
            mono = indata[:, 0] * self.mic_gain
            # Diagnostic only: lets _idle_watchdog's periodic log answer
            # "is real signal even reaching us" without needing another
            # live attempt to find out -- cheap, no allocation beyond a max().
            # Reported post-gain so it reflects what's actually being sent.
            self._last_mic_peak = max(self._last_mic_peak, float(np.max(np.abs(mono))))
            pcm = np.clip(mono * 32767, -32768, 32767).astype(np.int16).tobytes()
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

            if not self._playback_primed:
                if self._audio_out_queued_bytes < self._playback_prebuffer_bytes:
                    outdata.fill(0)
                    return
                self._playback_primed = True

            chunk = b""
            while len(chunk) < needed:
                try:
                    piece = self._audio_out_queue.get_nowait()
                    self._audio_out_queued_bytes -= len(piece)
                    chunk += piece
                except queue.Empty:
                    break
            if not chunk:
                # Ran dry -- re-prime before resuming so the next burst of
                # audio gets its own cushion instead of stuttering straight
                # through. This is also the ONE authoritative place the
                # mic's post-speech cooldown starts: the speaker has
                # genuinely gone quiet right now (not just "server said
                # it's done sending" -- see _mic_callback's comment on why
                # that signal alone caused a feedback loop).
                self._playback_primed = False
                self._mic_gate_until = time.monotonic() + 0.4
                outdata.fill(0)
                return
            if len(chunk) < needed:
                chunk += b"\x00" * (needed - len(chunk))
            elif len(chunk) > needed:
                leftover = chunk[needed:]
                self._audio_out_queue.put(leftover)
                self._audio_out_queued_bytes += len(leftover)
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
        self._audio_out_queued_bytes = 0
        self._playback_primed = False

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

        # Device selection: reuse the SAME preferred-device logic as ONE's
        # existing wake listener (one_agents/wake.py's _preferred_device),
        # rather than trusting sounddevice's plain OS-default input. On this
        # machine the plain default lands on an MME-level duplicate of the
        # Realtek mic at its 44.1kHz native rate; wake.py deliberately walks
        # past that to the WASAPI instance instead (already proven reliable
        # here). Using the device's OWN native rate for both the capture
        # stream and what we tell Deepgram to expect avoids a silent
        # resample mismatch -- a fixed 16000 constant here previously did
        # not match what was actually being captured, which is the likely
        # reason a real 19s session produced audio Deepgram couldn't use.
        input_device = _preferred_device(sd)
        if input_device is None:
            input_device = sd.default.device[0]
        device_info = sd.query_devices(input_device, "input")
        self._sample_rate_in = int(device_info.get("default_samplerate", 16000)) or 16000
        logger.warning(
            "[voice bridge diag] using input device %r (index=%s) at %dHz",
            device_info.get("name"),
            input_device,
            self._sample_rate_in,
        )

        # Same reasoning, speaker side: the previous code never selected an
        # output device at all, so it silently fell back to Windows'
        # non-WASAPI default speaker entry while Settings told Deepgram a
        # fixed 24kHz -- confirmed live as the likely cause of a
        # pitch-distorted ("deep") voice. Walk to the WASAPI Realtek output
        # and use ITS native rate everywhere, same pattern as the input side.
        output_device = _preferred_output_device(sd)
        if output_device is None:
            output_device = sd.default.device[1]
        output_info = sd.query_devices(output_device, "output")
        self._sample_rate_out = int(output_info.get("default_samplerate", 24000)) or 24000
        self._playback_prebuffer_bytes = int(self._sample_rate_out * 2 * _PLAYBACK_PREBUFFER_SECONDS)
        logger.warning(
            "[voice bridge diag] using output device %r (index=%s) at %dHz",
            output_info.get("name"),
            output_device,
            self._sample_rate_out,
        )

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

                # No explicit blocksize: forcing a tiny 20ms buffer here
                # (previous code) starves/glitches WASAPI's own preferred
                # buffering and was confirmed live to suppress the captured
                # level by 6-14x on this exact device compared to a plain
                # sd.InputStream() with no blocksize at all -- let PortAudio
                # pick its own, same as the standalone test that worked.
                with sd.InputStream(
                    device=input_device,
                    samplerate=self._sample_rate_in,
                    channels=1,
                    dtype="float32",
                    callback=self._mic_callback,
                ), sd.OutputStream(
                    device=output_device,
                    samplerate=self._sample_rate_out,
                    channels=1,
                    dtype="int16",
                    callback=self._play_callback,
                ):
                    results = await asyncio.gather(
                        self._send_audio_loop(ws),
                        self._receive_loop(ws),
                        self._idle_watchdog(),
                        return_exceptions=True,
                    )
                    for result in results:
                        if isinstance(result, Exception):
                            logger.warning("voice bridge subtask ended with error: %s", result, exc_info=result)
                            self.error = self.error or str(result)
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            logger.warning("voice bridge session ended with error: %s", exc, exc_info=True)
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
                "input": {"encoding": "linear16", "sample_rate": self._sample_rate_in},
                "output": {"encoding": "linear16", "sample_rate": self._sample_rate_out, "container": "none"},
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
                "speak": {
                    "provider": {"type": "deepgram", "model": self.speak_model, "speed": self.speak_speed}
                },
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
            self._bytes_sent += len(pcm)

    async def _receive_loop(self, ws: Any) -> None:
        try:
            async for message in ws:
                if self._stop.is_set():
                    break
                self._touch()
                if isinstance(message, (bytes, bytearray)):
                    self._bytes_received_audio += len(message)
                    self._audio_out_queue.put(bytes(message))
                    self._audio_out_queued_bytes += len(message)
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
        self._events_seen.append(etype or "?")
        if etype in ("ConversationText", "Error", "Warning"):
            logger.warning("[voice bridge diag] event: %s", event)
        if etype == "UserStartedSpeaking":
            self.state = "listening"
            self._drain_playback()
        elif etype == "AgentThinking":
            self.state = "thinking"
        elif etype == "AgentStartedSpeaking":
            self.state = "speaking"
        elif etype == "AgentAudioDone":
            # Only means Deepgram finished SENDING audio -- playback may
            # still have several seconds queued. The mic stays gated via
            # _audio_out_queued_bytes (checked in _mic_callback) until
            # _play_callback confirms the speaker has actually gone quiet.
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
        connected minute, so an idle session left open is wasted credit.
        Also the diagnostic heartbeat: logs mic level / bytes sent+received
        / events seen every ~4s so a real session leaves concrete evidence
        of exactly where the pipeline got to, instead of a bare 'nothing
        happened'."""
        tick = 0
        while not self._stop.is_set():
            await asyncio.sleep(2.0)
            tick += 1
            if tick % 2 == 0:
                logger.warning(
                    "[voice bridge diag] state=%s mic_peak=%.3f bytes_sent=%d bytes_recv_audio=%d status_flags=%d events=%s",
                    self.state,
                    self._last_mic_peak,
                    self._bytes_sent,
                    self._bytes_received_audio,
                    self._mic_status_flags,
                    self._events_seen[-10:],
                )
                self._last_mic_peak = 0.0
            if time.monotonic() - self._last_activity > self.silence_timeout_seconds:
                logger.warning(
                    "[voice bridge diag] idle for %.0fs, auto-disconnecting to save credit.",
                    self.silence_timeout_seconds,
                )
                self._stop.set()
                if self._ws is not None:
                    await self._ws.close()
                break

    def request_stop(self) -> None:
        """Called from the /v1/voice-bridge/stop route. Setting the flag
        alone isn't enough: _receive_loop's `async for message in ws` blocks
        until the NEXT message arrives, so if Deepgram has gone quiet it
        would never notice _stop was set. Actually closing the socket is
        what guarantees the session actually ends instead of hanging."""
        self._stop.set()
        if self._loop is not None and self._ws is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
            except Exception:
                logger.debug("voice bridge: closing ws on stop failed", exc_info=True)


__all__ = ["VoiceBridgeSession"]
