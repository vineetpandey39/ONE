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
import threading
import time
from typing import Any, Dict, Optional

import numpy as np
import websockets

from openjarvis.one_agents.wake import (
    _preferred_device,
    pause_wake_listener,
    resume_wake_listener,
)
from openjarvis.voice_bridge.functions import (
    _strip_markdown_for_speech,
    deepgram_function_schemas,
    execute_function,
    remember_full_turn,
)
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
# Reported live (2026-08-09): still crackling/clicking after 150ms -- likely
# not quite enough cushion against real network jitter inside a busy
# multi-threaded server. Doubled for more headroom.
_PLAYBACK_PREBUFFER_SECONDS = 0.3
# Reported live (2026-08-09): an audible click/crackle after every sentence.
# Deepgram streams TTS audio in per-sentence bursts, and the playback queue
# runs dry in the gap between them -- the code was hard-cutting straight to
# digital silence and then jumping straight back to full amplitude, both
# genuine waveform discontinuities (clicks), once per sentence boundary.
# Ramping through a short fade instead of a hard cut removes the click at
# its source without touching the actual voice tone (unlike adding
# reverb/echo, which would mask it but color the sound).
_FADE_SAMPLES = 240  # ~5-10ms depending on output rate -- short enough to be inaudible as a fade itself
# Confirmed live (2026-08-09): repeated controlled tests (device selection,
# buffer size, full-duplex vs input-only) all ruled out as the cause of a
# consistently weak captured signal (~0.01-0.03 peak on a 0-1 scale, vs the
# ~0.3-0.6 a normal speaking voice should produce) on this mic/room setup.
# The signal is real, just quiet -- so it's boosted in software rather than
# depending on Windows mic-boost/OS gain settings. First live conversation
# at gain=16 worked (real replies came back) but hard-clipped on loud
# moments (peaked 1.13-1.48) -- confirmed live that clipping this badly
# didn't just sound harsh, whole utterances went completely unrecognized
# by Deepgram. _mic_callback now runs this through a tanh soft limiter
# instead of a hard clip, so loud moments compress gracefully rather than
# distorting -- this value no longer needs to be tuned down to the exact
# edge of clipping the way a hard-clip gain did.
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
    "You may call get_current_time, agent_stats, or recall_memory directly "
    "when asked about the time, how the agents are doing, or a past "
    "conversation -- never invent an answer to those without calling the "
    "function first. For anything bigger -- searching the web, reading a "
    "file, opening an app, playing something, checking on the system, "
    "running a command, or handing work to one of Sir's named floor agents "
    "(ZEUS, ATHENA, and the rest) -- call ask_ghost_agent with Sir's "
    "request in his own words and relay back whatever it reports."
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
        # Exposed via /v1/voice-bridge/status so the cockpit's glass chat
        # window (previously wired only to typed chat + the now-removed
        # wake-word flow, never to JARVIS Voice Mode) can show the live
        # conversation. Bumped once per completed turn -- see
        # _flush_conversation_turn -- so the frontend can tell a NEW turn
        # apart from a repeated poll of the same one.
        self.last_turn_id = 0
        self.last_turn: Optional[Dict[str, str]] = None
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
        # _out_lock guards _audio_out_queued_bytes specifically: it's
        # mutated from three different threads (asyncio loop via
        # _receive_loop/_drain_playback, PortAudio's output callback via
        # _play_callback) with no synchronization previously -- confirmed
        # live (2026-08-09) as the likely cause of the mic getting stuck
        # permanently gated (counter left stranded above zero by a lost
        # update), which then starved Deepgram of any audio at all long
        # enough to trip its own CLIENT_MESSAGE_TIMEOUT and kill the
        # session.
        self._out_lock = threading.Lock()
        self._audio_out_queued_bytes = 0
        self._playback_primed = False
        # Click-free fade state -- see _FADE_SAMPLES above. Touched only
        # from _play_callback's own thread except _need_fade_in, which
        # _drain_playback also sets so a barge-in resume fades in too.
        self._last_output_sample = 0
        self._need_fade_in = True
        # Diagnostics, all logged periodically by _idle_watchdog so a live
        # session leaves a real trail of where the pipeline actually got to
        # instead of a bare "nothing happened".
        self._last_mic_peak = 0.0
        self._bytes_sent = 0
        self._bytes_received_audio = 0
        self._events_seen: list[str] = []
        self._mic_status_flags = 0
        # Full-transcript memory: confirmed live (2026-08-12) that only
        # exchanges which happened to trigger a function call (ask_ghost_agent
        # etc.) were ever remembered/saved to Obsidian -- most of a real
        # conversation is Deepgram's own think-model answering directly with
        # NO function call at all, and none of that was captured anywhere.
        # ConversationText events cover EVERY turn regardless, so these
        # accumulate the current turn's text and flush (remember + save) it
        # the moment the next user turn starts -- see _handle_event/
        # _flush_conversation_turn.
        self._pending_user_text: Optional[str] = None
        self._pending_assistant_parts: list[str] = []
        # Live preview for the cockpit's glass chat window: confirmed live
        # (2026-08-12) that showing text only at turn-flush time made the
        # window display the PREVIOUS turn while ONE was actually mid-speech
        # on the current one -- a permanent one-turn lag ("delay hai... ek
        # message piche chal rahi hai"). These mirror _pending_user_text/
        # _pending_assistant_parts but are exposed live via
        # /v1/voice-bridge/status on every poll, updated the instant each
        # ConversationText chunk arrives rather than only at flush. Cleared
        # in lockstep with the pending fields in _flush_conversation_turn.
        self.live_user_text = ""
        self.live_assistant_text = ""
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
            with self._out_lock:
                queued = self._audio_out_queued_bytes
            gated = self.state == "speaking" or queued > 0 or time.monotonic() < self._mic_gate_until
            if gated:
                # Send silence rather than nothing at all: Deepgram expects
                # a continuous stream of SOMETHING to stay alive. Confirmed
                # live (2026-08-09) -- going fully silent client-side for
                # the length of a longer reply (a normal, correctly-gated
                # window, not a bug) still tripped Deepgram's own
                # CLIENT_MESSAGE_TIMEOUT and killed the session. Silence
                # keeps the socket fed without ever leaking ONE's own
                # (amplified) voice back to it.
                silence = np.zeros(frames, dtype=np.int16).tobytes()
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(self._queue_mic_chunk, silence)
                return
            # Soft limiter (tanh) instead of a hard clip: confirmed live
            # (2026-08-09) that hard-clipped mic audio (peak >1.0, a sharp
            # digital chop) wasn't just harsh-sounding -- entire loud
            # utterances went completely unrecognized by Deepgram, likely
            # because clipping mangles the waveform enough to break speech
            # recognition, not just audio quality. tanh saturates smoothly
            # toward +-1 instead of chopping, so quiet moments still get
            # the full gain (linear for small values) while loud ones
            # compress gracefully instead of distorting.
            mono = np.tanh(indata[:, 0] * self.mic_gain)
            # Diagnostic only: lets _idle_watchdog's periodic log answer
            # "is real signal even reaching us" without needing another
            # live attempt to find out -- cheap, no allocation beyond a max().
            # Reported post-limiter, so a healthy loud utterance should now
            # read close to but never above 1.0.
            self._last_mic_peak = max(self._last_mic_peak, float(np.max(np.abs(mono))))
            pcm = (mono * 32767).astype(np.int16).tobytes()
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
            chunk = None

            with self._out_lock:
                if not self._playback_primed:
                    if self._audio_out_queued_bytes >= self._playback_prebuffer_bytes:
                        self._playback_primed = True

                if self._playback_primed:
                    chunk = b""
                    while len(chunk) < needed:
                        try:
                            piece = self._audio_out_queue.get_nowait()
                            self._audio_out_queued_bytes -= len(piece)
                            chunk += piece
                        except queue.Empty:
                            break
                    if not chunk:
                        # Ran dry -- re-prime before resuming so the next
                        # burst of audio gets its own cushion instead of
                        # stuttering straight through, and fade the next
                        # burst in rather than snapping to full volume.
                        # This is also the ONE authoritative place the
                        # mic's post-speech cooldown starts: the speaker
                        # has genuinely gone quiet right now (not just
                        # "server said it's done sending" -- see
                        # _mic_callback's comment on why that signal alone
                        # caused a feedback loop).
                        self._playback_primed = False
                        self._need_fade_in = True
                        self._mic_gate_until = time.monotonic() + 0.4
                    elif len(chunk) < needed:
                        chunk += b"\x00" * (needed - len(chunk))
                    elif len(chunk) > needed:
                        leftover = chunk[needed:]
                        self._audio_out_queue.put(leftover)
                        self._audio_out_queued_bytes += len(leftover)
                        chunk = chunk[:needed]

            if not chunk:
                # Fade from whatever was last actually playing down to true
                # silence, instead of a hard cut -- removes the click at the
                # start of every inter-sentence gap.
                n = min(_FADE_SAMPLES, frames)
                if n > 0 and self._last_output_sample != 0:
                    ramp = np.linspace(1.0, 0.0, n, dtype=np.float32)
                    outdata[:n, 0] = (self._last_output_sample * ramp).astype(np.int16)
                    outdata[n:] = 0
                else:
                    outdata.fill(0)
                self._last_output_sample = 0
                return

            samples = np.frombuffer(chunk, dtype=np.int16).copy()
            if self._need_fade_in and len(samples):
                # Symmetric fade-in when resuming after a gap (or on the
                # very first utterance) -- removes the click at the end of
                # every inter-sentence gap.
                n = min(_FADE_SAMPLES, len(samples))
                ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
                samples[:n] = (samples[:n].astype(np.float32) * ramp).astype(np.int16)
                self._need_fade_in = False
            outdata[:] = samples.reshape(-1, 1)
            if len(samples):
                self._last_output_sample = int(samples[-1])
        except Exception:
            logger.debug("voice bridge playback callback error", exc_info=True)
            outdata.fill(0)

    def _drain_playback(self) -> None:
        """Barge-in: the user started talking, stop whatever ONE was saying."""
        with self._out_lock:
            while True:
                try:
                    self._audio_out_queue.get_nowait()
                except queue.Empty:
                    break
            self._audio_out_queued_bytes = 0
            self._playback_primed = False
            self._need_fade_in = True

    # -- main session --

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        api_key = os.environ.get("DEEPGRAM_API_KEY", "")
        if not api_key:
            self.error = "DEEPGRAM_API_KEY is not set."
            raise RuntimeError(self.error)

        # Everything below, including the sounddevice import itself, now
        # lives inside the try/except below rather than running unguarded
        # before it -- confirmed live (2026-08-11) that an import-time crash
        # here (missing sounddevice in the venv after a relocation)
        # propagated straight past _runner()'s wrapper in routes.py, so
        # self.error was never set and /v1/voice-bridge/status reported a
        # clean idle state with no error at all. The button looked simply
        # unresponsive with nothing to diagnose from.
        pause_wake_listener()
        try:
            import sounddevice as sd

            # Redaction is not optional safety here -- confirm it actually
            # imports and runs before ever opening the socket. Fail closed.
            redact("startup self-check")

            # Device selection: reuse the SAME preferred-device logic as
            # ONE's existing wake listener (one_agents/wake.py's
            # _preferred_device), rather than trusting sounddevice's plain
            # OS-default input. On this machine the plain default lands on
            # an MME-level duplicate of the Realtek mic at its 44.1kHz
            # native rate; wake.py deliberately walks past that to the
            # WASAPI instance instead (already proven reliable here). Using
            # the device's OWN native rate for both the capture stream and
            # what we tell Deepgram to expect avoids a silent resample
            # mismatch -- a fixed 16000 constant here previously did not
            # match what was actually being captured, which is the likely
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

            # Same reasoning, speaker side: the previous code never selected
            # an output device at all, so it silently fell back to Windows'
            # non-WASAPI default speaker entry while Settings told Deepgram
            # a fixed 24kHz -- confirmed live as the likely cause of a
            # pitch-distorted ("deep") voice. Walk to the WASAPI Realtek
            # output and use ITS native rate everywhere, same pattern as the
            # input side.
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
            self._flush_conversation_turn()  # catch the last pending turn before the session ends
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
                    with self._out_lock:
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
        if etype == "ConversationText":
            role = event.get("role")
            content = str(event.get("content") or "").strip()
            if content:
                if role == "user":
                    # A new user turn starting means the PRIOR turn (if any)
                    # is now complete -- flush it before starting the new one.
                    self._flush_conversation_turn()
                    self._pending_user_text = content
                    self.live_user_text = content
                elif role == "assistant":
                    # Deepgram streams a reply as several short
                    # ConversationText chunks -- accumulate all of them into
                    # one turn, flushed as a single exchange. live_assistant_text
                    # updates on every chunk (not just at flush) so the glass
                    # window can track speech in near real time instead of
                    # showing the previous, already-finished turn.
                    self._pending_assistant_parts.append(content)
                    self.live_assistant_text = _strip_markdown_for_speech(
                        " ".join(self._pending_assistant_parts).strip()
                    )
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

    def _flush_conversation_turn(self) -> None:
        """Remember + save whatever user/assistant turn has accumulated so
        far, then reset. Runs on the asyncio loop thread (called from
        _handle_event and run()'s finally), so this offloads the actual
        remember/save work to a background thread rather than blocking event
        handling -- same reasoning as _handle_function_calls' run_in_executor.

        last_turn keeps the markdown-stripped text (matches live_assistant_text,
        so the glass window doesn't visibly change the instant a turn
        finalizes) -- remember_full_turn still gets the RAW text, since the
        Obsidian journal is a markdown vault and stripping there would be a
        real loss, not a fix."""
        user_text = self._pending_user_text
        assistant_text = " ".join(self._pending_assistant_parts).strip()
        self._pending_user_text = None
        self._pending_assistant_parts = []
        self.live_user_text = ""
        self.live_assistant_text = ""
        if not user_text or not assistant_text:
            return
        self.last_turn_id += 1
        self.last_turn = {"user": user_text, "assistant": _strip_markdown_for_speech(assistant_text)}
        if self._loop is not None:
            self._loop.run_in_executor(None, remember_full_turn, user_text, assistant_text)

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
