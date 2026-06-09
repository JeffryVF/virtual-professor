import httpx

from core.config import settings

# Default voices per language — override per-professor in future iterations
_DEFAULT_VOICES = {
    "en": "af_heart",
    "es": "ef_dora",
    "both": "af_heart",
}


async def synthesize(text: str, voice: str | None = None, language: str = "en") -> bytes:
    """Send text to Kokoro TTS and return WAV audio bytes."""
    payload = {
        "text": text,
        "voice": voice or _DEFAULT_VOICES.get(language, "af_heart"),
        "language": "en-us" if language == "en" else "es",
        "speed": 1.0,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(f"{settings.kokoro_url}/tts", json=payload)
        response.raise_for_status()
        return response.content
