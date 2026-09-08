"""Tests for the Gemini embedding adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import settings
from services.embeddings import GeminiEmbeddingModel, get_embed_model


@pytest.fixture(autouse=True)
def _isolate_embed_settings():
    provider = settings.embed_provider
    model = settings.embed_model
    dim = settings.embed_dim
    google_key = settings.google_api_key
    gemini_key = settings.gemini_api_key
    yield
    settings.embed_provider = provider
    settings.embed_model = model
    settings.embed_dim = dim
    settings.google_api_key = google_key
    settings.gemini_api_key = gemini_key
    get_embed_model.cache_clear()
    from services.embeddings import _gemini_client

    _gemini_client.cache_clear()


def _fake_embedding(values: list[float]) -> MagicMock:
    item = MagicMock()
    item.values = values
    return item


def test_get_embed_model_requires_gemini():
    settings.embed_provider = "fastembed"
    settings.google_api_key = "test-key"
    get_embed_model.cache_clear()
    with pytest.raises(RuntimeError, match="EMBED_PROVIDER=gemini"):
        get_embed_model()


def test_get_embed_model_requires_api_key():
    settings.embed_provider = "gemini"
    settings.google_api_key = ""
    settings.gemini_api_key = ""
    get_embed_model.cache_clear()
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        get_embed_model()


def test_get_embed_model_returns_cached_adapter():
    settings.embed_provider = "gemini"
    settings.google_api_key = "test-key"
    get_embed_model.cache_clear()
    first = get_embed_model()
    second = get_embed_model()
    assert isinstance(first, GeminiEmbeddingModel)
    assert first is second


def test_query_uses_retrieval_query_and_document_uses_retrieval_document():
    settings.embed_provider = "gemini"
    settings.embed_model = "gemini-embedding-001"
    settings.embed_dim = 768
    settings.google_api_key = "test-key"
    get_embed_model.cache_clear()
    model = get_embed_model()

    fake_client = MagicMock()
    fake_result = MagicMock()
    fake_result.embeddings = [_fake_embedding([3.0, 4.0, 0.0])]
    fake_client.models.embed_content.return_value = fake_result

    with patch("services.embeddings._gemini_client", return_value=fake_client):
        query_vec = model._get_query_embedding("que es RAG")
        doc_vec = model._get_text_embedding("contenido")

    query_call = fake_client.models.embed_content.call_args_list[0]
    doc_call = fake_client.models.embed_content.call_args_list[1]
    assert query_call.kwargs["model"] == "gemini-embedding-001"
    assert query_call.kwargs["contents"] == ["que es RAG"]
    assert query_call.kwargs["config"].task_type == "RETRIEVAL_QUERY"
    assert query_call.kwargs["config"].output_dimensionality == 768
    assert doc_call.kwargs["config"].task_type == "RETRIEVAL_DOCUMENT"
    # 3-4-5 triangle → unit vector after L2 (dim 768 < 3072)
    assert query_vec == pytest.approx([0.6, 0.8, 0.0])
    assert doc_vec == pytest.approx([0.6, 0.8, 0.0])


def test_native_3072_vectors_are_not_renormalized():
    settings.embed_dim = 3072
    settings.google_api_key = "test-key"
    get_embed_model.cache_clear()
    model = get_embed_model()

    fake_client = MagicMock()
    fake_result = MagicMock()
    fake_result.embeddings = [_fake_embedding([3.0, 4.0])]
    fake_client.models.embed_content.return_value = fake_result

    with patch("services.embeddings._gemini_client", return_value=fake_client):
        vector = model._get_text_embedding("contenido")

    assert vector == [3.0, 4.0]


@pytest.mark.asyncio
async def test_async_query_embedding_uses_aio_client():
    settings.embed_dim = 768
    settings.google_api_key = "test-key"
    get_embed_model.cache_clear()
    model = get_embed_model()

    fake_result = MagicMock()
    fake_result.embeddings = [_fake_embedding([0.0, 1.0])]
    fake_client = MagicMock()
    fake_client.aio.models.embed_content = AsyncMock(return_value=fake_result)

    with patch("services.embeddings._gemini_client", return_value=fake_client):
        vector = await model._aget_query_embedding("pregunta")

    fake_client.aio.models.embed_content.assert_awaited_once()
    assert vector == pytest.approx([0.0, 1.0])
