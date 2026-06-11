"""RAG reranker adapter with local BGE cross-encoder implementation.

Provides a pluggable ``RerankerAdapter`` abstract interface and a concrete
``BGELocalReranker`` that wraps ``SentenceTransformerRerank`` from
``llama-index-postprocessor-sbert-rerank``.

Usage::

    reranker = BGELocalReranker(model="BAAI/bge-reranker-v2-m3", top_n=5)
    indices = reranker.rerank("user query", retrieved_chunks)
    # indices → [2, 0, 1]  (most relevant first)
    reranked = [chunks[i] for i in indices]
"""

import logging
from abc import ABC, abstractmethod
from typing import Sequence

from llama_index.core.schema import NodeWithScore

log = logging.getLogger(__name__)


class RerankerAdapter(ABC):
    """Abstract interface for RAG rerankers.

    Implementations return chunk indices in re-ranked order, with the most
    relevant chunk first. The caller is responsible for re-ordering the
    original list and using the updated scores on the nodes.
    """

    @abstractmethod
    def rerank(self, query: str, chunks: Sequence[NodeWithScore]) -> list[int]:
        """Return chunk indices in re-ranked order (descending relevance).

        Args:
            query: The user query string.
            chunks: Retrieved chunks to rerank.

        Returns:
            List of indices into *chunks* in re-ranked order.
            Same length as *chunks*. Each index is a valid position
            (0 .. len(chunks)-1). Empty input returns [].

        Note:
            Implementations SHOULD update ``node.score`` on the original
            nodes as a side-effect so downstream pipeline steps
            (e.g. score threshold filtering) use the reranker score.
        """


class BGELocalReranker(RerankerAdapter):
    """Reranker using ``BAAI/bge-reranker-v2-m3`` via ``SentenceTransformerRerank``.

    The cross-encoder model is loaded **lazily** — the first call to
    :meth:`rerank` triggers model initialisation. If the model fails to load
    or inference raises an exception, a ``log.warning`` is emitted and the
    original chunk order is returned.
    """

    def __init__(
        self,
        model: str = "BAAI/bge-reranker-v2-m3",
        top_n: int = 5,
        device: str = "cpu",
    ) -> None:
        self._model_name = model
        self._top_n = top_n
        self._device = device
        self._model = None  # lazy: loaded on first rerank()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        """Lazy-load the ``SentenceTransformerRerank`` cross-encoder."""
        # Delayed import — only needed when reranker is actually enabled
        from llama_index.postprocessor.sbert_rerank import (  # noqa: PLC0415
            SentenceTransformerRerank,
        )

        self._model = SentenceTransformerRerank(
            model=self._model_name,
            top_n=self._top_n,
            device=self._device,
        )

    def _tag_nodes(self, chunks: Sequence[NodeWithScore]) -> None:
        """Tag each node with its original index for later re-mapping."""
        for i, chunk in enumerate(chunks):
            chunk.metadata["_rerank_idx"] = i

    def _extract_indices(
        self, reranked: list[NodeWithScore]
    ) -> list[int]:
        """Extract original indices from reranked nodes (sorted by relevance)."""
        return [n.metadata.pop("_rerank_idx") for n in reranked]

    def _update_scores(
        self,
        chunks: Sequence[NodeWithScore],
        reranked: list[NodeWithScore],
        indices: list[int],
    ) -> None:
        """Copy reranker scores back onto the original node objects."""
        for new_pos, orig_idx in enumerate(indices):
            chunks[orig_idx].score = reranked[new_pos].score

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rerank(self, query: str, chunks: Sequence[NodeWithScore]) -> list[int]:
        if not chunks:
            return []

        # Lazy-load the model on first call
        if self._model is None:
            try:
                self._load_model()
            except Exception as exc:
                log.warning("Reranker model load failed: %s", exc)
                return list(range(len(chunks)))

        self._tag_nodes(chunks)

        try:
            reranked = self._model.postprocess_nodes(
                list(chunks), query_str=query
            )
            indices = self._extract_indices(reranked)
            self._update_scores(chunks, reranked, indices)
            return indices
        except Exception as exc:
            log.warning("Reranker inference failed: %s", exc)
            # Clean up metadata tags
            for chunk in chunks:
                chunk.metadata.pop("_rerank_idx", None)
            return list(range(len(chunks)))
