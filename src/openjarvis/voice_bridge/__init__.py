"""Deepgram Voice Agent bridge: a redacted, opt-in real-time voice pipeline.

Connects ONE to Deepgram's cloud Voice Agent WebSocket API (Flux STT +
managed LLM + Aura-2 TTS) as an outbound-only client, so voice conversations
feel like the Deepgram playground demo instead of ONE's existing multi-hop
REST pipeline. Only 3 narrow functions are exposed to the cloud LLM
(voice_bridge.functions), and everything that could leave the machine is
passed through voice_bridge.redact first. See client.py for the session
itself, started/stopped on demand via /v1/voice-bridge/* in server/routes.py.
"""

from __future__ import annotations
