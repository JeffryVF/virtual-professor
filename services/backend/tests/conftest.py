"""
Async test fixtures for Virtual Professor API.

External services (Z.AI, Redis) and the LLM/TTS/RAG pipelines
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
os.environ.setdefault("QDRANT_API_KEY", "")
os.environ.setdefault("ZAI_API_KEY", "test-zai-key")
os.environ.setdefault("ZAI_LLM_MODEL", "glm-4.7-flash")
os.environ.setdefault("GOOGLE_API_KEY", "test-google-key")
os.environ.setdefault("EMBED_PROVIDER", "gemini")
os.environ.setdefault("EMBED_MODEL", "gemini-embedding-001")
os.environ.setdefault("EMBED_DIM", "768")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("SESSION_MEMORY_MESSAGES", "10")
os.environ.setdefault("SESSION_TIMEOUT_MINUTES", "30")
os.environ.setdefault("RAG_MIN_RELEVANCE_SCORE", "0.0")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing-only")
os.environ.setdefault("LANGFUSE_ENABLE", "false")
os.environ["CORS_ORIGINS"] = (
    '["https://virtual-professor-frontend.onrender.com","http://localhost:3000"]'
)
# ─────────────────────────────────────────────────────────────────────────────

from main import app  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
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


# ── Auth fixtures ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def student_user(db_session):
    """Create and return a test student user."""
    from dependencies.auth import hash_password
    from models.user import User

    user = User(
        email="student@test.com",
        hashed_password=hash_password("testpassword"),
        role="student",
        name="Test Student",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_user(db_session):
    """Create and return a test admin user."""
    from dependencies.auth import hash_password
    from models.user import User

    user = User(
        email="admin@test.com",
        hashed_password=hash_password("adminpassword"),
        role="admin",
        name="Test Admin",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def student_token(async_client, student_user):
    """Log in as student and return the access token."""
    response = await async_client.post(
        "/auth/login",
        json={"email": "student@test.com", "password": "testpassword"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest_asyncio.fixture
async def admin_token(async_client, admin_user):
    """Log in as admin and return the access token."""
    response = await async_client.post(
        "/auth/login",
        json={"email": "admin@test.com", "password": "adminpassword"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


# ── Header dict fixtures (convenience for tests that need full headers) ──────


@pytest_asyncio.fixture
async def auth_headers(student_token: str) -> dict[str, str]:
    """Return Authorization headers for a student user."""
    return {"Authorization": f"Bearer {student_token}"}


@pytest_asyncio.fixture
async def admin_headers(admin_token: str) -> dict[str, str]:
    """Return Authorization headers for an admin user."""
    return {"Authorization": f"Bearer {admin_token}"}


# ── Professor & Document fixtures (via admin API) ────────────────────────────


@pytest_asyncio.fixture
async def test_professor(async_client, admin_headers) -> dict:
    """Create a professor via the admin API and return its data.

    Uses the POST /admin/professors endpoint so the fixture exercises the
    real API path. Tests that need DB-level fixtures can still define their
    own module-level fixtures.

    Returns the full ProfessorResponse dict including ``id``, ``name``,
    ``collection``, etc.
    """
    response = await async_client.post(
        "/admin/professors",
        json={
            "name": "API Test Professor",
            "topic": "science",
            "language": "es",
            "avatar_id": "test-avatar",
            "system_prompt": "You are a science professor.",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, f"Professor creation failed: {response.text}"
    return response.json()


@pytest_asyncio.fixture
async def test_document(async_client, admin_headers, test_professor) -> dict:
    """Upload a test document via the admin API and return its data.

    Creates a professor first (via ``test_professor``), then uploads a small
    PDF file. The background ingestion task is mocked to avoid side effects.

    Returns the full DocumentResponse dict including ``id``, ``status``,
    ``filename``, etc.
    """
    from unittest.mock import patch

    with patch("routers.admin.ingest_document"):
        response = await async_client.post(
            f"/admin/professors/{test_professor['id']}/documents",
            files={"file": ("test.pdf", b"%PDF-1.4 test content", "application/pdf")},
            headers=admin_headers,
        )
    assert response.status_code == 201, f"Document upload failed: {response.text}"
    return response.json()
