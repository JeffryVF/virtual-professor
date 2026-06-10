"""
Async test fixtures for Virtual Professor API.

External services (Ollama, Qdrant, Redis, Whisper, Kokoro, LiveAvatar)
are mocked to keep tests fast, deterministic, and dependency-free.
"""

import os
from typing import AsyncGenerator

import httpx
import pytest_asyncio
from fastapi import FastAPI

# ── Override settings BEFORE importing app modules ──────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")
os.environ.setdefault("OLLAMA_LLM_MODEL", "test-model")
os.environ.setdefault("OLLAMA_EMBED_MODEL", "test-embed")
os.environ.setdefault("WHISPER_URL", "http://localhost:9000")
os.environ.setdefault("KOKORO_URL", "http://localhost:8880")
os.environ.setdefault("LIVEAVATAR_API_KEY", "test-key")
os.environ.setdefault("LIVEAVATAR_API_URL", "http://localhost:8080")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("SESSION_MEMORY_MESSAGES", "10")
os.environ.setdefault("SESSION_TIMEOUT_MINUTES", "30")
# ─────────────────────────────────────────────────────────────────────────────

from main import app  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    """Create all tables once per test session.

    Runs before any test using the async client (which triggers DB queries).
    """
    from core.database import engine
    from models.db import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def async_app() -> FastAPI:
    """Return the FastAPI app instance with test settings."""
    return app


@pytest_asyncio.fixture
async def async_client(async_app: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create an async HTTP client for integration tests."""
    transport = httpx.ASGITransport(app=async_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def db_session():
    """Provide a clean DB session per test.

    Tables are already created by setup_database (session-scoped).
    This fixture yields a fresh session per test.
    """
    from core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session
