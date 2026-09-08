"""Tests for ingestion metadata enrichment (CRIT-03).

Verifies that source_filename is injected into stored DocumentChunk metadata
during document ingestion, enabling the RAG pipeline to cite sources.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from llama_index.core import Document as LIDocument

from models.db import DocumentChunk, DocumentStatus


@pytest.mark.asyncio
async def test_source_filename_injected_into_document_chunks():
    """GIVEN a Document with filename='intro_to_ai.pdf'
    WHEN the ingestion pipeline indexes chunks into pgvector
    THEN every stored DocumentChunk SHALL have source_filename='intro_to_ai.pdf'
    in its metadata.
    """
    # ── Mock DB session returning a Document with known filename ──────
    mock_doc = MagicMock()
    mock_doc.id = "doc-uuid-1"
    mock_doc.filename = "intro_to_ai.pdf"
    mock_doc.status = DocumentStatus.pending
    mock_doc.chunk_count = 0

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_doc

    mock_session = MagicMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    # ── Capture DocumentChunk rows added by ingest_document ───────────
    captured_chunks: list[DocumentChunk] = []
    mock_session.add.side_effect = captured_chunks.append

    # ── Mock embed model returning one embedding per node ────────────
    mock_embed = MagicMock()
    mock_embed.get_text_embedding_batch.return_value = [[0.0] * 1024]

    # ── Mock reader to avoid filesystem access ────────────────────────
    mock_reader = MagicMock()
    mock_reader.load_data.return_value = [LIDocument(text="AI concepts")]
    mock_reader_cls = MagicMock(return_value=mock_reader)

    split_node = MagicMock()
    split_node.metadata = {}
    split_node.get_content.return_value = "AI concepts"

    with (
        patch("services.ingestion.AsyncSessionLocal", return_value=mock_session),
        patch("services.ingestion.get_embed_model", return_value=mock_embed),
        patch("services.ingestion._validate_document", return_value=(True, "")),
        patch("services.ingestion.SentenceSplitter") as mock_splitter_cls,
        patch.dict("services.ingestion._FORMAT_READERS", {"pdf": mock_reader_cls}),
    ):
        mock_splitter_cls.return_value.get_nodes_from_documents.return_value = [split_node]

        from services.ingestion import ingest_document  # noqa: PLC0415

        await ingest_document(
            document_id="doc-uuid-1",
            professor_collection="prof_test",
            file_path="/fake/path/doc.pdf",
            file_format="pdf",
        )

    assert len(captured_chunks) == 1
    chunk = captured_chunks[0]
    assert chunk.chunk_metadata["source_filename"] == "intro_to_ai.pdf"
    assert chunk.professor_collection == "prof_test"
    assert chunk.document_id == "doc-uuid-1"
    # Document marked as ready
    assert mock_doc.status == DocumentStatus.ready
    assert mock_doc.chunk_count == 1