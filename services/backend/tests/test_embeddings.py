"""Tests for the local, provider-independent embedding adapter."""

from unittest.mock import MagicMock, patch

import pytest

from core.config import settings
from services.embeddings import FastEmbedModel, get_embed_model


@pytest.fixture(autouse=True)
def _isolate_embed_settings():
    provider = settings.embed_provider
    model = settings.embed_model
    yield
    settings.embed_provider = provider
    settings.embed_model = model


def test_get_embed_model_requires_fastembed():
    settings.embed_provider = "openai"
    with pytest.raises(RuntimeError, match="EMBED_PROVIDER=fastembed"):
        get_embed_model.cache_clear()
        get_embed_model()


def test_get_embed_model_returns_cached_local_adapter():
    settings.embed_provider = "fastembed"
    get_embed_model.cache_clear()
    first = get_embed_model()
    second = get_embed_model()
    assert isinstance(first, FastEmbedModel)
    assert first is second


def test_adapter_does_not_add_e5_prefixes_to_minilm():
    settings.embed_provider = "fastembed"
    get_embed_model.cache_clear()
    model = get_embed_model()
    fake_vector = MagicMock()
    fake_vector.tolist.return_value = [0.1, 0.2]
    fake_runtime = MagicMock()
    fake_runtime.embed.return_value = iter([fake_vector])
    with patch("services.embeddings._fastembed_model", return_value=fake_runtime):
        model._get_query_embedding("que es RAG")
        fake_runtime.embed.assert_called_once_with(["que es RAG"])
        fake_runtime.reset_mock()
        fake_runtime.embed.return_value = iter([fake_vector])
        model._get_text_embedding("contenido")
        fake_runtime.embed.assert_called_once_with(["contenido"])
