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


async def _probe_cloudflare() -> dict:
    """Check Cloudflare AI Search via GET instance."""
    from core import cloudflare

    if not cloudflare.is_configured():
        raise RuntimeError("Cloudflare AI Search is not configured")
    await cloudflare.get_instance()
    return {"status": "healthy"}


# ── Probe runner with timeout ────────────────────────────────────────────────


async def _run_probe(name: str, probe_coro) -> tuple[str, dict]:
    """Run a single probe with timeout and latency measurement.

    Returns a (name, result_dict) tuple suitable for ``dict()``.
    """
    start = asyncio.get_event_loop().time()
    try:
        result = await asyncio.wait_for(probe_coro, timeout=_SERVICE_TIMEOUT)
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

    All probes run concurrently with ``asyncio.gather()`` and a 5-second
    timeout each. Returns ``healthy`` only when every service responds,
    ``degraded`` otherwise.
    """
    raw = await asyncio.gather(
        _run_probe("postgres", _probe_postgres()),
        _run_probe("redis", _probe_redis()),
        _run_probe("zai", _probe_zai()),
        _run_probe("cloudflare", _probe_cloudflare()),
    )
    services = dict(raw)
    all_healthy = all(s["status"] == "healthy" for s in services.values())

    return {
        "status": "healthy" if all_healthy else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": services,
        "version": "0.1.0",
    }
