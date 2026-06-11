"""Tests for RAG relevance score filtering.

Uses pure-function extraction to avoid mocking the full Qdrant pipeline.
Tests the core filtering logic independently per Extract-Before-Mock rule.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from core.config import settings
from services.rag import filter_nodes_by_score

# Import must fail initially — ContextChunk doesn't exist yet (RED phase)
from models.schemas import ContextChunk


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_node(text: str, score: float) -> NodeWithScore:
    """Create a NodeWithScore with known text and score."""
    return NodeWithScore(node=TextNode(text=text), score=score)


def _make_node_with_metadata(
    text: str, score: float, metadata: dict | None = None,
) -> NodeWithScore:
    """Create a NodeWithScore with text, score, and metadata."""
    node = TextNode(text=text)
    if metadata:
        for k, v in metadata.items():
            node.metadata[k] = v
    return NodeWithScore(node=node, score=score)


# ── Pure function tests (no mocks needed) ──────────────────────────────────


class TestFilterNodesByScore:
    """Tests for the pure extraction function filter_nodes_by_score."""

    def test_filters_low_score_chunks(self):
        """GIVEN threshold 0.75 AND scores [0.92, 0.88, 0.81, 0.67, 0.42]
        WHEN filter applied THEN only >= 0.75 are returned.
        """
        nodes = [
            _make_node("relevant A", 0.92),
            _make_node("relevant B", 0.88),
            _make_node("relevant C", 0.81),
            _make_node("irrelevant D", 0.67),
            _make_node("irrelevant E", 0.42),
        ]
        result = filter_nodes_by_score(nodes, 0.75)
        assert len(result) == 3
        assert all(n.node.text.startswith("relevant") for n in result)

    def test_no_chunk_meets_threshold(self):
        """GIVEN threshold 0.75 AND highest score 0.63
        WHEN filter applied THEN empty list.
        """
        nodes = [
            _make_node("barely relevant", 0.63),
            _make_node("low relevance", 0.41),
        ]
        result = filter_nodes_by_score(nodes, 0.75)
        assert result == []

    def test_threshold_zero_passes_all(self):
        """GIVEN threshold 0.0 (rollback scenario)
        WHEN filter applied THEN all pass.
        """
        nodes = [
            _make_node("low A", 0.12),
            _make_node("low B", 0.05),
            _make_node("medium C", 0.55),
        ]
        result = filter_nodes_by_score(nodes, 0.0)
        assert len(result) == 3

    def test_empty_list_returns_empty(self):
        """GIVEN empty input WHEN filter applied THEN empty."""
        assert filter_nodes_by_score([], 0.75) == []

    def test_score_exactly_at_threshold(self):
        """GIVEN score == threshold (>= semantics) THEN included."""
        nodes = [_make_node("at threshold", 0.75)]
        result = filter_nodes_by_score(nodes, 0.75)
        assert len(result) == 1

    def test_score_just_below_threshold(self):
        """GIVEN score just below threshold THEN excluded."""
        nodes = [_make_node("just below", 0.749)]
        result = filter_nodes_by_score(nodes, 0.75)
        assert result == []


# ── Integration test (settings-aware) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieve_context_applies_filter_integration():
    """Verify that retrieve_context applies the score filter end-to-end.

    Mocks the Qdrant client and retriever, injects nodes with known scores,
    and verifies only qualifying nodes are returned as content strings.
    """
    mock_retriever = MagicMock(spec=AsyncMock)
    nodes = [
        _make_node("high score chunk", 0.92),
        _make_node("low score chunk", 0.30),
    ]
    mock_retriever.aretrieve = AsyncMock(return_value=nodes)

    mock_index = MagicMock()
    mock_index.as_retriever.return_value = mock_retriever

    mock_collections = MagicMock()
    mock_col = MagicMock()
    mock_col.name = "prof_collection"
    mock_collections.collections = [mock_col]

    with (
        patch("services.rag.AsyncQdrantClient") as mock_qdrant_cls,
        patch("services.rag.QdrantVectorStore") as mock_store_cls,
        patch("services.rag.OllamaEmbedding") as mock_embed_cls,
        patch("services.rag.VectorStoreIndex.from_vector_store", return_value=mock_index),
    ):
        mock_client = MagicMock()
        mock_client.get_collections = AsyncMock(return_value=mock_collections)
        mock_qdrant_cls.return_value = mock_client

        from services.rag import retrieve_context

        result = await retrieve_context(
            query="test query",
            professor_collection="prof_collection",
            top_k=5,
        )

    # With default RAG_MIN_RELEVANCE_SCORE=0.0 in test env, ALL nodes pass
    assert len(result) == 2
    assert "high score chunk" in result[0].text or "high score chunk" in result[1].text


# ═════════════════════════════════════════════════════════════════════════════
# Phase 3 — Integration tests for RAG reranker
# ═════════════════════════════════════════════════════════════════════════════


class TestRetrieveContextWithReranker:
    """Integration tests for reranker step in retrieve_context().

    Each test patches the Qdrant pipeline to return controlled nodes, then
    configures the reranker (via settings mocks or SentenceTransformerRerank
    patch) to verify ordering, fallback, and top-k limiting.
    """

    # ── Shared Qdrant mock helper ────────────────────────────────────────

    _qdrant_patches = (
        "services.rag.AsyncQdrantClient",
        "services.rag.QdrantVectorStore",
        "services.rag.OllamaEmbedding",
        "services.rag.VectorStoreIndex.from_vector_store",
    )

    @staticmethod
    def _make_retriever_mock(nodes: list[NodeWithScore]) -> MagicMock:
        """Build a mock retriever that returns *nodes*."""
        mock_retriever = MagicMock(spec=AsyncMock)
        mock_retriever.aretrieve = AsyncMock(return_value=nodes)

        mock_index = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever

        mock_collections = MagicMock()
        mock_col = MagicMock()
        mock_col.name = "test_collection"
        mock_collections.collections = [mock_col]

        return mock_retriever, mock_index, mock_collections

    # ── 3.1 RED / 3.2 GREEN: reranker enabled re-orders before threshold ─

    @pytest.mark.asyncio
    async def test_reranker_enabled_reorders_before_filter(self):
        """GIVEN reranker_type=bge WHEN retrieve_context THEN chunks re-ordered."""
        from services.rag import _reset_reranker, retrieve_context  # noqa: PLC0415

        _reset_reranker()
        nodes = [
            _make_node("chunk A (originally first)", 0.2),
            _make_node("chunk B (originally second)", 0.9),
            _make_node("chunk C (originally third)", 0.5),
        ]
        mock_retriever, mock_index, mock_collections = (
            self._make_retriever_mock(nodes)
        )

        with (
            patch(self._qdrant_patches[0]) as mock_qdrant_cls,
            patch(self._qdrant_patches[1]),
            patch(self._qdrant_patches[2]),
            patch(self._qdrant_patches[3], return_value=mock_index),
            patch.object(settings, "reranker_type", "bge"),
            patch.object(settings, "reranker_top_n", 5),
            patch(
                "services.rag.BGELocalReranker"
            ) as mock_bge_cls,
        ):
            mock_client = MagicMock()
            mock_client.get_collections = AsyncMock(
                return_value=mock_collections
            )
            mock_qdrant_cls.return_value = mock_client

            # Build a mock BGELocalReranker instance
            mock_reranker = MagicMock()
            nodes_copy = list(nodes)

            def rerank_side_effect(query, chunks):
                # Re-order by score descending, update scores on originals
                sorted_chunks = sorted(
                    chunks, key=lambda n: n.score, reverse=True
                )
                indices = []
                for sc in sorted_chunks:
                    for i, nc in enumerate(nodes_copy):
                        if nc.node.text == sc.node.text:
                            indices.append(i)
                            nc.score = sc.score
                            break
                return indices

            mock_reranker.rerank.side_effect = rerank_side_effect
            mock_bge_cls.return_value = mock_reranker

            result = await retrieve_context(
                query="test",
                professor_collection="test_collection",
                top_k=5,
            )

        # B scored 0.9 → first, C scored 0.5 → second, A scored 0.2 → third
        assert len(result) == 3
        assert result[0].text == "chunk B (originally second)"
        assert result[1].text == "chunk C (originally third)"
        assert result[2].text == "chunk A (originally first)"

    # ── 3.1 RED / 3.2 GREEN: reranker disabled preserves original order ──

    @pytest.mark.asyncio
    async def test_reranker_disabled_preserves_original_order(self):
        """GIVEN reranker_type=none WHEN retrieve_context THEN order unchanged."""
        nodes = [
            _make_node("first chunk", 0.2),
            _make_node("second chunk", 0.9),
            _make_node("third chunk", 0.5),
        ]
        mock_retriever, mock_index, mock_collections = (
            self._make_retriever_mock(nodes)
        )

        with (
            patch(self._qdrant_patches[0]) as mock_qdrant_cls,
            patch(self._qdrant_patches[1]),
            patch(self._qdrant_patches[2]),
            patch(self._qdrant_patches[3], return_value=mock_index),
            patch.object(settings, "reranker_type", "none"),
        ):
            mock_client = MagicMock()
            mock_client.get_collections = AsyncMock(
                return_value=mock_collections
            )
            mock_qdrant_cls.return_value = mock_client

            from services.rag import retrieve_context  # noqa: PLC0415

            result = await retrieve_context(
                query="test",
                professor_collection="test_collection",
                top_k=5,
            )

        assert len(result) == 3
        assert result[0].text == "first chunk"
        assert result[1].text == "second chunk"
        assert result[2].text == "third chunk"

    # ── 3.1 RED / 3.2 GREEN: error fallback preserves order + logs ───────

    @pytest.mark.asyncio
    async def test_reranker_error_fallback_preserves_order(self):
        """GIVEN reranker raises on load WHEN retrieve_context THEN original order."""
        from services.rag import _reset_reranker, retrieve_context  # noqa: PLC0415

        _reset_reranker()
        nodes = [
            _make_node("stable A", 0.9),
            _make_node("stable B", 0.5),
        ]
        mock_retriever, mock_index, mock_collections = (
            self._make_retriever_mock(nodes)
        )

        with (
            patch(self._qdrant_patches[0]) as mock_qdrant_cls,
            patch(self._qdrant_patches[1]),
            patch(self._qdrant_patches[2]),
            patch(self._qdrant_patches[3], return_value=mock_index),
            patch.object(settings, "reranker_type", "bge"),
            patch.object(settings, "reranker_top_n", 5),
            patch(
                "services.rag.BGELocalReranker"
            ) as mock_bge_cls,
        ):
            mock_client = MagicMock()
            mock_client.get_collections = AsyncMock(
                return_value=mock_collections
            )
            mock_qdrant_cls.return_value = mock_client

            # BGELocalReranker init raises
            mock_bge_cls.side_effect = OSError("Model not available")

            result = await retrieve_context(
                query="test",
                professor_collection="test_collection",
                top_k=5,
            )

        # Original order preserved on error
        assert len(result) == 2
        assert result[0].text == "stable A"
        assert result[1].text == "stable B"

    # ── 3.3 RED / 3.4 GREEN: top_n limits reranked chunks ───────────────

    @pytest.mark.asyncio
    async def test_reranker_top_n_limits_reranked_chunks(self):
        """GIVEN reranker_top_n=2 AND 5 chunks WHEN retrieve_context THEN only 2 reranked."""
        from services.rag import _reset_reranker, retrieve_context  # noqa: PLC0415

        _reset_reranker()
        nodes = [
            _make_node("chunk 0", 0.1),
            _make_node("chunk 1", 0.9),
            _make_node("chunk 2", 0.8),
            _make_node("chunk 3", 0.7),
            _make_node("chunk 4", 0.6),
        ]
        mock_retriever, mock_index, mock_collections = (
            self._make_retriever_mock(nodes)
        )

        with (
            patch(self._qdrant_patches[0]) as mock_qdrant_cls,
            patch(self._qdrant_patches[1]),
            patch(self._qdrant_patches[2]),
            patch(self._qdrant_patches[3], return_value=mock_index),
            patch.object(settings, "reranker_type", "bge"),
            patch.object(settings, "reranker_top_n", 2),
            patch(
                "services.rag.BGELocalReranker"
            ) as mock_bge_cls,
        ):
            mock_client = MagicMock()
            mock_client.get_collections = AsyncMock(
                return_value=mock_collections
            )
            mock_qdrant_cls.return_value = mock_client

            mock_reranker = MagicMock()
            reranker_inputs = []

            def rerank_side_effect(query, chunks):
                reranker_inputs.append(
                    [n.node.text for n in chunks]
                )
                # Only 2 chunks are passed — return them in score order
                sorted_chunks = sorted(
                    chunks, key=lambda n: n.score, reverse=True
                )
                return [
                    next(
                        i
                        for i, c in enumerate(nodes)
                        if c.node.text == sc.node.text
                    )
                    for sc in sorted_chunks
                ]

            mock_reranker.rerank.side_effect = rerank_side_effect
            mock_bge_cls.return_value = mock_reranker

            result = await retrieve_context(
                query="test",
                professor_collection="test_collection",
                top_k=5,
            )

        # Only top 2 (by retrieval order: chunk 0, chunk 1) were passed to reranker
        assert len(reranker_inputs) == 1
        assert reranker_inputs[0] == ["chunk 0", "chunk 1"]
        # After reranking: chunk 1 (0.9) then chunk 0 (0.1),
        # then chunks 2, 3, 4 preserved in original order
        assert result[0].text == "chunk 1"
        assert result[1].text == "chunk 0"
        assert result[2].text == "chunk 2"
        assert result[3].text == "chunk 3"
        assert result[4].text == "chunk 4"


# ═════════════════════════════════════════════════════════════════════════════
# Phase 1 — ContextChunk Pydantic Model (CRIT-03)
# ═════════════════════════════════════════════════════════════════════════════


class TestContextChunkModel:
    """Tests for the ContextChunk Pydantic model.

    ContextChunk carries chunk content along with source document provenance
    through the RAG pipeline.
    """

    def test_required_fields_only(self):
        """GIVEN text, source_document, and source_document_id only
        WHEN ContextChunk is created
        THEN source_page and trace_id SHALL be None.
        """
        chunk = ContextChunk(
            text="Neural networks use backpropagation.",
            source_document="lecture.pdf",
            source_document_id="uuid-123",
        )
        assert chunk.text == "Neural networks use backpropagation."
        assert chunk.source_document == "lecture.pdf"
        assert chunk.source_document_id == "uuid-123"
        assert chunk.source_page is None
        assert chunk.trace_id is None

    def test_all_fields_populated(self):
        """GIVEN values for all five fields
        WHEN ContextChunk is created
        THEN every field SHALL match its constructor argument.
        """
        chunk = ContextChunk(
            text="Transformer models use attention mechanisms.",
            source_document="paper.pdf",
            source_document_id="uuid-456",
            source_page="42",
            trace_id="trace-789",
        )
        assert chunk.text == "Transformer models use attention mechanisms."
        assert chunk.source_document == "paper.pdf"
        assert chunk.source_document_id == "uuid-456"
        assert chunk.source_page == "42"
        assert chunk.trace_id == "trace-789"


# ═════════════════════════════════════════════════════════════════════════════
# Phase 3 — Typed Chunks + Fallback (CRIT-03)
# ═════════════════════════════════════════════════════════════════════════════


class TestRetrieveContextTypedChunks:
    """Tests for retrieve_context returning list[ContextChunk] with metadata."""

    _qdrant_patches = (
        "services.rag.AsyncQdrantClient",
        "services.rag.QdrantVectorStore",
        "services.rag.OllamaEmbedding",
        "services.rag.VectorStoreIndex.from_vector_store",
    )

    @staticmethod
    def _make_retriever_mock(nodes: list[NodeWithScore]) -> tuple:
        """Build a mock retriever that returns *nodes*."""
        mock_retriever = MagicMock(spec=AsyncMock)
        mock_retriever.aretrieve = AsyncMock(return_value=nodes)

        mock_index = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever

        mock_collections = MagicMock()
        mock_col = MagicMock()
        mock_col.name = "test_collection"
        mock_collections.collections = [mock_col]

        return mock_retriever, mock_index, mock_collections

    @pytest.mark.asyncio
    async def test_retrieve_context_returns_list_of_contextchunk(self):
        """GIVEN a query matching 3 Qdrant nodes with complete metadata
        WHEN retrieve_context() is called
        THEN the return SHALL be list[ContextChunk] of length 3
        AND each chunk SHALL have source_document matching node's source_filename.
        """
        nodes = [
            _make_node_with_metadata(
                "Neural networks use backpropagation.",
                0.92,
                {"source_filename": "lecture.pdf", "document_id": "uuid-1"},
            ),
            _make_node_with_metadata(
                "Transformers use attention.",
                0.88,
                {"source_filename": "paper.pdf", "document_id": "uuid-2"},
            ),
            _make_node_with_metadata(
                "CNNs are for images.",
                0.81,
                {"source_filename": "slides.pdf", "document_id": "uuid-3"},
            ),
        ]
        mock_retriever, mock_index, mock_collections = (
            self._make_retriever_mock(nodes)
        )

        with (
            patch(self._qdrant_patches[0]) as mock_qdrant_cls,
            patch(self._qdrant_patches[1]),
            patch(self._qdrant_patches[2]),
            patch(self._qdrant_patches[3], return_value=mock_index),
            patch.object(settings, "reranker_type", "none"),
        ):
            mock_client = MagicMock()
            mock_client.get_collections = AsyncMock(
                return_value=mock_collections
            )
            mock_qdrant_cls.return_value = mock_client

            from services.rag import retrieve_context  # noqa: PLC0415

            result = await retrieve_context(
                query="test",
                professor_collection="test_collection",
                top_k=5,
            )

        assert len(result) == 3
        for chunk in result:
            assert isinstance(chunk, ContextChunk)
        assert result[0].source_document == "lecture.pdf"
        assert result[1].source_document == "paper.pdf"
        assert result[2].source_document == "slides.pdf"

    @pytest.mark.asyncio
    async def test_empty_retrieval_returns_empty_list(self):
        """GIVEN a query matching zero Qdrant nodes
        WHEN retrieve_context() is called
        THEN the return SHALL be [].
        """
        # ── Qdrant collection does not exist → empty ────────────────────
        mock_collections = MagicMock()
        mock_collections.collections = []

        with (
            patch("services.rag.AsyncQdrantClient") as mock_qdrant_cls,
        ):
            mock_client = MagicMock()
            mock_client.get_collections = AsyncMock(
                return_value=mock_collections
            )
            mock_qdrant_cls.return_value = mock_client

            from services.rag import retrieve_context  # noqa: PLC0415

            result = await retrieve_context(
                query="test",
                professor_collection="nonexistent",
                top_k=5,
            )

        assert result == []


class TestFallbackChain:
    """Tests for the source_filename → document_id → '' fallback chain."""

    _qdrant_patches = (
        "services.rag.AsyncQdrantClient",
        "services.rag.QdrantVectorStore",
        "services.rag.OllamaEmbedding",
        "services.rag.VectorStoreIndex.from_vector_store",
    )

    @staticmethod
    def _make_retriever_mock(nodes: list[NodeWithScore]) -> tuple:
        mock_retriever = MagicMock(spec=AsyncMock)
        mock_retriever.aretrieve = AsyncMock(return_value=nodes)

        mock_index = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever

        mock_collections = MagicMock()
        mock_col = MagicMock()
        mock_col.name = "test_collection"
        mock_collections.collections = [mock_col]

        return mock_retriever, mock_index, mock_collections

    @pytest.mark.asyncio
    async def test_source_filename_present_uses_it(self):
        """GIVEN node with source_filename in payload
        WHEN ContextChunk is built
        THEN source_document = source_filename.
        """
        nodes = [
            _make_node_with_metadata(
                "content",
                0.9,
                {"source_filename": "report.pdf", "document_id": "uuid-1"},
            ),
        ]
        mock_retriever, mock_index, mock_collections = (
            self._make_retriever_mock(nodes)
        )

        with (
            patch(self._qdrant_patches[0]) as mock_qdrant_cls,
            patch(self._qdrant_patches[1]),
            patch(self._qdrant_patches[2]),
            patch(self._qdrant_patches[3], return_value=mock_index),
            patch.object(settings, "reranker_type", "none"),
        ):
            mock_client = MagicMock()
            mock_client.get_collections = AsyncMock(
                return_value=mock_collections
            )
            mock_qdrant_cls.return_value = mock_client

            from services.rag import retrieve_context  # noqa: PLC0415

            result = await retrieve_context(
                query="test",
                professor_collection="test_collection",
                top_k=5,
            )

        assert len(result) == 1
        assert result[0].source_document == "report.pdf"

    @pytest.mark.asyncio
    async def test_no_source_filename_falls_back_to_document_id(self):
        """GIVEN node with document_id but NO source_filename
        WHEN ContextChunk is built
        THEN source_document = document_id.
        """
        nodes = [
            _make_node_with_metadata(
                "legacy content",
                0.9,
                {"document_id": "fallback-uuid-999"},
            ),
        ]
        mock_retriever, mock_index, mock_collections = (
            self._make_retriever_mock(nodes)
        )

        with (
            patch(self._qdrant_patches[0]) as mock_qdrant_cls,
            patch(self._qdrant_patches[1]),
            patch(self._qdrant_patches[2]),
            patch(self._qdrant_patches[3], return_value=mock_index),
            patch.object(settings, "reranker_type", "none"),
        ):
            mock_client = MagicMock()
            mock_client.get_collections = AsyncMock(
                return_value=mock_collections
            )
            mock_qdrant_cls.return_value = mock_client

            from services.rag import retrieve_context  # noqa: PLC0415

            result = await retrieve_context(
                query="test",
                professor_collection="test_collection",
                top_k=5,
            )

        assert len(result) == 1
        assert result[0].source_document == "fallback-uuid-999"

    @pytest.mark.asyncio
    async def test_no_metadata_falls_back_to_empty_string(self):
        """GIVEN node with neither source_filename nor document_id
        WHEN ContextChunk is built
        THEN source_document = ''.
        """
        nodes = [
            _make_node_with_metadata(
                "orphan content",
                0.9,
                {},
            ),
        ]
        mock_retriever, mock_index, mock_collections = (
            self._make_retriever_mock(nodes)
        )

        with (
            patch(self._qdrant_patches[0]) as mock_qdrant_cls,
            patch(self._qdrant_patches[1]),
            patch(self._qdrant_patches[2]),
            patch(self._qdrant_patches[3], return_value=mock_index),
            patch.object(settings, "reranker_type", "none"),
        ):
            mock_client = MagicMock()
            mock_client.get_collections = AsyncMock(
                return_value=mock_collections
            )
            mock_qdrant_cls.return_value = mock_client

            from services.rag import retrieve_context  # noqa: PLC0415

            result = await retrieve_context(
                query="test",
                professor_collection="test_collection",
                top_k=5,
            )

        assert len(result) == 1
        assert result[0].source_document == ""
