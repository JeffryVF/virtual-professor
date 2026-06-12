import json
import logging

from redis.asyncio import Redis

from core.config import settings

log = logging.getLogger(__name__)

# ── Optional tokenizer ──────────────────────────────────────────────────────
_TIKTOKEN_AVAILABLE = False
_tiktoken_enc = None

try:
    import tiktoken

    _tiktoken_enc = tiktoken.get_encoding("cl100k_base")
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    log.info("tiktoken not available — falling back to char-based token estimation")
except Exception as exc:
    log.warning("tiktoken init failed — falling back to char-based estimation: %s", exc)

_SESSION_KEY = "session:{session_id}:history"


def _create_client() -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=10,
        retry_on_timeout=True,
        health_check_interval=30,
    )


_redis = _create_client()


async def _ensure_connected() -> Redis:
    global _redis
    try:
        await _redis.ping()
    except Exception:
        log.warning("Redis connection lost, reconnecting...")
        try:
            await _redis.aclose()
        except Exception:
            pass
        _redis = _create_client()
    return _redis


# ── Token estimation ────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text string.

    Uses tiktoken (cl100k_base) if available — not exact for llama3.2 but
    close enough for compression decisions. Falls back to ~4 chars/token.
    """
    if _TIKTOKEN_AVAILABLE and _tiktoken_enc is not None:
        return len(_tiktoken_enc.encode(text))
    return len(text) // 4


def _compress_messages(history: list[dict], max_tokens: int) -> int:
    """Remove oldest messages until total estimated tokens fit within ``max_tokens``.

    Mutates the list in place. Always keeps at least one message.
    Returns the number of messages removed.
    """
    if not history:
        return 0

    removed = 0
    while len(history) > 1:
        total = sum(estimate_tokens(m.get("content", "")) for m in history)
        if total <= max_tokens:
            break
        history.pop(0)
        removed += 1

    return removed


# ── Backward-compat alias ───────────────────────────────────────────────────
_estimate_tokens = estimate_tokens

# ── Public API ──────────────────────────────────────────────────────────────

async def get_history(session_id: str) -> list[dict]:
    """Return the cached conversation history for a session."""
    try:
        client = await _ensure_connected()
        raw = await client.get(_SESSION_KEY.format(session_id=session_id))
        return json.loads(raw) if raw else []
    except Exception as exc:
        log.error("Failed to read session history from Redis: %s", exc)
        return []


async def compress_history(
    session_id: str,
    max_tokens: int | None = None,
) -> int:
    """Compress session history by removing oldest messages until total
    estimated tokens fit within ``max_tokens``.

    Returns the number of messages removed. A no-op if already under limit.
    Raises on Redis error so callers (e.g. an endpoint) can surface it.
    """
    client = await _ensure_connected()
    raw = await client.get(_SESSION_KEY.format(session_id=session_id))
    if not raw:
        return 0

    history = json.loads(raw)
    if max_tokens is None:
        max_tokens = settings.session_memory_max_tokens

    removed = _compress_messages(history, max_tokens)

    if removed:
        ttl = settings.session_timeout_minutes * 60
        await client.setex(
            _SESSION_KEY.format(session_id=session_id),
            ttl,
            json.dumps(history),
        )

    return removed


async def append_message(session_id: str, role: str, content: str) -> None:
    """Append a message to the session history and trim to the configured window."""
    try:
        client = await _ensure_connected()
        history = await get_history(session_id)
        history.append({"role": role, "content": content})

        # 1. Trim by message count
        max_pairs = settings.session_memory_messages
        if len(history) > max_pairs * 2:
            history = history[-(max_pairs * 2):]

        # 2. Trim by token budget (second safety net)
        _compress_messages(history, settings.session_memory_max_tokens)

        ttl = settings.session_timeout_minutes * 60
        await client.setex(
            _SESSION_KEY.format(session_id=session_id),
            ttl,
            json.dumps(history),
        )
    except Exception as exc:
        log.error("Failed to append session history to Redis: %s", exc)


async def clear_session(session_id: str) -> None:
    try:
        client = await _ensure_connected()
        await client.delete(_SESSION_KEY.format(session_id=session_id))
    except Exception as exc:
        log.error("Failed to clear session from Redis: %s", exc)
