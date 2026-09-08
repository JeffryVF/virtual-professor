"""Gemini embeddings for RAG (gemini-embedding-001)."""

from __future__ import annotations

import logging
import math
from functools import lru_cache

from llama_index.core.embeddings import BaseEmbedding

from core.config import settings

log = logging.getLogger(__name__)

_QUERY_TASK = "RETRIEVAL_QUERY"
_DOCUMENT_TASK = "RETRIEVAL_DOCUMENT"
_NATIVE_DIM = 3072
_MAX_BATCH = 100


class GeminiEmbeddingModel(BaseEmbedding):
    """LlamaIndex adapter around the Gemini embedding API."""

    model_name: str = settings.embed_model
    embed_batch_size: int = _MAX_BATCH

    def _get_query_embedding(self, query: str) -> list[float]:
        return _embed_texts([query], _QUERY_TASK)[0]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return (await _aembed_texts([query], _QUERY_TASK))[0]

    def _get_text_embedding(self, text: str) -> list[float]:
        return _embed_texts([text], _DOCUMENT_TASK)[0]

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return (await _aembed_texts([text], _DOCUMENT_TASK))[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return _embed_texts(texts, _DOCUMENT_TASK)

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return await _aembed_texts(texts, _DOCUMENT_TASK)


def _api_key() -> str:
    return (settings.google_api_key or settings.gemini_api_key).strip()


def _embed_config(task_type: str):
    from google.genai import types

    return types.EmbedContentConfig(
        task_type=task_type,
        output_dimensionality=settings.embed_dim,
    )


def _l2_normalize(vector: list[float]) -> list[float]:
    """Re-normalize truncated gemini-embedding-001 vectors (required below 3072-d)."""
    if settings.embed_dim >= _NATIVE_DIM:
        return vector
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0:
        return vector
    return [component / norm for component in vector]


def _vectors_from_response(result, expected: int) -> list[list[float]]:
    embeddings = getattr(result, "embeddings", None) or []
    if len(embeddings) != expected:
        raise RuntimeError(
            f"Gemini embed_content returned {len(embeddings)} vectors, expected {expected}"
        )
    return [_l2_normalize(list(item.values)) for item in embeddings]


def _embed_texts(texts: list[str], task_type: str) -> list[list[float]]:
    if not texts:
        return []
    client = _gemini_client()
    out: list[list[float]] = []
    config = _embed_config(task_type)
    for start in range(0, len(texts), _MAX_BATCH):
        batch = texts[start : start + _MAX_BATCH]
        result = client.models.embed_content(
            model=settings.embed_model,
            contents=batch,
            config=config,
        )
        out.extend(_vectors_from_response(result, len(batch)))
    return out


async def _aembed_texts(texts: list[str], task_type: str) -> list[list[float]]:
    if not texts:
        return []
    client = _gemini_client()
    out: list[list[float]] = []
    config = _embed_config(task_type)
    for start in range(0, len(texts), _MAX_BATCH):
        batch = texts[start : start + _MAX_BATCH]
        result = await client.aio.models.embed_content(
            model=settings.embed_model,
            contents=batch,
            config=config,
        )
        out.extend(_vectors_from_response(result, len(batch)))
    return out


@lru_cache(maxsize=1)
def _gemini_client():
    from google import genai

    key = _api_key()
    log.warning("Using Gemini embedding model %s (%s-d)", settings.embed_model, settings.embed_dim)
    return genai.Client(api_key=key) if key else genai.Client()


@lru_cache(maxsize=1)
def get_embed_model() -> BaseEmbedding:
    """Return the process-wide Gemini embedding model."""
    if settings.embed_provider != "gemini":
        raise RuntimeError(
            "Only EMBED_PROVIDER=gemini is supported. "
            "Set EMBED_MODEL=gemini-embedding-001 and EMBED_DIM=768."
        )
    if not _api_key():
        raise RuntimeError(
            "GOOGLE_API_KEY (or GEMINI_API_KEY) is required for Gemini embeddings. "
            "Create a key at https://aistudio.google.com/apikey"
        )
    return GeminiEmbeddingModel()
