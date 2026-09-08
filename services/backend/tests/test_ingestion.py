"""Tests for Cloudflare-backed document ingestion."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.db import DocumentStatus


@pytest.mark.asyncio
async def test_ingest_uploads_to_cloudflare_with_source_filename():
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

    uploaded: dict = {}

    async def fake_upload(key, content, content_type, **kwargs):
        uploaded["key"] = key
        uploaded["content"] = content
        uploaded["content_type"] = content_type
        return {"status": "completed", "chunks_count": 4}

    with (
        patch("services.ingestion.AsyncSessionLocal", return_value=mock_session),
        patch("services.ingestion._validate_document", return_value=(True, "")),
        patch("services.ingestion.Path.read_bytes", return_value=b"%PDF-1.4 content"),
        patch("core.cloudflare.upload_item", new=fake_upload),
    ):
        from services.ingestion import ingest_document

        await ingest_document(
            document_id="doc-uuid-1",
            professor_collection="prof_test",
            file_path="/fake/path/doc.pdf",
            file_format="pdf",
        )

    assert uploaded["key"] == "prof_test/doc-uuid-1/intro_to_ai.pdf"
    assert uploaded["content_type"] == "application/pdf"
    assert mock_doc.status == DocumentStatus.ready
    assert mock_doc.chunk_count == 4


@pytest.mark.asyncio
async def test_ingest_empty_payload_is_rejected():
    mock_doc = MagicMock()
    mock_doc.id = "doc-empty-1"
    mock_doc.filename = "empty.txt"
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_doc
    mock_result.scalar_one_or_none.return_value = mock_doc
    mock_session = MagicMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    with (
        patch("services.ingestion.AsyncSessionLocal", return_value=mock_session),
        patch("services.ingestion._validate_document", return_value=(True, "")),
        patch("services.ingestion.Path.read_bytes", return_value=b"   "),
        patch("core.cloudflare.upload_item", new=AsyncMock()) as upload,
    ):
        from services.ingestion import ingest_document

        await ingest_document(
            document_id="doc-empty-1",
            professor_collection="prof_test",
            file_path="/fake/empty.txt",
            file_format="txt",
        )

    upload.assert_not_called()
    assert mock_doc.status == DocumentStatus.error
    assert "EMPTY_CHUNKS" in mock_doc.error_message


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
