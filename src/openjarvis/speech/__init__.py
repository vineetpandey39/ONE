"""Speech subsystem — speech-to-text and text-to-speech backends."""

import importlib

# Optional STT backends — each registers itself via @SpeechRegistry.register()
for _mod in ("faster_whisper", "openai_whisper", "deepgram"):
    try:
        importlib.import_module(f".{_mod}", __name__)
    except ImportError:
        pass

# Optional TTS backends — each registers itself via @TTSRegistry.register()
# elevenlabs comes first: it is the primary narration backend and the only one
# that can reach Sonia's account-scoped cloned voice. The rest are fallbacks
# for generic speech and can never reproduce her voice.
for _mod in ("elevenlabs_tts", "cartesia_tts", "kokoro_tts", "openai_tts", "fal_elevenlabs_tts"):
    try:
        importlib.import_module(f".{_mod}", __name__)
    except ImportError:
        pass
