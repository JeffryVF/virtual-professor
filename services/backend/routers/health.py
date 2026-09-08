"""Enhanced health-check endpoint with async probes for all backend services."""

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter
from redis.asyncio import Redis
from sqlalchemy import text

from core.config import settings
from core.database import AsyncSessionLocal

log = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_SERVICE_TIMEOUT = 5
# Qdrant Cloud TLS + REST can exceed the local 5s budget on first contact.
_QDRANT_PROBE_TIMEOUT = 20


# ── Individual probe functions ───────────────────────────────────────────────
# Each raises on failure so the caller can wrap with timeout + error handling.


async def _probe_postgres() -> dict:
    """Check postgres connectivity via SELECT 1."""
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "healthy"}


async def _probe_redis() -> dict:
    """Check redis connectivity via PING."""
    client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=_SERVICE_TIMEOUT,
        socket_timeout=_SERVICE_TIMEOUT,
    )
    try:
        await client.ping()
        return {"status": "healthy"}
    finally:
        await client.aclose()


async def _probe_zai() -> dict:
    """Check Z.AI connectivity via GET /models."""
    base = settings.zai_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=_SERVICE_TIMEOUT) as client:
        response = await client.get(
            f"{base}/models",
            headers={"Authorization": f"Bearer {settings.zai_api_key}"},
        )
        response.raise_for_status()
    return {"status": "healthy"}


async def _probe_qdrant() -> dict:
    """Check Qdrant Cloud connectivity via list-collections."""
    from core.qdrant import get_async_qdrant_client

    client = get_async_qdrant_client()
    try:
        await client.get_collections()
        return {"status": "healthy"}
    finally:
        await client.close()


async def _probe_gemini() -> dict:
    """Check Gemini API connectivity via GET /v1beta/models."""
    key = (settings.google_api_key or settings.gemini_api_key).strip()
    async with httpx.AsyncClient(timeout=_SERVICE_TIMEOUT) as client:
        response = await client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": key, "pageSize": 1},
        )
        response.raise_for_status()
    return {"status": "healthy"}


# ── Probe runner with timeout ────────────────────────────────────────────────


async def _run_probe(name: str, probe_coro, timeout: float = _SERVICE_TIMEOUT) -> tuple[str, dict]:
    """Run a single probe with timeout and latency measurement.

    Returns a (name, result_dict) tuple suitable for ``dict()``.
    """
    start = asyncio.get_event_loop().time()
    try:
        result = await asyncio.wait_for(probe_coro, timeout=timeout)
        elapsed = (asyncio.get_event_loop().time() - start) * 1000
        result["latency_ms"] = round(elapsed, 2)
        return name, result
    except asyncio.TimeoutError:
        return name, {"status": "unhealthy", "error": "timeout"}
    except Exception as exc:
        return name, {"status": "unhealthy", "error": str(exc)}


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get("/health")
async def health():
    """Combined health check for all backend services.

    All probes run concurrently. Local services use a 5-second timeout;
    the Qdrant Cloud probe allows 20 seconds for TLS and REST.
    Returns ``healthy`` only when every service responds, ``degraded`` otherwise.
    """
    raw = await asyncio.gather(
        _run_probe("postgres", _probe_postgres()),
        _run_probe("redis", _probe_redis()),
        _run_probe("zai", _probe_zai()),
        _run_probe("qdrant", _probe_qdrant(), timeout=_QDRANT_PROBE_TIMEOUT),
        _run_probe("gemini", _probe_gemini()),
    )
    services = dict(raw)
    all_healthy = all(s["status"] == "healthy" for s in services.values())

    return {
        "status": "healthy" if all_healthy else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": services,
        "version": "0.1.0",
    }
