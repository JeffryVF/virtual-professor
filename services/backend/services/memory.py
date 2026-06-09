import json
import logging

from redis.asyncio import Redis

from core.config import settings

log = logging.getLogger(__name__)

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


async def get_history(session_id: str) -> list[dict]:
    """Return the cached conversation history for a session."""
    try:
        client = await _ensure_connected()
        raw = await client.get(_SESSION_KEY.format(session_id=session_id))
        return json.loads(raw) if raw else []
    except Exception as exc:
        log.error("Failed to read session history from Redis: %s", exc)
        return []


async def append_message(session_id: str, role: str, content: str) -> None:
    """Append a message to the session history and trim to the configured window."""
    try:
        client = await _ensure_connected()
        history = await get_history(session_id)
        history.append({"role": role, "content": content})

        max_pairs = settings.session_memory_messages
        if len(history) > max_pairs * 2:
            history = history[-(max_pairs * 2):]

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
