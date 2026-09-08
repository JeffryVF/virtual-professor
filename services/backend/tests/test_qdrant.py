"""Tests for the Qdrant Cloud client factory and payload helpers."""

from unittest.mock import MagicMock, patch

import pytest
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode
from llama_index.core.vector_stores.utils import node_to_metadata_dict
from llama_index.vector_stores.qdrant import QdrantVectorStore
from pydantic import ValidationError
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from core.config import Settings
from core.qdrant import qdrant_client_kwargs
from services.ingestion import stamp_chunk_document_id
from services.qdrant_store import (
    DOCUMENT_ID_KEY,
    VP_DOCUMENT_ID_KEY,
    _chunk_from_payload,
    _document_filter,
    collection_vector_size,
    ensure_collection,
)

CLOUD_URL = "https://demo.us-east.aws.cloud.qdrant.io:6333"


def test_qdrant_client_kwargs_include_api_key_for_cloud():
    with patch("core.qdrant.settings") as mock_settings:
        mock_settings.qdrant_url = CLOUD_URL
        mock_settings.qdrant_api_key = "cloud-key"
        kwargs = qdrant_client_kwargs()
    assert kwargs["url"] == CLOUD_URL
    assert kwargs["api_key"] == "cloud-key"
    assert kwargs["prefer_grpc"] is False
    assert kwargs["check_compatibility"] is False
    assert kwargs["timeout"] == 30


def test_qdrant_client_kwargs_omit_empty_api_key():
    with patch("core.qdrant.settings") as mock_settings:
        mock_settings.qdrant_url = "http://localhost:6333"
        mock_settings.qdrant_api_key = ""
        kwargs = qdrant_client_kwargs()
    assert kwargs["url"] == "http://localhost:6333"
    assert "api_key" not in kwargs


def test_chunk_from_payload_reads_top_level_fields():
    chunk = _chunk_from_payload(
        {"text": "hello", "chunk_index": 2, "page_label": "4"},
        fallback_index=0,
    )
    assert chunk == {"chunk_index": 2, "text": "hello", "page_label": "4"}


def test_chunk_from_payload_reads_llama_index_node_content():
    chunk = _chunk_from_payload(
        {
            "_node_content": '{"text": "from node"}',
            "metadata": {"chunk_index": 1, "page_label": "9"},
        },
        fallback_index=99,
    )
    assert chunk["text"] == "from node"
    assert chunk["chunk_index"] == 1
    assert chunk["page_label"] == "9"


def test_settings_reject_example_qdrant_url():
    with pytest.raises(ValidationError, match="QDRANT_URL"):
        Settings(
            database_url="postgresql://x",
            redis_url="redis://localhost",
            qdrant_url="https://your-cluster.qdrant.io:6333",
            qdrant_api_key="cloud-key",
            admin_api_key="k",
            jwt_secret_key="secret-secret-secret-secret",
            rag_min_relevance_score=0.2,
            zai_api_key="zai",
            google_api_key="google",
        )


def test_settings_reject_example_xxxx_cloud_url():
    with pytest.raises(ValidationError, match="QDRANT_URL"):
        Settings(
            database_url="postgresql://x",
            redis_url="redis://localhost",
            qdrant_url="https://xxxx.us-east-1-0.aws.cloud.qdrant.io:6333",
            qdrant_api_key="cloud-key",
            admin_api_key="k",
            jwt_secret_key="secret-secret-secret-secret",
            rag_min_relevance_score=0.2,
            zai_api_key="zai",
            google_api_key="google",
        )


def test_settings_require_api_key_for_qdrant_cloud_url():
    with pytest.raises(ValidationError, match="QDRANT_API_KEY"):
        Settings(
            database_url="postgresql://x",
            redis_url="redis://localhost",
            qdrant_url=CLOUD_URL,
            qdrant_api_key="",
            admin_api_key="k",
            jwt_secret_key="secret-secret-secret-secret",
            rag_min_relevance_score=0.2,
            zai_api_key="zai",
            google_api_key="google",
        )


def test_production_requires_qdrant_cloud_url():
    cfg = Settings(
        database_url="postgresql://x",
        redis_url="redis://localhost",
        qdrant_url="http://localhost:6333",
        qdrant_api_key="",
        admin_api_key="k",
        jwt_secret_key="secret-secret-secret-secret",
        rag_min_relevance_score=0.2,
        zai_api_key="zai",
        google_api_key="google",
    )
    with pytest.raises(RuntimeError, match="QDRANT_URL"):
        cfg.validate_production()


def test_production_requires_qdrant_cloud_api_key():
    cfg = Settings(
        database_url="postgresql://x",
        redis_url="redis://localhost",
        qdrant_url=CLOUD_URL,
        qdrant_api_key="cloud-key",
        admin_api_key="k",
        jwt_secret_key="secret-secret-secret-secret",
        rag_min_relevance_score=0.2,
        zai_api_key="zai",
        google_api_key="google",
    )
    cfg.qdrant_api_key = ""
    with pytest.raises(RuntimeError, match="QDRANT_API_KEY"):
        cfg.validate_production()


def test_production_requires_google_api_key():
    cfg = Settings(
        database_url="postgresql://x",
        redis_url="redis://localhost",
        qdrant_url=CLOUD_URL,
        qdrant_api_key="cloud-key",
        admin_api_key="k",
        jwt_secret_key="secret-secret-secret-secret",
        rag_min_relevance_score=0.2,
        zai_api_key="zai",
        google_api_key="",
        gemini_api_key="",
    )
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        cfg.validate_production()


def test_collection_vector_size_reads_unnamed_params():
    info = MagicMock()
    info.config.params.vectors.size = 384
    assert collection_vector_size(info) == 384


def test_ensure_collection_recreates_on_dimension_mismatch():
    named = MagicMock()
    named.name = "prof_test"
    client = MagicMock()
    client.get_collections.return_value.collections = [named]
    info = MagicMock()
    info.config.params.vectors.size = 384
    client.get_collection.return_value = info

    with patch("services.qdrant_store.settings") as mock_settings:
        mock_settings.embed_dim = 768
        wiped = ensure_collection(client, "prof_test")

    assert wiped is True
    client.delete_collection.assert_called_once_with("prof_test")
    client.create_collection.assert_called_once()
    assert client.create_collection.call_args.kwargs["vectors_config"].size == 768


def test_ensure_collection_keeps_matching_dimension():
    named = MagicMock()
    named.name = "prof_test"
    client = MagicMock()
    client.get_collections.return_value.collections = [named]
    info = MagicMock()
    info.config.params.vectors.size = 768
    client.get_collection.return_value = info

    with patch("services.qdrant_store.settings") as mock_settings:
        mock_settings.embed_dim = 768
        wiped = ensure_collection(client, "prof_test")

    assert wiped is False
    client.delete_collection.assert_not_called()
    client.create_collection.assert_not_called()


def test_stamp_sets_source_so_llamaindex_payload_keeps_postgres_id():
    node = TextNode(text="chunk", metadata={"document_id": "should-be-replaced"})
    stamp_chunk_document_id(node, "doc-uuid-1")

    payload = node_to_metadata_dict(node, remove_text=False, flat_metadata=False)
    assert payload["document_id"] == "doc-uuid-1"
    assert payload["doc_id"] == "doc-uuid-1"
    assert payload[VP_DOCUMENT_ID_KEY] == "doc-uuid-1"
    assert node.relationships[NodeRelationship.SOURCE] == RelatedNodeInfo(
        node_id="doc-uuid-1"
    )


def test_in_memory_qdrant_collection_filter_and_search():
    """Exercise collection create, payload filter, and cosine search on real Qdrant."""
    client = QdrantClient(":memory:")
    with patch("services.qdrant_store.settings") as mock_settings:
        mock_settings.embed_dim = 4
        wiped = ensure_collection(client, "prof_demo")

    assert wiped is False
    info = client.get_collection("prof_demo")
    assert collection_vector_size(info) == 4

    alpha = [1.0, 0.0, 0.0, 0.0]
    beta = [0.0, 1.0, 0.0, 0.0]
    client.upsert(
        collection_name="prof_demo",
        points=[
            PointStruct(
                id=1,
                vector=alpha,
                payload={
                    DOCUMENT_ID_KEY: "None",
                    VP_DOCUMENT_ID_KEY: "doc-a",
                    "text": "alpha",
                    "chunk_index": 0,
                },
            ),
            PointStruct(
                id=2,
                vector=beta,
                payload={
                    DOCUMENT_ID_KEY: "doc-b",
                    VP_DOCUMENT_ID_KEY: "doc-b",
                    "text": "beta",
                    "chunk_index": 0,
                },
            ),
        ],
    )

    records, _offset = client.scroll(
        collection_name="prof_demo",
        scroll_filter=_document_filter("doc-a"),
        with_payload=True,
        limit=10,
    )
    assert len(records) == 1
    assert records[0].payload["text"] == "alpha"

    hits = client.query_points(collection_name="prof_demo", query=alpha, limit=1)
    assert hits.points[0].id == 1
    assert hits.points[0].payload["text"] == "alpha"


def test_llamaindex_ingest_and_search_roundtrip_in_memory_qdrant():
    """Ingest via LlamaIndex QdrantVectorStore and retrieve by cosine similarity."""
    client = QdrantClient(":memory:")
    with patch("services.qdrant_store.settings") as mock_settings:
        mock_settings.embed_dim = 8
        ensure_collection(client, "prof_roundtrip")

    node = TextNode(text="La fotosintesis ocurre en las plantas")
    stamp_chunk_document_id(node, "doc-plants")
    node.metadata["source_filename"] = "bio.pdf"
    node.metadata["chunk_index"] = 0
    node.metadata["page_label"] = "1"

    embed = MockEmbedding(embed_dim=8)
    vector_store = QdrantVectorStore(client=client, collection_name="prof_roundtrip")
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex(
        [node],
        storage_context=storage_context,
        embed_model=embed,
    )

    records, _offset = client.scroll(
        collection_name="prof_roundtrip",
        scroll_filter=_document_filter("doc-plants"),
        with_payload=True,
        limit=10,
    )
    assert len(records) == 1
    payload = records[0].payload or {}
    assert payload.get("document_id") == "doc-plants"
    assert payload.get(VP_DOCUMENT_ID_KEY) == "doc-plants"
    assert payload.get("source_filename") == "bio.pdf"

    retriever = index.as_retriever(similarity_top_k=1)
    hits = retriever.retrieve("fotosintesis en plantas")
    assert len(hits) == 1
    assert "fotosintesis" in hits[0].get_content().lower()
    assert hits[0].metadata.get("document_id") == "doc-plants"
