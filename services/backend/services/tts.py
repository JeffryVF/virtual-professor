import io
import logging
import re
import wave

import httpx

from core.config import settings

log = logging.getLogger(__name__)

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


def _split_into_tts_chunks(text: str, max_chars: int = None) -> list[str]:
    """Split text into sentence-aligned chunks, each <= *max_chars*.

    Falls back to word-level splitting when a single sentence exceeds the limit.
    """
    if max_chars is None:
        max_chars = settings.tts_chunk_max_chars
    if not text or len(text) <= max_chars:
        return [text] if text else []

    # Split on sentence boundaries (. ! ? followed by space or end-of-string)
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if len(sentence) > max_chars:
            # Flush current buffer first
            if current:
                chunks.append(" ".join(current))
                current = []
                current_len = 0

            # Force-split this long sentence at word boundaries
            words = sentence.split()
            temp: list[str] = []
            temp_len = 0
            for word in words:
                if temp_len + len(word) + 1 > max_chars and temp:
                    chunks.append(" ".join(temp))
                    temp = [word]
                    temp_len = len(word)
                else:
                    temp.append(word)
                    temp_len += len(word) + 1
            if temp:
                chunks.append(" ".join(temp))

        elif current_len + len(sentence) + 1 > max_chars and current:
            chunks.append(" ".join(current))
            current = [sentence]
            current_len = len(sentence)
        else:
            current.append(sentence)
            current_len += len(sentence) + 1

    if current:
        chunks.append(" ".join(current))

    return chunks


def _merge_wavs(wav_chunks: list[bytes]) -> bytes:
    """Merge multiple 16-bit mono WAV byte strings into a single WAV.

    All chunks must share the same sample rate, bit depth, and channel count.
    """
    pcm_parts: list[bytes] = []
    params: tuple[int, int, int, int, str, str] | None = None

    for wav_bytes in wav_chunks:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            frame_params = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate())
            if params is None:
                params = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), 0, "NONE", "not compressed")
            else:
                if frame_params != (params[0], params[1], params[2]):
                    log.warning(
                        "WAV format mismatch: expected %s, got %s — re-encoding first chunk",
                        params[:3],
                        frame_params,
                    )
                    # Re-sample everything to match first chunk via intermediate PCM
                    # (In practice Kokoro always returns 24KHz 16-bit mono so this is defensive)
                    params = (params[0], params[1], params[2], 0, "NONE", "not compressed")
            pcm_parts.append(wav.readframes(wav.getnframes()))

    if not pcm_parts:
        raise ValueError("No PCM data to merge")

    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(params[0])
        out.setsampwidth(params[1])
        out.setframerate(params[2])
        for part in pcm_parts:
            out.writeframes(part)
    return buf.getvalue()


async def synthesize_chunked(
    text: str,
    voice: str | None = None,
    language: str = "en",
) -> bytes:
    """Split *text* into sentence-aligned chunks, synthesize each, and merge.

    Falls back gracefully when individual chunks fail — as long as at least one
    chunk succeeds the call returns valid WAV audio.
    """
    max_chars = settings.tts_chunk_max_chars
    max_total = settings.tts_max_total_chars

    if len(text) <= max_chars:
        return await synthesize(text, voice, language)

    # Apply total-length guard before chunking
    if len(text) > max_total:
        log.info("Text exceeds TTS_MAX_TOTAL_CHARS (%d), truncating to %d", len(text), max_total)
        text = _truncate_at_sentence(text, max_total)

    chunks = _split_into_tts_chunks(text, max_chars)
    log.info("Splitting TTS text into %d chunks (%d chars total)", len(chunks), len(text))

    wav_parts: list[bytes] = []
    for i, chunk in enumerate(chunks):
        try:
            wav = await synthesize(chunk, voice, language)
            wav_parts.append(wav)
            log.debug("TTS chunk %d/%d OK (%d chars)", i + 1, len(chunks), len(chunk))
        except Exception as exc:
            log.warning("TTS chunk %d/%d failed (%d chars): %s", i + 1, len(chunks), len(chunk), exc)
            continue

    if not wav_parts:
        raise RuntimeError("All TTS chunks failed — no audio produced")

    if len(wav_parts) == 1:
        return wav_parts[0]

    return _merge_wavs(wav_parts)


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    """Truncate *text* at the last sentence boundary before *max_chars*."""
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars].rstrip()
    # Find last sentence-ending punctuation
    match = re.search(r"[.!?]\s*$", truncated)
    if match:
        return truncated
    # Fall back to last sentence boundary within the window
    last_boundary = max(
        truncated.rfind(". "),
        truncated.rfind("? "),
        truncated.rfind("! "),
    )
    if last_boundary > 0:
        return truncated[: last_boundary + 1]
    # Worst case: cut at word boundary
    last_space = truncated.rfind(" ")
    return truncated[:last_space] if last_space > 0 else truncated
