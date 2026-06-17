"""Health-check and smoke tests for the Virtual Professor API.

The health endpoint probes all backend services concurrently. In the test
environment no external services are available, so every probe returns
``unhealthy`` and the overall status is ``degraded``.
"""

import pytest


@pytest.mark.asyncio
async def test_health_endpoint(async_client):
    """GET /health should return 200 with the enhanced status payload."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    body = response.json()

    # The response shape is always the same regardless of which services are up
    assert body["status"] in ("healthy", "degraded")
    assert "timestamp" in body
    assert body["version"] == "0.1.0"

    services = body["services"]
    assert set(services.keys()) == {"postgres", "redis", "qdrant", "ollama", "kokoro"}

    for service_name, info in services.items():
        assert info["status"] in ("healthy", "unhealthy")
        if info["status"] == "healthy":
            assert "latency_ms" in info
            assert isinstance(info["latency_ms"], float)
        else:
            assert "error" in info
            assert isinstance(info["error"], str)


@pytest.mark.asyncio
async def test_professors_list_empty(async_client):
    """GET /professors should return an empty list initially."""
    response = await async_client.get("/professors")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_health_response_time(async_client):
    """Health endpoint should respond in under 1s (5 concurrent failing probes)."""
    import time

    start = time.perf_counter()
    await async_client.get("/health")
    elapsed = (time.perf_counter() - start) * 1000
    assert elapsed < 1000, f"Health check took {elapsed:.1f}ms — expected <1000ms"


# ── Healthy / degraded simulation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_all_healthy(async_client):
    """GIVEN all backend services respond successfully
    WHEN GET /health
    THEN the overall status SHALL be 'healthy'.
    """
    from unittest.mock import AsyncMock, patch

    # Each probe mock returns a healthy status dict
    with (
        patch("routers.health._probe_postgres", new_callable=AsyncMock, return_value={"status": "healthy"}),
        patch("routers.health._probe_redis", new_callable=AsyncMock, return_value={"status": "healthy"}),
        patch("routers.health._probe_qdrant", new_callable=AsyncMock, return_value={"status": "healthy"}),
        patch("routers.health._probe_ollama", new_callable=AsyncMock, return_value={"status": "healthy"}),
        patch("routers.health._probe_kokoro", new_callable=AsyncMock, return_value={"status": "healthy"}),
    ):
        response = await async_client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    for svc in ("postgres", "redis", "qdrant", "ollama", "kokoro"):
        assert body["services"][svc]["status"] == "healthy"
        assert "latency_ms" in body["services"][svc]


@pytest.mark.asyncio
async def test_health_one_down(async_client):
    """GIVEN one backend service (redis) is down
    WHEN GET /health
    THEN the overall status SHALL be 'degraded'.
    """
    from unittest.mock import AsyncMock, patch

    with (
        patch("routers.health._probe_postgres", new_callable=AsyncMock, return_value={"status": "healthy"}),
        # Redis probe raises → _run_probe catches and returns "unhealthy"
        patch("routers.health._probe_redis", new_callable=AsyncMock, side_effect=Exception("Redis connection refused")),
        patch("routers.health._probe_qdrant", new_callable=AsyncMock, return_value={"status": "healthy"}),
        patch("routers.health._probe_ollama", new_callable=AsyncMock, return_value={"status": "healthy"}),
        patch("routers.health._probe_kokoro", new_callable=AsyncMock, return_value={"status": "healthy"}),
    ):
        response = await async_client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"]["postgres"]["status"] == "healthy"
    assert body["services"]["redis"]["status"] == "unhealthy"
    assert "error" in body["services"]["redis"]


@pytest.mark.asyncio
async def test_health_no_auth_required(async_client):
    """GET /health SHALL return 200 without any Authorization header.

    The health endpoint must be publicly accessible for monitoring
    and load-balancer probes.
    """
    response = await async_client.get("/health", headers={})
    assert response.status_code == 200
    # Verify it's a proper health response, not an auth error
    assert "status" in response.json()
