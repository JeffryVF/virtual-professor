"""Tests for production config helpers used by Render/Vercel deploys."""

from pathlib import Path

import pytest

from core.config import Settings
from core.database import _async_database_url
from core.db_url import async_database_url


def _find_repo_file(name: str) -> Path | None:
    for parent in Path(__file__).resolve().parents:
        direct = parent / name
        if direct.is_file():
            return direct
        nested = parent / "services" / "frontend" / name
        if nested.is_file():
            return nested
    return None


def test_render_postgres_url_normalized_to_postgresql():
    assert (
        Settings._normalize_database_url("postgres://user:pass@host:5432/db")
        == "postgresql://user:pass@host:5432/db"
    )


def test_async_url_adds_asyncpg_and_rewrites_postgres_scheme():
    assert (
        _async_database_url("postgres://user:pass@host:5432/db")
        == "postgresql+asyncpg://user:pass@host:5432/db"
    )
    assert _async_database_url("sqlite+aiosqlite:///./test.db") == "sqlite+aiosqlite:///./test.db"
    assert async_database_url("postgres://user:pass@host:5432/db") == (
        "postgresql+asyncpg://user:pass@host:5432/db"
    )
    assert async_database_url("postgresql+asyncpg://user:pass@host:5432/db") == (
        "postgresql+asyncpg://user:pass@host:5432/db"
    )


def test_root_path_empty_on_render_slash_api_behind_nginx():
    assert Settings._normalize_root_path("") == ""
    assert Settings._normalize_root_path("/") == ""
    assert Settings._normalize_root_path("/api/") == "/api"
    assert Settings._normalize_root_path("api") == "/api"


def test_cors_origins_strip_trailing_slash_for_vercel():
    assert Settings._split_cors_origins("https://app.vercel.app/") == ["https://app.vercel.app"]
    assert Settings._split_cors_origins('["https://a.vercel.app/", "http://localhost:3000"]') == [
        "https://a.vercel.app",
        "http://localhost:3000",
    ]


def test_render_blueprint_declares_split_services():
    path = _find_repo_file("render.yaml")
    if path is None:
        pytest.skip("render.yaml not available from this test path")
    text = path.read_text(encoding="utf-8")
    for name in (
        "virtual-professor-api",
        "virtual-professor-frontend",
        "virtual-professor-redis",
    ):
        assert name in text
    assert "healthCheckPath: /health" in text
    assert "glm-4.7-flash" in text
    assert "CLOUDFLARE_ACCOUNT_ID" in text
    assert "CLOUDFLARE_API_TOKEN" in text
    assert "CLOUDFLARE_AI_SEARCH_INSTANCE" in text
    assert "plan: free" in text
    assert "EMBED_RESUME_ON_STARTUP" in text
    assert "DATABASE_URL" in text
    assert "NEXT_PUBLIC_API_URL" in text
    assert "dockerfilePath: ./services/frontend/Dockerfile.prod" in text


def test_api_dockerfile_stays_slim_without_local_rag_models():
    path = None
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "Dockerfile"
        if candidate.is_file() and (parent / "requirements.txt").is_file():
            path = candidate
            break
    if path is None:
        pytest.skip("backend Dockerfile not available from this test path")
    text = path.read_text(encoding="utf-8")
    assert "fastembed" not in text.lower()
    assert "torch" not in text.lower()
    assert "--workers 1" in text


def test_vercel_config_lives_in_frontend():
    path = _find_repo_file("vercel.json")
    if path is None:
        pytest.skip("vercel.json not available from this test path")
    assert '"framework": "nextjs"' in path.read_text(encoding="utf-8")
