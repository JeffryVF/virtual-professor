"""Tests for ingestion metadata enrichment (CRIT-03).

Verifies that source_filename is injected into node metadata during
document ingestion, enabling the RAG pipeline to cite sources.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from llama_index.core import Document as LIDocument
from llama_index.core.schema import NodeRelationship, TextNode

from models.db import DocumentStatus


@pytest.mark.asyncio
async def test_source_filename_injected_into_node_metadata():
    """GIVEN a Document with filename='intro_to_ai.pdf'
    WHEN the ingestion pipeline indexes chunks into Qdrant
    THEN every node SHALL have source_filename='intro_to_ai.pdf' in metadata.
    """
    mock_doc = MagicMock()
    mock_doc.id = "doc-uuid-1"
    mock_doc.filename = "intro_to_ai.pdf"
    mock_doc.status = DocumentStatus.pending
    mock_doc.chunk_count = 0

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_doc
    mock_result.scalar_one_or_none.return_value = mock_doc

    mock_session = MagicMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    captured_nodes: list = []

    def _capture_index(nodes, professor_collection):
        captured_nodes.extend(nodes)
        return False

    mock_reader = MagicMock()
    mock_reader.load_data.return_value = [LIDocument(text="AI concepts")]
    mock_reader_cls = MagicMock(return_value=mock_reader)

    split_node = TextNode(text="AI concepts", metadata={})

    with (
        patch("services.ingestion.AsyncSessionLocal", return_value=mock_session),
        patch("services.ingestion.delete_document_points"),
        patch("services.ingestion._index_nodes", side_effect=_capture_index),
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

    assert len(captured_nodes) == 1
    assert captured_nodes[0].metadata["source_filename"] == "intro_to_ai.pdf"
    assert captured_nodes[0].metadata["document_id"] == "doc-uuid-1"
    assert captured_nodes[0].metadata["vp_document_id"] == "doc-uuid-1"
    assert captured_nodes[0].metadata["professor_collection"] == "prof_test"
    assert captured_nodes[0].relationships[NodeRelationship.SOURCE].node_id == "doc-uuid-1"
    assert mock_doc.status == DocumentStatus.ready
    assert mock_doc.chunk_count == 1


@pytest.mark.asyncio
async def test_resume_incomplete_ingestion_vectorizes_when_file_exists():
    doc = MagicMock()
    doc.id = "doc-1"
    doc.professor_id = "prof-1"
    doc.format = "pdf"
    prof = MagicMock()
    prof.collection = "prof_col"

    mock_result = MagicMock()
    mock_result.all.return_value = [(doc, prof)]
    mock_session = MagicMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.execute = AsyncMock(return_value=mock_result)

    with (
        patch("services.ingestion.AsyncSessionLocal", return_value=mock_session),
        patch("services.ingestion.os.path.isfile", return_value=True),
        patch("services.ingestion.ingest_document", new_callable=AsyncMock) as ingest,
    ):
        from services.ingestion import resume_incomplete_ingestion

        await resume_incomplete_ingestion()

    ingest.assert_awaited_once()
    assert ingest.await_args.args[0] == "doc-1"
    assert ingest.await_args.args[1] == "prof_col"
    assert ingest.await_args.args[3] == "pdf"


@pytest.mark.asyncio
async def test_resume_incomplete_ingestion_marks_missing_source():
    doc = MagicMock()
    doc.id = "doc-missing"
    doc.professor_id = "prof-1"
    doc.format = "pdf"
    prof = MagicMock()
    prof.collection = "prof_col"

    fresh = MagicMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [(doc, prof)]
    mock_session = MagicMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.get = AsyncMock(return_value=fresh)
    mock_session.commit = AsyncMock()

    with (
        patch("services.ingestion.AsyncSessionLocal", return_value=mock_session),
        patch("services.ingestion.os.path.isfile", return_value=False),
        patch("services.ingestion.ingest_document", new_callable=AsyncMock) as ingest,
    ):
        from services.ingestion import resume_incomplete_ingestion

        await resume_incomplete_ingestion()

    ingest.assert_not_called()
    assert fresh.status == DocumentStatus.error
    assert "SOURCE_MISSING" in fresh.error_message
