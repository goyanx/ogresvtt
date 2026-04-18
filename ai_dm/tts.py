"""
Text-to-speech via Kokoro-82M.
Install: pip install kokoro soundfile
Windows extra: pip install pywin32  (for audio device enumeration, optional)

Voices suited for a Dungeon Master:
  bm_george  - British male    (recommended: deep, authoritative)
  am_adam    - American male
  bm_lewis   - British male, younger
  af_sky     - American female, dramatic
"""
import io
import numpy as np
import soundfile as sf

_pipeline = None


def _get_pipeline(voice: str = "bm_george"):
    global _pipeline
    if _pipeline is None:
        from kokoro import KPipeline
        # lang_code: 'a' = American English, 'b' = British English
        lang = "b" if voice.startswith("b") else "a"
        _pipeline = KPipeline(lang_code=lang)
    return _pipeline


def synthesize(text: str, voice: str = "bm_george", speed: float = 0.95) -> bytes:
    """
    Synthesize text to WAV audio bytes.
    speed < 1.0 = slower/more dramatic, > 1.0 = faster.
    """
    pipeline = _get_pipeline(voice)
    audio_chunks = []
    for _, _, audio in pipeline(text, voice=voice, speed=speed):
        if audio is not None:
            audio_chunks.append(audio)

    if not audio_chunks:
        return b""

    combined = np.concatenate(audio_chunks)
    buf = io.BytesIO()
    sf.write(buf, combined, samplerate=24000, format="WAV")
    return buf.getvalue()


AVAILABLE_VOICES = [
    {"id": "bm_george", "label": "George (British male) — recommended"},
    {"id": "bm_lewis",  "label": "Lewis (British male)"},
    {"id": "am_adam",   "label": "Adam (American male)"},
    {"id": "am_echo",   "label": "Echo (American male)"},
    {"id": "af_sky",    "label": "Sky (American female)"},
    {"id": "af_nova",   "label": "Nova (American female)"},
    {"id": "bf_emma",   "label": "Emma (British female)"},
]
