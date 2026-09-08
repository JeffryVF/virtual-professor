"""Tests for pgvector schema alignment on startup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.vector_schema import (
    ensure_embedding_dimension,
    ensure_vector_extension,
    parse_vector_dimensions,
)


def test_parse_vector_dimensions_reads_typmod():
    assert parse_vector_dimensions("vector(1024)") == 1024
    assert parse_vector_dimensions("vector(384)") == 384
    assert parse_vector_dimensions("public.vector(384)") == 384
    assert parse_vector_dimensions("vector") is None
    assert parse_vector_dimensions(None) is None


@pytest.mark.asyncio
async def test_ensure_vector_extension_skips_sqlite():
    conn = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"), execute=AsyncMock())
    await ensure_vector_extension(conn)
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_embedding_dimension_skips_sqlite():
    conn = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"), execute=AsyncMock())
    assert await ensure_embedding_dimension(conn, 384) is False
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_embedding_dimension_noops_when_already_384():
    result = MagicMock()
    result.first.return_value = ("vector(384)",)
    conn = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        execute=AsyncMock(return_value=result),
    )
    assert await ensure_embedding_dimension(conn, 384) is False
    assert conn.execute.await_count == 1


@pytest.mark.asyncio
async def test_ensure_embedding_dimension_resizes_1024_to_384():
    result = MagicMock()
    result.first.return_value = ("vector(1024)",)
    conn = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        execute=AsyncMock(return_value=result),
    )
    assert await ensure_embedding_dimension(conn, 384) is True
    sqls = [" ".join(str(call.args[0]).split()) for call in conn.execute.await_args_list]
    assert any("TRUNCATE TABLE document_chunks" in sql for sql in sqls)
    assert any("TYPE vector(384)" in sql for sql in sqls)


@pytest.mark.asyncio
async def test_ensure_embedding_dimension_skips_missing_table():
    result = MagicMock()
    result.first.return_value = None
    conn = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        execute=AsyncMock(return_value=result),
    )
    assert await ensure_embedding_dimension(conn, 384) is False
    assert conn.execute.await_count == 1
