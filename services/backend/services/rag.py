import logging

from llama_index.core.schema import NodeWithScore, TextNode
from sqlalchemy import select

from core.config import settings
from core.database import AsyncSessionLocal
from models.db import DocumentChunk
from models.schemas import ContextChunk
from services import langfuse as langfuse_helpers
from services.embeddings import get_embed_model
from services.reranker import BGELocalReranker

log = logging.getLogger(__name__)

# ── Reranker singleton ──────────────────────────────────────────────────────

_reranker_instance: BGELocalReranker | None = None


def _reset_reranker() -> None:
    """Reset the reranker singleton (exposed for test isolation).

    Call this between tests that manipulate ``_get_reranker`` with mocks.
    """
    global _reranker_instance
    _reranker_instance = None


def _get_reranker() -> BGELocalReranker:
    """Return the application-wide reranker singleton (lazy-init)."""
    global _reranker_instance
    if _reranker_instance is None:
        _reranker_instance = BGELocalReranker(
            model=settings.reranker_model,
            top_n=settings.rag_retrieval_top_k,
            device=settings.reranker_device,
        )
    return _reranker_instance


# ── Core pipeline ───────────────────────────────────────────────────────────


def filter_nodes_by_score(nodes: list[NodeWithScore], min_score: float) -> list[NodeWithScore]:
    """Filter nodes by minimum relevance score.

    Returns only nodes where ``node.score >= min_score``.
    Returns empty list if no nodes pass the threshold.
    """
    return [node for node in nodes if node.score is not None and node.score >= min_score]


async def retrieve_context(
    query: str,
    professor_collection: str,
    top_k: int | None = None,
    min_score: float | None = None,
    trace_id: str | None = None,
    trace: "LangfuseTrace | None" = None,
) -> list[ContextChunk]:
    """Retrieve the top-k relevant chunks from the professor's pgvector store.

    Embeddings live in the ``document_chunks`` table; retrieval is a plain
    cosine-similarity search over that table. Retrieved nodes are filtered by
    ``min_score`` (default: ``settings.rag_min_relevance_score``). Returns an
    empty list if nothing meets the threshold or the store errors.
    """
    embed_model = get_embed_model()
    query_embedding = embed_model.get_query_embedding(query)
    limit = top_k or settings.rag_retrieval_top_k
    relevance_floor = settings.rag_min_relevance_score if min_score is None else min_score

    try:
        async with AsyncSessionLocal() as db:
            distance = DocumentChunk.embedding.cosine_distance(query_embedding)
            stmt = (
                select(
                    DocumentChunk,
                    (1 - distance).label("score"),
                )
                .where(DocumentChunk.professor_collection == professor_collection)
                .order_by(distance)
                .limit(limit)
            )
            rows = (await db.execute(stmt)).all()
    except Exception as exc:
        log.warning("pgvector retrieval error: %s", exc)
        return []

    nodes: list[NodeWithScore] = []
    for chunk, score in rows:
        metadata = chunk.chunk_metadata or {}
        document_id = str(chunk.document_id)
        source_document = metadata.get("source_filename", "") or document_id
        node = TextNode(
            text=chunk.text,
            metadata={
                "document_id": document_id,
                "professor_collection": chunk.professor_collection,
                "source_filename": source_document,
                "page_label": chunk.page_label,
            },
        )
        nodes.append(NodeWithScore(node=node, score=float(score)))

    # ── Reranker step ────────────────────────────────────────────────────
    if settings.reranker_type != "none":
        async with langfuse_helpers.create_span(trace, "reranker") as span:
            try:
                if span is not None:
                    span.update(
                        input={
                            "query": query,
                            "chunk_count": len(nodes),
                            "scores": [node.score for node in nodes],
                        }
                    )
                reranker = _get_reranker()
                indices = reranker.rerank(query, nodes)
                nodes = [nodes[i] for i in indices]
                if span is not None:
                    span.update(
                        output={
                            "order": [node.get_content() for node in nodes],
                            "scores": [node.score for node in nodes],
                        }
                    )
            except Exception as exc:
                if span is not None:
                    span.update(level="ERROR", status_message=str(exc))
                log.warning("Reranker failed: %s", exc)
                raise

    # Unconditional truncation to reranker_top_n (regardless of reranker status)
    nodes = nodes[: settings.reranker_top_n]

    filtered = filter_nodes_by_score(nodes, relevance_floor)
    return [
        ContextChunk(
            text=node.get_content(),
            source_document=node.metadata.get(
                "source_filename", node.metadata.get("document_id", "")
            ),
            source_document_id=node.metadata.get("document_id", ""),
            source_page=node.metadata.get("page_label", None),
            trace_id=trace_id,
            score=node.score,
        )
        for node in filtered
    ]