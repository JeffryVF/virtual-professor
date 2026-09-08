import io
import logging

import edge_tts

from core.config import settings

log = logging.getLogger(__name__)

_ES_ACCENTS = "áéíóúñÁÉÍÓÚÑ"

_ES_STOPWORDS = frozenset({
    "el", "la", "los", "las", "un", "una", "que", "es", "de", "y", "para",
    "por", "con", "sobre", "hola", "qué", "como", "eres", "soy", "tema",
})

_EN_STOPWORDS = frozenset({
    "the", "is", "of", "to", "and", "for", "what", "how", "are", "you",
    "with", "hello", "can", "about", "teach", "topic",
})


def _strip_punct(token: str) -> str:
    return "".join(ch for ch in token if ch.isalnum())


def detect_language(text: str) -> str:
    """Best-effort ES/EN detection for a short message."""
    lowered = text.lower()
    if any(ch in lowered for ch in _ES_ACCENTS):
        return "es"
    tokens = [_strip_punct(tok) for tok in lowered.split()]
    es_count = sum(1 for tok in tokens if tok and tok in _ES_STOPWORDS)
    en_count = sum(1 for tok in tokens if tok and tok in _EN_STOPWORDS)
    return "es" if es_count >= en_count else "en"


def resolve_language(language, text: str) -> str:
    """Map a professor/student language value ('es'/'en'/'both') to 'es'/'en'.

    Explicit 'es'/'en' are returned as-is; 'both' falls back to per-message
    heuristic detection so the female Edge-TTS voice matches the language.
    """
    value = getattr(language, "value", language)
    if value in ("es", "en"):
        return value
    return detect_language(text)


def _voice_for(language: str, voice: str | None) -> str:
    """Pick an Edge-TTS voice for the given language (ES/EN)."""
    if voice:
        return voice
    if language == "es":
        return settings.edge_tts_voice_es
    if language == "en":
        return settings.edge_tts_voice_en
    return settings.edge_tts_voice_en


async def synthesize(text: str, voice: str | None = None, language: str = "en") -> bytes:
    """Synthesize *text* to MP3 bytes using Edge-TTS."""
    voice_name = _voice_for(language, voice)
    communicate = edge_tts.Communicate(text, voice_name, rate=settings.edge_tts_rate)
    buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buffer.write(chunk["data"])
    data = buffer.getvalue()
    if not data:
        raise RuntimeError("Edge-TTS produced no audio data")
    return data


async def synthesize_chunked(
    text: str,
    voice: str | None = None,
    language: str = "en",
) -> bytes:
    """Synthesize *text*, truncating gracefully when it exceeds the total budget.

    Edge-TTS handles long text in a single request, so the old WAV
    split-and-merge pipeline is no longer needed. The full text is persisted
    separately in the DB; only the audio copy is trimmed here.
    """
    max_total = settings.tts_max_total_chars
    if len(text) > max_total:
        log.info("Text exceeds TTS_MAX_TOTAL_CHARS (%d), truncating to %d", len(text), max_total)
        text = _truncate_at_sentence(text, max_total)
    return await synthesize(text, voice, language)


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    """Truncate *text* at the last sentence boundary before *max_chars*."""
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars].rstrip()
    match = __import__("re").search(r"[.!?]\s*$", truncated)
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