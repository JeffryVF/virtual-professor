import logging
from uuid import UUID

import httpx

from core.config import settings
from core.utils import mask_sensitive

log = logging.getLogger(__name__)


def _normalize_avatar_id(avatar_id: str) -> str:
    """Validate that LiveAvatar receives a UUID-shaped avatar ID.

    LiveAvatar rejects placeholders such as "avatar-1" or "<avatar_id>".
    We validate locally so callers get a clear 422 before hitting the API.
    """
    try:
        return str(UUID(avatar_id))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "avatar_id must be a valid UUID from LiveAvatar (for example, a public avatar ID)."
        ) from exc


async def create_session_token(avatar_id: str) -> dict:
    """
    POST /v1/sessions/token (LITE mode).
    Returns {"session_id": ..., "session_token": ...}
    """
    avatar_id = _normalize_avatar_id(avatar_id)

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.liveavatar_api_url}/v1/sessions/token",
            headers={"X-API-KEY": settings.liveavatar_api_key},
            json={
                "mode": "LITE",
                "avatar_id": avatar_id,
                "is_sandbox": settings.liveavatar_sandbox,
            },
        )
        log.info(
            "token response %s (length=%s)",
            response.status_code,
            len(response.text),
        )
        response.raise_for_status()
        return response.json()["data"]


async def start_session(session_token: str) -> dict:
    """
    POST /v1/sessions/start.
    Returns {session_id, livekit_url, livekit_client_token, ws_url, ...}
    """
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.liveavatar_api_url}/v1/sessions/start",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        log.info(
            "start response %s (length=%s)",
            response.status_code,
            len(response.text),
        )
        response.raise_for_status()
        return response.json()["data"]


async def stop_session(session_id: str, reason: str = "USER_CLOSED") -> dict:
    """POST /v1/sessions/stop to close an active LiveAvatar session."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.liveavatar_api_url}/v1/sessions/stop",
            headers={"X-API-KEY": settings.liveavatar_api_key},
            json={"session_id": session_id, "reason": reason},
        )
        log.info(
            "stop response %s (length=%s)",
            response.status_code,
            len(response.text),
        )
        response.raise_for_status()
        return response.json()["data"]


async def create_embed_session(avatar_id: str) -> dict:
    """Legacy embed helper (kept for reference)."""
    avatar_id = _normalize_avatar_id(avatar_id)

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.liveavatar_api_url}/v2/embeddings",
            headers={"Authorization": f"Bearer {settings.liveavatar_api_key}"},
            json={"avatar_id": avatar_id, "mode": "lite", "interaction_mode": "push_to_talk"},
        )
        response.raise_for_status()
        return response.json()
