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
    assert "EMBED_PROVIDER" in text
    assert "gemini-embedding-001" in text
    assert "GOOGLE_API_KEY" in text
    assert "plan: free" in text
    assert "EMBED_RESUME_ON_STARTUP" in text
    assert "MALLOC_ARENA_MAX" in text
    assert "DATABASE_URL" in text
    assert "QDRANT_URL" in text
    assert "QDRANT_API_KEY" in text
    assert "NEXT_PUBLIC_API_URL" in text
    assert "dockerfilePath: ./services/frontend/Dockerfile.prod" in text


def test_requirements_use_qdrant_not_pgvector():
    path = _find_repo_file("requirements.txt")
    if path is None:
        pytest.skip("requirements.txt not available from this test path")
    text = path.read_text(encoding="utf-8")
    assert "qdrant-client" in text
    assert "llama-index-vector-stores-qdrant" in text
    assert "google-genai" in text
    assert "fastembed" not in text
    assert "pgvector" not in text


def test_compose_and_env_example_target_qdrant_cloud():
    compose = _find_repo_file("docker-compose.yml")
    example = _find_repo_file(".env.example")
    if compose is None or example is None:
        pytest.skip("compose/.env.example not available from this test path")
    compose_text = compose.read_text(encoding="utf-8")
    example_text = example.read_text(encoding="utf-8")
    assert "pgvector/pgvector" not in compose_text
    assert "image: postgres:16" in compose_text
    assert "QDRANT_URL=${QDRANT_URL}" in compose_text
    assert "QDRANT_API_KEY=${QDRANT_API_KEY}" in compose_text
    assert "QDRANT_URL=" in example_text
    assert "QDRANT_API_KEY=" in example_text
    assert "GOOGLE_API_KEY=" in example_text
    assert "gemini-embedding-001" in example_text
    assert "cloud.qdrant.io" in example_text


def test_api_dockerfile_omits_torch_for_render_ram():
    path = None
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "Dockerfile"
        if candidate.is_file() and (parent / "requirements.txt").is_file():
            path = candidate
            break
    if path is None:
        pytest.skip("backend Dockerfile not available from this test path")
    text = path.read_text(encoding="utf-8")
    assert "extra-index-url" not in text
    assert "grep -vE" in text
    assert "--workers 1" in text
    assert "FASTEMBED_CACHE_PATH" not in text
    assert "TextEmbedding" not in text


def test_vercel_config_lives_in_frontend():
    path = _find_repo_file("vercel.json")
    if path is None:
        pytest.skip("vercel.json not available from this test path")
    assert '"framework": "nextjs"' in path.read_text(encoding="utf-8")
