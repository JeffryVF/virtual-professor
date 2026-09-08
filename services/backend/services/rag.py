"""Retrieve professor knowledge from Cloudflare AI Search."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core import cloudflare
from core.config import settings
from models.schemas import ContextChunk

log = logging.getLogger(__name__)


@dataclass
class ScoredChunk:
    text: str
    score: float | None
    source_filename: str
    document_id: str
    page_label: str | None = None


def filter_chunks_by_score(chunks: list[ScoredChunk], min_score: float) -> list[ScoredChunk]:
    """Keep chunks whose score meets the configured floor."""
    return [chunk for chunk in chunks if chunk.score is not None and chunk.score >= min_score]


# Kept as an alias so older tests that import the LlamaIndex-era name still work.
filter_nodes_by_score = filter_chunks_by_score


def _chunk_text(raw: dict) -> str:
    content = raw.get("text") or raw.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


def _parse_search_chunk(raw: dict) -> ScoredChunk:
    item = raw.get("item") if isinstance(raw.get("item"), dict) else {}
    key = str(item.get("key") or raw.get("filename") or "")
    _collection, document_id, filename = cloudflare.parse_item_key(key)
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    source = (
        str(metadata.get("filename") or filename or document_id or key)
    )
    score = raw.get("score")
    if score is None:
        details = raw.get("scoring_details") if isinstance(raw.get("scoring_details"), dict) else {}
        score = details.get("reranking_score") or details.get("vector_score")
    page = metadata.get("page_label") or raw.get("page") or None
    return ScoredChunk(
        text=_chunk_text(raw),
        score=float(score) if score is not None else None,
        source_filename=source,
        document_id=document_id or str(metadata.get("document_id") or ""),
        page_label=str(page) if page is not None else None,
    )


async def retrieve_context(
    query: str,
    professor_collection: str,
    top_k: int | None = None,
    min_score: float | None = None,
    trace_id: str | None = None,
    trace: object | None = None,
) -> list[ContextChunk]:
    """Retrieve the top-k relevant chunks for a professor from Cloudflare AI Search."""
    del trace  # Langfuse traces still wrap the caller; retrieval itself is one API call.
    if not cloudflare.is_configured():
        log.warning("Cloudflare AI Search is not configured; returning no context")
        return []

    relevance_floor = settings.rag_min_relevance_score if min_score is None else min_score
    try:
        raw_chunks = await cloudflare.search(
            query,
            folder_prefix=professor_collection,
            max_num_results=top_k,
        )
    except Exception as exc:
        log.warning("Cloudflare AI Search retrieval error: %s", exc)
        return []

    chunks = [_parse_search_chunk(raw) for raw in raw_chunks if isinstance(raw, dict)]
    filtered = filter_chunks_by_score(chunks, relevance_floor)
    return [
        ContextChunk(
            text=chunk.text,
            source_document=chunk.source_filename or chunk.document_id,
            source_document_id=chunk.document_id,
            source_page=chunk.page_label,
            trace_id=trace_id,
            score=chunk.score,
        )
        for chunk in filtered
        if chunk.text.strip()
    ]


async def list_document_chunks(
    professor_collection: str,
    document_id: str,
    filename: str,
    *,
    offset: int = 0,
    limit: int = 50,
) -> list[ScoredChunk]:
    """Return indexed chunks for one document (admin viewer)."""
    if not cloudflare.is_configured():
        return []
    try:
        raw_chunks = await cloudflare.search(
            filename or "document",
            folder_prefix=f"{professor_collection}/{document_id}",
            max_num_results=min(offset + limit, 50),
        )
    except Exception as exc:
        log.warning("Cloudflare AI Search list chunks error: %s", exc)
        return []
    chunks = [_parse_search_chunk(raw) for raw in raw_chunks if isinstance(raw, dict)]
    return chunks[offset : offset + limit]
