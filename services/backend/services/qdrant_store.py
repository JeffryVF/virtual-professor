"""Professor collections and document points in Qdrant Cloud."""

from __future__ import annotations

import json
import logging

from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    VectorParams,
)

from core.config import settings
from core.qdrant import get_qdrant_client

log = logging.getLogger(__name__)

DOCUMENT_ID_KEY = "document_id"
# LlamaIndex overwrites payload ``document_id`` with ``node.ref_doc_id``.
# Keep a stable key so delete/list still match the Postgres document UUID.
VP_DOCUMENT_ID_KEY = "vp_document_id"


def _document_filter(document_id: str) -> Filter:
    """Match LlamaIndex payload layouts (top-level, nested, or vp_document_id)."""
    match = MatchValue(value=str(document_id))
    return Filter(
        should=[
            FieldCondition(key=DOCUMENT_ID_KEY, match=match),
            FieldCondition(key=f"metadata.{DOCUMENT_ID_KEY}", match=match),
            FieldCondition(key=VP_DOCUMENT_ID_KEY, match=match),
            FieldCondition(key=f"metadata.{VP_DOCUMENT_ID_KEY}", match=match),
        ]
    )


def collection_vector_size(info) -> int | None:
    """Read the unnamed (or first named) vector size from a Qdrant collection."""
    params = getattr(getattr(info, "config", None), "params", None)
    vectors = getattr(params, "vectors", None) if params is not None else None
    if vectors is None:
        return None
    size = getattr(vectors, "size", None)
    if size is not None:
        return int(size)
    if isinstance(vectors, dict):
        for named in vectors.values():
            named_size = getattr(named, "size", None)
            if named_size is not None:
                return int(named_size)
    return None


def ensure_collection(client, collection_name: str) -> bool:
    """Create a cosine collection sized to EMBED_DIM when it does not exist.

    Recreates the collection if an older embedding size is still stored
    (for example after switching MiniLM 384-d to Gemini 768-d).
    Returns True when an existing collection was deleted and recreated.
    """
    existing = {c.name for c in client.get_collections().collections}
    wiped = False
    if collection_name in existing:
        info = client.get_collection(collection_name)
        current = collection_vector_size(info)
        if current == settings.embed_dim:
            return False
        log.warning(
            "Recreating Qdrant collection %s: vector size %s != EMBED_DIM %s. "
            "Sibling documents will be re-embedded with Gemini.",
            collection_name,
            current,
            settings.embed_dim,
        )
        client.delete_collection(collection_name)
        wiped = True
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=settings.embed_dim, distance=Distance.COSINE),
    )
    for field_name in (DOCUMENT_ID_KEY, VP_DOCUMENT_ID_KEY):
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception as exc:
            log.warning("Could not index %s on %s: %s", field_name, collection_name, exc)
    return wiped


def delete_collection(collection_name: str) -> None:
    client = get_qdrant_client()
    try:
        existing = {c.name for c in client.get_collections().collections}
        if collection_name in existing:
            client.delete_collection(collection_name=collection_name)
    finally:
        client.close()


def delete_document_points(collection_name: str, document_id: str) -> None:
    client = get_qdrant_client()
    try:
        existing = {c.name for c in client.get_collections().collections}
        if collection_name not in existing:
            return
        client.delete(
            collection_name=collection_name,
            points_selector=_document_filter(document_id),
        )
    except UnexpectedResponse as exc:
        if getattr(exc, "status_code", None) != 404:
            raise
    finally:
        client.close()


def count_collection_points(collection_name: str) -> int:
    client = get_qdrant_client()
    try:
        existing = {c.name for c in client.get_collections().collections}
        if collection_name not in existing:
            return 0
        result = client.count(collection_name=collection_name, exact=True)
        return int(result.count)
    except UnexpectedResponse as exc:
        if getattr(exc, "status_code", None) == 404:
            return 0
        raise
    finally:
        client.close()


def list_document_points(collection_name: str, document_id: str) -> list[dict]:
    """Return stored chunks for one document, ordered by chunk_index."""
    client = get_qdrant_client()
    try:
        existing = {c.name for c in client.get_collections().collections}
        if collection_name not in existing:
            return []
        records, _offset = client.scroll(
            collection_name=collection_name,
            scroll_filter=_document_filter(document_id),
            with_payload=True,
            with_vectors=False,
            limit=10_000,
        )
    except UnexpectedResponse as exc:
        if getattr(exc, "status_code", None) == 404:
            return []
        raise
    finally:
        client.close()

    chunks: list[dict] = []
    for idx, record in enumerate(records):
        payload = record.payload or {}
        chunks.append(_chunk_from_payload(payload, fallback_index=idx))
    chunks.sort(key=lambda item: item["chunk_index"])
    return chunks


def _chunk_from_payload(payload: dict, fallback_index: int) -> dict:
    text = str(payload.get("text") or "")
    if not text:
        raw = payload.get("_node_content")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                text = str(parsed.get("text") or "")
            except json.JSONDecodeError:
                text = raw
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    page_label = (
        payload.get("page_label")
        or metadata.get("page_label")
        or payload.get("page_number")
    )
    chunk_index = payload.get("chunk_index", metadata.get("chunk_index", fallback_index))
    try:
        chunk_index = int(chunk_index)
    except (TypeError, ValueError):
        chunk_index = fallback_index
    return {
        "chunk_index": chunk_index,
        "text": text,
        "page_label": None if page_label is None else str(page_label),
    }
