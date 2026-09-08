"""Ensure pgvector is usable and document embeddings match EMBED_DIM."""

from __future__ import annotations

import logging
import re

from sqlalchemy import text

log = logging.getLogger(__name__)

_VECTOR_DIM_RE = re.compile(r"vector\((\d+)\)", re.IGNORECASE)


def parse_vector_dimensions(coltype: str | None) -> int | None:
    """Return the dimension from a PostgreSQL ``format_type`` string, if present."""
    if not coltype:
        return None
    match = _VECTOR_DIM_RE.search(coltype)
    if match:
        return int(match.group(1))
    return None


def _is_postgres(conn) -> bool:
    name = getattr(getattr(conn, "dialect", None), "name", "")
    return name in {"postgresql", "postgres"}


async def ensure_vector_extension(conn) -> None:
    """Create the ``vector`` extension when connected to PostgreSQL."""
    if not _is_postgres(conn):
        return
    try:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as exc:
        log.warning(
            "Could not CREATE EXTENSION vector (enable it in Supabase if missing): %s",
            exc,
        )


async def ensure_embedding_dimension(conn, embed_dim: int) -> bool:
    """Resize ``document_chunks.embedding`` to ``embed_dim``.

    Returns True when existing rows were truncated because the column size
    did not match. ``create_all`` never alters an existing vector column, so
    a leftover VECTOR(1024) table would reject FastEmbed's 384-d vectors.
    """
    if not _is_postgres(conn):
        return False

    result = await conn.execute(
        text(
            """
            SELECT format_type(a.atttypid, a.atttypmod) AS coltype
            FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON a.attrelid = c.oid
            JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = current_schema()
              AND c.relname = 'document_chunks'
              AND a.attname = 'embedding'
              AND a.attnum > 0
              AND NOT a.attisdropped
            """
        )
    )
    row = result.first()
    if row is None:
        return False

    coltype = row[0] if not hasattr(row, "coltype") else row.coltype
    actual = parse_vector_dimensions(coltype)
    if actual == embed_dim:
        return False

    dim = int(embed_dim)
    log.warning(
        "document_chunks.embedding is %s, expected vector(%s). "
        "Clearing old vectors and resizing the column.",
        coltype,
        dim,
    )
    await conn.execute(text("TRUNCATE TABLE document_chunks"))
    await conn.execute(
        text(f"ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector({dim})")
    )
    return True
