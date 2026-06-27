---
name: one-local-transcription
description: Transcribe audio privately with ONE's local GPU-backed Faster-Whisper tool. Use for voice notes, interviews, recordings, subtitles, and audio files without spending API credits.
license: MIT
compatibility: ONE on Windows with Faster-Whisper and an NVIDIA GPU
allowed-tools: audio_transcribe
---

# ONE Local Transcription

Use `audio_transcribe` with `provider: "local"` for supported audio files. Local is
also the default provider. Never select the OpenAI provider unless Vineet explicitly
requests a paid cloud transcription.

## Workflow

1. Confirm the file exists and has a supported extension: mp3, wav, m4a, ogg, flac, or webm.
2. Call `audio_transcribe` with the absolute file path and `provider: "local"`.
3. Set a language code only when the speaker's language is known; otherwise allow multilingual auto-detection.
4. Preserve names, numbers, and agent identifiers exactly when the audio supports them.
5. State uncertainty instead of inventing words when audio is unclear.
6. For permanent memory, format the transcript with `obsidian-markdown` and save it through `obsidian_memory`.

ONE's vocabulary bias includes ONE/JARVIS, Vineet, PostForge, Obsidian, and all named agents.
