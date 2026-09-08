"""Local, provider-independent embeddings for RAG."""

import logging
from functools import lru_cache

from llama_index.core.embeddings import BaseEmbedding

from core.config import settings

log = logging.getLogger(__name__)


class FastEmbedModel(BaseEmbedding):
    """LlamaIndex adapter around FastEmbed's local inference runtime."""

    model_name: str = settings.embed_model
    embed_batch_size: int = 32

    @property
    def _text_embedding_model(self):
        return _fastembed_model()

    def _get_query_embedding(self, query: str) -> list[float]:
        return list(self._text_embedding_model.embed([_format_text(query, "query")]))[0].tolist()

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return list(self._text_embedding_model.embed([_format_text(text, "passage")]))[0].tolist()

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [
            vector.tolist()
            for vector in self._text_embedding_model.embed(
                [_format_text(text, "passage") for text in texts]
            )
        ]


def _format_text(text: str, role: str) -> str:
    """Apply E5 prefixes only when an E5 model is explicitly configured."""
    if "e5" in settings.embed_model.lower():
        return f"{role}: {text}"
    return text


@lru_cache(maxsize=1)
def _fastembed_model():
    from fastembed import TextEmbedding

    log.info("Loading local embedding model %s", settings.embed_model)
    return TextEmbedding(model_name=settings.embed_model)


@lru_cache(maxsize=1)
def get_embed_model() -> BaseEmbedding:
    """Return the process-wide local embedding model."""
    if settings.embed_provider != "fastembed":
        raise RuntimeError(
            "Only EMBED_PROVIDER=fastembed is supported. "
            "Use the configured multilingual FastEmbed model with EMBED_DIM=384."
        )
    return FastEmbedModel()
