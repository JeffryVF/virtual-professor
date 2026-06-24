"""Tests for RAG reranker adapter and BGE cross-encoder implementation.

Tests follow Strict TDD: tests are written first (RED), then
implementation is added to make them pass (GREEN).
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
from llama_index.core.schema import NodeWithScore, TextNode


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_node(text: str, score: float = 0.5) -> NodeWithScore:
    """Create a NodeWithScore with known text and score."""
    return NodeWithScore(node=TextNode(text=text), score=score)


# ═════════════════════════════════════════════════════════════════════════════
# Task 2.1 — RED: Adapter contract tests
# ═════════════════════════════════════════════════════════════════════════════


class TestRerankerAdapterContract:
    """Contract tests for the RerankerAdapter abstract interface.

    Uses a minimal concrete subclass to verify the interface contract
    without loading any model. These tests validate that the abstract
    interface enforces the correct return type and shape.
    """

    def test_rerank_returns_list_of_ints_same_length(self):
        """GIVEN 3 chunks WHEN rerank THEN returns list[int] of same length."""
        from services.reranker import RerankerAdapter

        class TestAdapter(RerankerAdapter):
            def rerank(self, query, chunks):
                return list(range(len(chunks)))

        adapter = TestAdapter()
        nodes = [_make_node("a"), _make_node("b"), _make_node("c")]
        result = adapter.rerank("query", nodes)

        assert isinstance(result, list)
        assert all(isinstance(i, int) for i in result)
        assert len(result) == 3

    def test_rerank_all_indices_are_valid(self):
        """GIVEN 3 chunks WHEN rerank THEN all indices in valid range [0, 2]."""
        from services.reranker import RerankerAdapter

        class TestAdapter(RerankerAdapter):
            def rerank(self, query, chunks):
                return [2, 0, 1]

        adapter = TestAdapter()
        nodes = [_make_node("a"), _make_node("b"), _make_node("c")]
        indices = adapter.rerank("query", nodes)

        assert all(0 <= i < 3 for i in indices)
        assert sorted(indices) == [0, 1, 2]  # all unique, all present

    def test_rerank_empty_chunks_returns_empty(self):
        """GIVEN empty chunks WHEN rerank THEN returns empty list."""
        from services.reranker import RerankerAdapter

        class TestAdapter(RerankerAdapter):
            def rerank(self, query, chunks):
                return list(range(len(chunks)))

        adapter = TestAdapter()
        result = adapter.rerank("query", [])
        assert result == []

    def test_rerank_single_chunk_returns_zero(self):
        """GIVEN 1 chunk WHEN rerank THEN returns [0]."""
        from services.reranker import RerankerAdapter

        class TestAdapter(RerankerAdapter):
            def rerank(self, query, chunks):
                return list(range(len(chunks)))

        adapter = TestAdapter()
        nodes = [_make_node("only")]
        result = adapter.rerank("query", nodes)
        assert result == [0]


# ═════════════════════════════════════════════════════════════════════════════
# Task 2.3 — RED: BGELocalReranker ordering tests
# ═════════════════════════════════════════════════════════════════════════════


class TestBGELocalRerankerOrdering:
    """Tests for BGELocalReranker ordering with mocked SentenceTransformerRerank."""

    @patch("llama_index.postprocessor.sbert_rerank.SentenceTransformerRerank")
    def test_reorders_by_score_descending(self, mock_rerank_cls):
        """GIVEN scores [0.2, 0.9, 0.5] WHEN rerank THEN indices [1, 2, 0]."""
        from services.reranker import BGELocalReranker

        mock_rerank = MagicMock()
        mock_rerank_cls.return_value = mock_rerank

        reranker = BGELocalReranker(model="test-model", top_n=5, device="cpu")

        nodes = [
            _make_node("low relevance", 0.2),
            _make_node("high relevance", 0.9),
            _make_node("medium relevance", 0.5),
        ]

        # Mock postprocess_nodes: simulate cross-encoder by sorting by score descending
        def postprocess_side_effect(nodes_arg, query_str=None):
            return sorted(nodes_arg, key=lambda n: n.score, reverse=True)

        mock_rerank.postprocess_nodes.side_effect = postprocess_side_effect

        indices = reranker.rerank("test query", nodes)

        # Expected: highest score first → idx 1 (high), then 2 (medium), then 0 (low)
        assert indices == [1, 2, 0]

    @patch("llama_index.postprocessor.sbert_rerank.SentenceTransformerRerank")
    def test_single_chunk_returns_identity(self, mock_rerank_cls):
        """GIVEN 1 chunk WHEN rerank THEN returns [0]."""
        from services.reranker import BGELocalReranker

        mock_rerank = MagicMock()
        mock_rerank_cls.return_value = mock_rerank

        reranker = BGELocalReranker(model="test-model", top_n=5, device="cpu")

        nodes = [_make_node("only chunk", 0.8)]
        mock_rerank.postprocess_nodes.return_value = list(nodes)

        indices = reranker.rerank("query", nodes)
        assert indices == [0]

    @patch("llama_index.postprocessor.sbert_rerank.SentenceTransformerRerank")
    def test_reranked_scores_updated_on_original_nodes(self, mock_rerank_cls):
        """GIVEN reranker scores [0.3, 0.8] WHEN rerank THEN node.score updated."""
        from services.reranker import BGELocalReranker

        mock_rerank = MagicMock()
        mock_rerank_cls.return_value = mock_rerank

        reranker = BGELocalReranker(model="test-model", top_n=5, device="cpu")

        nodes = [
            _make_node("first", 0.3),
            _make_node("second", 0.8),
        ]

        def postprocess_side_effect(nodes_arg, query_str=None):
            # Reorder: second then first, and update scores
            reordered = [nodes_arg[1], nodes_arg[0]]
            reordered[0].score = 0.8
            reordered[1].score = 0.3
            return reordered

        mock_rerank.postprocess_nodes.side_effect = postprocess_side_effect

        reranker.rerank("query", nodes)

        # Scores should be updated on the original nodes
        assert nodes[0].score == 0.3  # low relevance
        assert nodes[1].score == 0.8  # high relevance

    @patch("llama_index.postprocessor.sbert_rerank.SentenceTransformerRerank")
    def test_model_not_loaded_on_init(self, mock_rerank_cls):
        """GIVEN BGELocalReranker WHEN init THEN _model is None."""
        from services.reranker import BGELocalReranker

        reranker = BGELocalReranker(model="test-model", top_n=5, device="cpu")
        assert reranker._model is None
        mock_rerank_cls.assert_not_called()

    @patch("llama_index.postprocessor.sbert_rerank.SentenceTransformerRerank")
    def test_model_loaded_on_first_rerank_call(self, mock_rerank_cls):
        """GIVEN BGELocalReranker WHEN first rerank THEN model loaded."""
        from services.reranker import BGELocalReranker

        mock_rerank = MagicMock()
        mock_rerank.postprocess_nodes.return_value = []
        mock_rerank_cls.return_value = mock_rerank

        reranker = BGELocalReranker(model="test-model", top_n=5, device="cpu")
        assert reranker._model is None

        reranker.rerank("query", [_make_node("test")])
        assert reranker._model is not None
        mock_rerank_cls.assert_called_once_with(
            model="test-model", top_n=5, device="cpu"
        )


# ═════════════════════════════════════════════════════════════════════════════
# Task 2.5 — RED: Graceful fallback tests
# ═════════════════════════════════════════════════════════════════════════════


class TestBGELocalRerankerFallback:
    """Tests for graceful fallback when model loading or inference fails."""

    @patch("llama_index.postprocessor.sbert_rerank.SentenceTransformerRerank")
    def test_model_load_failure_returns_original_order(self, mock_rerank_cls):
        """GIVEN model load raises OSError WHEN rerank THEN original indices returned."""
        from services.reranker import BGELocalReranker

        mock_rerank_cls.side_effect = OSError("Model download failed")

        reranker = BGELocalReranker(model="test-model", top_n=5, device="cpu")
        nodes = [
            _make_node("a", 0.2),
            _make_node("b", 0.9),
            _make_node("c", 0.5),
        ]
        indices = reranker.rerank("query", nodes)

        assert indices == [0, 1, 2]

    @patch("llama_index.postprocessor.sbert_rerank.SentenceTransformerRerank")
    def test_inference_error_returns_original_order(self, mock_rerank_cls):
        """GIVEN inference raises RuntimeError WHEN rerank THEN original indices returned."""
        from services.reranker import BGELocalReranker

        mock_rerank = MagicMock()
        mock_rerank.postprocess_nodes.side_effect = RuntimeError("CUDA out of memory")
        mock_rerank_cls.return_value = mock_rerank

        reranker = BGELocalReranker(model="test-model", top_n=5, device="cpu")
        nodes = [
            _make_node("a", 0.2),
            _make_node("b", 0.9),
            _make_node("c", 0.5),
        ]
        indices = reranker.rerank("query", nodes)

        assert indices == [0, 1, 2]

    @patch("llama_index.postprocessor.sbert_rerank.SentenceTransformerRerank")
    def test_fallback_logs_warning_on_load_error(self, mock_rerank_cls, caplog):
        """GIVEN model load error WHEN rerank THEN warning logged with error details."""
        from services.reranker import BGELocalReranker

        mock_rerank_cls.side_effect = OSError("Model not found")

        reranker = BGELocalReranker(model="test-model", top_n=5, device="cpu")

        with caplog.at_level(logging.WARNING):
            reranker.rerank("query", [_make_node("a")])

        assert "Model" in caplog.text or "model" in caplog.text

    @patch("llama_index.postprocessor.sbert_rerank.SentenceTransformerRerank")
    def test_fallback_logs_warning_on_inference_error(self, mock_rerank_cls, caplog):
        """GIVEN inference error WHEN rerank THEN warning logged."""
        from services.reranker import BGELocalReranker

        mock_rerank = MagicMock()
        mock_rerank.postprocess_nodes.side_effect = RuntimeError("Inference failed")
        mock_rerank_cls.return_value = mock_rerank

        reranker = BGELocalReranker(model="test-model", top_n=5, device="cpu")

        with caplog.at_level(logging.WARNING):
            reranker.rerank("query", [_make_node("a")])

        assert "Inference" in caplog.text or "inference" in caplog.text

    @patch("llama_index.postprocessor.sbert_rerank.SentenceTransformerRerank")
    def test_empty_chunks_returns_empty_even_with_error(self, mock_rerank_cls):
        """GIVEN empty chunks WHEN rerank (even if model would error) THEN []."""
        from services.reranker import BGELocalReranker

        mock_rerank_cls.side_effect = OSError("Model not found")

        reranker = BGELocalReranker(model="test-model", top_n=5, device="cpu")
        indices = reranker.rerank("query", [])

        assert indices == []
