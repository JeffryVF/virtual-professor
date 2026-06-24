"""Tests for ingestion metadata enrichment (CRIT-03).

Verifies that source_filename is injected into node metadata during
document ingestion, enabling the RAG pipeline to cite sources.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from llama_index.core import Document as LIDocument


@pytest.mark.asyncio
async def test_source_filename_injected_into_node_metadata():
    """GIVEN a Document with filename='intro_to_ai.pdf'
    WHEN the ingestion pipeline indexes chunks into Qdrant
    THEN every node SHALL have source_filename='intro_to_ai.pdf' in metadata.
    """
    # ── Mock DB session returning a Document with known filename ──────
    mock_doc = MagicMock()
    mock_doc.id = "doc-uuid-1"
    mock_doc.filename = "intro_to_ai.pdf"

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_doc

    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.execute = AsyncMock(return_value=mock_result)

    # ── Capture nodes passed to VectorStoreIndex ──────────────────────
    captured_nodes: list = []

    class VectorStoreIndexSpy:
        def __init__(self, nodes, storage_context=None, embed_model=None):
            captured_nodes.extend(nodes)

    # ── Mock reader to avoid filesystem access ────────────────────────
    mock_reader = MagicMock()
    mock_reader.load_data.return_value = [LIDocument(text="AI concepts")]

    mock_reader_cls = MagicMock(return_value=mock_reader)

    split_node = MagicMock()
    split_node.metadata = {}
    split_node.get_content.return_value = "AI concepts"

    with (
        patch("services.ingestion.AsyncSessionLocal", return_value=mock_session),
        patch("services.ingestion.QdrantClient"),
        patch("services.ingestion.OllamaEmbedding"),
        patch("services.ingestion._ensure_collection", new=AsyncMock()),
        patch("services.ingestion._validate_document", return_value=(True, "")),
        patch("services.ingestion.SentenceSplitter.get_nodes_from_documents") as mock_splitter,
        patch("services.ingestion.VectorStoreIndex", VectorStoreIndexSpy),
        patch.dict("services.ingestion._FORMAT_READERS", {"pdf": mock_reader_cls}),
    ):
        mock_splitter.return_value = [split_node]

        from services.ingestion import ingest_document  # noqa: PLC0415

        await ingest_document(
            document_id="doc-uuid-1",
            professor_collection="prof_test",
            file_path="/fake/path/doc.pdf",
            file_format="pdf",
        )

    assert len(captured_nodes) == 1
    assert captured_nodes[0].metadata["source_filename"] == "intro_to_ai.pdf"
