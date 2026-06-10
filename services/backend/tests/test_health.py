"""Basic health-check and smoke tests for the Virtual Professor API."""

import pytest


@pytest.mark.asyncio
async def test_health_endpoint(async_client):
    """GET /health should return 200 with status ok."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_professors_list_empty(async_client):
    """GET /professors should return an empty list initially."""
    response = await async_client.get("/professors")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_health_response_time(async_client):
    """Health endpoint should respond in under 100ms."""
    import time

    start = time.perf_counter()
    await async_client.get("/health")
    elapsed = (time.perf_counter() - start) * 1000
    assert elapsed < 100, f"Health check took {elapsed:.1f}ms — expected <100ms"
