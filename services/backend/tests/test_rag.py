"""Tests for RAG relevance filtering and Cloudflare retrieval mapping."""

from unittest.mock import AsyncMock, patch

import pytest

from models.schemas import ContextChunk
from services.rag import ScoredChunk, filter_chunks_by_score, retrieve_context


def _chunk(text: str, score: float | None, **kwargs) -> ScoredChunk:
    return ScoredChunk(
        text=text,
        score=score,
        source_filename=kwargs.get("source_filename", "doc.pdf"),
        document_id=kwargs.get("document_id", "doc-1"),
        page_label=kwargs.get("page_label"),
    )


class TestRagRetrieveScaleConfig:
    def test_rag_retrieval_top_k_defaults_to_8(self):
        from core.config import Settings as RagSettings

        s = RagSettings()
        assert s.rag_retrieval_top_k == 8


class TestFilterChunksByScore:
    def test_filters_low_score_chunks(self):
        chunks = [
            _chunk("relevant A", 0.92),
            _chunk("relevant B", 0.88),
            _chunk("relevant C", 0.81),
            _chunk("irrelevant D", 0.67),
            _chunk("irrelevant E", 0.42),
        ]
        result = filter_chunks_by_score(chunks, 0.75)
        assert len(result) == 3
        assert all(c.text.startswith("relevant") for c in result)

    def test_no_chunk_meets_threshold(self):
        result = filter_chunks_by_score(
            [_chunk("barely relevant", 0.63), _chunk("low relevance", 0.41)],
            0.75,
        )
        assert result == []

    def test_threshold_zero_passes_all(self):
        result = filter_chunks_by_score(
            [_chunk("low A", 0.12), _chunk("low B", 0.05), _chunk("medium C", 0.55)],
            0.0,
        )
        assert len(result) == 3

    def test_empty_list_returns_empty(self):
        assert filter_chunks_by_score([], 0.75) == []

    def test_score_exactly_at_threshold(self):
        result = filter_chunks_by_score([_chunk("at threshold", 0.75)], 0.75)
        assert len(result) == 1

    def test_score_just_below_threshold(self):
        result = filter_chunks_by_score([_chunk("just below", 0.749)], 0.75)
        assert result == []

    def test_none_scores_handled_as_low(self):
        result = filter_chunks_by_score([_chunk("no score", None)], 0.0)
        assert result == []


def _search_payload(chunks: list[ScoredChunk]) -> list[dict]:
    payload = []
    for chunk in chunks:
        payload.append(
            {
                "text": chunk.text,
                "score": chunk.score,
                "item": {
                    "key": f"test_collection/{chunk.document_id}/{chunk.source_filename}",
                    "metadata": {"filename": chunk.source_filename},
                },
            }
        )
    return payload


@pytest.mark.asyncio
async def test_retrieve_context_applies_filter_integration():
    chunks = [_chunk("high score chunk", 0.92), _chunk("low score chunk", 0.30)]
    with (
        patch("services.rag.cloudflare.is_configured", return_value=True),
        patch("services.rag.cloudflare.search", new=AsyncMock(return_value=_search_payload(chunks))),
        patch("core.config.settings.rag_min_relevance_score", 0.0),
    ):
        result = await retrieve_context(
            query="test query",
            professor_collection="test_collection",
            top_k=8,
        )

    assert len(result) == 2
    assert {item.text for item in result} == {"high score chunk", "low score chunk"}


@pytest.mark.asyncio
async def test_retrieve_context_skips_when_unconfigured():
    with patch("services.rag.cloudflare.is_configured", return_value=False):
        result = await retrieve_context("q", "test_collection")
    assert result == []


@pytest.mark.asyncio
async def test_retrieve_context_returns_list_of_contextchunk():
    chunks = [
        _chunk("Neural networks use backpropagation.", 0.92, source_filename="lecture.pdf", document_id="uuid-1"),
        _chunk("Transformers use attention.", 0.88, source_filename="paper.pdf", document_id="uuid-2"),
        _chunk("CNNs are for images.", 0.81, source_filename="slides.pdf", document_id="uuid-3"),
    ]
    with (
        patch("services.rag.cloudflare.is_configured", return_value=True),
        patch("services.rag.cloudflare.search", new=AsyncMock(return_value=_search_payload(chunks))),
        patch("core.config.settings.rag_min_relevance_score", 0.0),
    ):
        result = await retrieve_context("test", "test_collection", top_k=8)

    assert len(result) == 3
    for item in result:
        assert isinstance(item, ContextChunk)
    assert result[0].source_document == "lecture.pdf"
    assert result[1].source_document == "paper.pdf"
    assert result[2].source_document == "slides.pdf"


@pytest.mark.asyncio
async def test_empty_retrieval_returns_empty_list():
    with (
        patch("services.rag.cloudflare.is_configured", return_value=True),
        patch("services.rag.cloudflare.search", new=AsyncMock(return_value=[])),
    ):
        result = await retrieve_context("test", "nonexistent", top_k=8)
    assert result == []


@pytest.mark.asyncio
async def test_source_filename_present_uses_it():
    chunks = [_chunk("content", 0.9, source_filename="report.pdf", document_id="uuid-1")]
    with (
        patch("services.rag.cloudflare.is_configured", return_value=True),
        patch("services.rag.cloudflare.search", new=AsyncMock(return_value=_search_payload(chunks))),
        patch("core.config.settings.rag_min_relevance_score", 0.0),
    ):
        result = await retrieve_context("test", "test_collection")
    assert result[0].source_document == "report.pdf"


@pytest.mark.asyncio
async def test_no_source_filename_falls_back_to_document_id():
    raw = [{"text": "legacy content", "score": 0.9, "item": {"key": "prof/fallback-uuid-999/"}}]
    with (
        patch("services.rag.cloudflare.is_configured", return_value=True),
        patch("services.rag.cloudflare.search", new=AsyncMock(return_value=raw)),
        patch("core.config.settings.rag_min_relevance_score", 0.0),
    ):
        result = await retrieve_context("test", "test_collection")
    assert len(result) == 1
    assert result[0].source_document == "fallback-uuid-999"


class TestContextChunkModel:
    def test_required_fields_only(self):
        chunk = ContextChunk(
            text="Neural networks use backpropagation.",
            source_document="lecture.pdf",
            source_document_id="uuid-123",
        )
        assert chunk.source_page is None
        assert chunk.trace_id is None

    def test_all_fields_populated(self):
        chunk = ContextChunk(
            text="Transformer models use attention mechanisms.",
            source_document="paper.pdf",
            source_document_id="uuid-456",
            source_page="42",
            trace_id="trace-789",
        )
        assert chunk.source_page == "42"
        assert chunk.trace_id == "trace-789"


@pytest.mark.asyncio
async def test_empty_query_returns_results():
    chunks = [_chunk("some content", 0.9)]
    with (
        patch("services.rag.cloudflare.is_configured", return_value=True),
        patch("services.rag.cloudflare.search", new=AsyncMock(return_value=_search_payload(chunks))),
        patch("core.config.settings.rag_min_relevance_score", 0.0),
    ):
        result = await retrieve_context("", "test_collection")
    assert result[0].text == "some content"


@pytest.mark.asyncio
async def test_very_long_query_does_not_crash():
    chunks = [_chunk("long query handled", 0.9)]
    with (
        patch("services.rag.cloudflare.is_configured", return_value=True),
        patch("services.rag.cloudflare.search", new=AsyncMock(return_value=_search_payload(chunks))),
        patch("core.config.settings.rag_min_relevance_score", 0.0),
    ):
        result = await retrieve_context("test " * 500, "test_collection")
    assert result[0].text == "long query handled"
