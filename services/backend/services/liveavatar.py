import logging

import httpx

from core.config import settings

log = logging.getLogger(__name__)


async def create_session_token(avatar_id: str) -> dict:
    """
    POST /v1/sessions/token (LITE mode).
    Returns {"session_id": ..., "session_token": ...}
    """
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
        log.info("token response %s: %s", response.status_code, response.text)
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
        log.info("start response %s: %s", response.status_code, response.text)
        response.raise_for_status()
        return response.json()["data"]


async def create_embed_session(avatar_id: str) -> dict:
    """Legacy embed helper (kept for reference)."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.liveavatar_api_url}/v2/embeddings",
            headers={"Authorization": f"Bearer {settings.liveavatar_api_key}"},
            json={"avatar_id": avatar_id, "mode": "lite", "interaction_mode": "push_to_talk"},
        )
        response.raise_for_status()
        return response.json()
