"""Tests for three-layer document validation.

Tests cover pre-upload (router layer), pre-ingestion (background task),
and post-parse validation following the sdd/pdf-validation spec.
"""

from uuid import UUID
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import UploadFile


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-ingestion validation — _validate_document()
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateDocument:
    """Tests for services.ingestion._validate_document — pre-ingestion layer."""

    @pytest.fixture(autouse=True)
    def _mock_fitz(self):
        """Patch fitz before each test in this class."""
        with patch("services.ingestion.fitz") as mock:
            self.mock_fitz = mock
            yield

    def _make_mock_doc(self, is_encrypted=False, page_count=5, page_texts=None):
        """Helper to build a mock fitz Document with context-manager support.

        fitz.open() returns the doc directly; `with doc:` uses doc.__enter__(),
        which must return an object with is_encrypted, page_count, and iteration.
        """
        doc = MagicMock()
        doc.is_encrypted = is_encrypted
        doc.page_count = page_count

        if page_texts is not None:
            pages = []
            for text in page_texts:
                p = MagicMock()
                p.get_text.return_value = text
                pages.append(p)
            doc.__iter__.return_value = iter(pages)

        # Context manager: `with doc:` calls doc.__enter__() which returns doc itself
        doc.__enter__.return_value = doc
        return doc

    def test_valid_pdf_passes_validation(self):
        """GIVEN a valid PDF with pages and extractable text
        WHEN _validate_document is called
        THEN it returns (True, "").
        """
        mock_doc = self._make_mock_doc(page_texts=["Some text", "More text"])
        self.mock_fitz.open.return_value = mock_doc

        from services.ingestion import _validate_document

        is_valid, error_msg = _validate_document("/fake/doc.pdf", "pdf", max_pages=200)

        assert is_valid is True
        assert error_msg == ""

    def test_password_protected_pdf_rejected(self):
        """GIVEN a password-protected PDF
        WHEN _validate_document is called
        THEN it returns (False, PDF_PASSWORD_PROTECTED ...).
        """
        mock_doc = self._make_mock_doc(is_encrypted=True)
        self.mock_fitz.open.return_value = mock_doc

        from services.ingestion import _validate_document

        is_valid, error_msg = _validate_document("/fake/protected.pdf", "pdf", max_pages=200)

        assert is_valid is False
        assert "PDF_PASSWORD_PROTECTED" in error_msg

    def test_too_many_pages_rejected(self):
        """GIVEN a PDF with 500 pages (exceeds max_pages=200)
        WHEN _validate_document is called
        THEN it returns (False, PDF_TOO_MANY_PAGES ...).
        """
        mock_doc = self._make_mock_doc(page_count=500)
        self.mock_fitz.open.return_value = mock_doc

        from services.ingestion import _validate_document

        is_valid, error_msg = _validate_document("/fake/big.pdf", "pdf", max_pages=200)

        assert is_valid is False
        assert "PDF_TOO_MANY_PAGES" in error_msg

    def test_no_extractable_text_rejected(self):
        """GIVEN a scanned PDF with no selectable text
        WHEN _validate_document is called
        THEN it returns (False, PDF_NO_EXTRACTABLE_TEXT ...).
        """
        mock_doc = self._make_mock_doc(page_texts=["", "", ""])
        self.mock_fitz.open.return_value = mock_doc

        from services.ingestion import _validate_document

        is_valid, error_msg = _validate_document("/fake/scanned.pdf", "pdf", max_pages=200)

        assert is_valid is False
        assert "PDF_NO_EXTRACTABLE_TEXT" in error_msg

    def test_corrupt_pdf_rejected(self):
        """GIVEN a corrupt PDF that fitz cannot open
        WHEN _validate_document is called
        THEN it returns (False, PDF_CORRUPT ...).
        """
        self.mock_fitz.open.side_effect = Exception("corrupt file")

        from services.ingestion import _validate_document

        is_valid, error_msg = _validate_document("/fake/corrupt.pdf", "pdf", max_pages=200)

        assert is_valid is False
        assert "PDF_CORRUPT" in error_msg

    def test_docx_format_skipped(self):
        """GIVEN a docx file (not PDF format)
        WHEN _validate_document is called
        THEN it returns (True, "") — no PDF-specific validation needed.
        """
        from services.ingestion import _validate_document

        is_valid, error_msg = _validate_document("/fake/doc.docx", "docx", max_pages=200)

        assert is_valid is True
        assert error_msg == ""

    def test_media_format_skipped(self):
        """GIVEN an mp3 file (not PDF format)
        WHEN _validate_document is called
        THEN it returns (True, "") — no PDF-specific validation needed.
        """
        from services.ingestion import _validate_document

        is_valid, error_msg = _validate_document("/fake/audio.mp3", "mp3", max_pages=200)

        assert is_valid is True
        assert error_msg == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Post-parse validation — empty chunks in ingest_document()
# ═══════════════════════════════════════════════════════════════════════════════

class TestPostParseValidation:
    """Tests for post-parse empty-chunk rejection in ingest_document()."""

    @pytest.mark.asyncio
    async def test_zero_nodes_rejected(self):
        """GIVEN a document that produces zero nodes after chunking
        WHEN ingest_document runs
        THEN doc.status=error, doc.error_message contains EMPTY_CHUNKS.
        """
        mock_doc = MagicMock()
        mock_doc.id = "doc-empty-1"
        mock_doc.filename = "empty.pdf"

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_doc

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.execute.return_value = mock_result

        mock_reader = MagicMock()
        mock_reader.load_data.return_value = []
        mock_reader_cls = MagicMock(return_value=mock_reader)

        # Zero nodes returned from splitter
        splitter_results: list = []

        from models.db import DocumentStatus

        with (
            patch("services.ingestion.AsyncSessionLocal", return_value=mock_session),
            patch("services.ingestion.get_embed_model"),
            patch("services.ingestion._validate_document", return_value=(True, "")),
            patch("services.ingestion.SentenceSplitter.get_nodes_from_documents") as mock_splitter,
            patch.dict("services.ingestion._FORMAT_READERS", {"pdf": mock_reader_cls}),
        ):
            mock_splitter.return_value = splitter_results

            from services.ingestion import ingest_document

            await ingest_document(
                document_id="doc-empty-1",
                professor_collection="prof_test",
                file_path="/fake/empty.pdf",
                file_format="pdf",
            )

        assert mock_doc.status == DocumentStatus.error
        assert "EMPTY_CHUNKS" in mock_doc.error_message

    @pytest.mark.asyncio
    async def test_empty_text_nodes_rejected(self):
        """GIVEN a document whose nodes have only whitespace/empty content
        WHEN ingest_document runs
        THEN doc.status=error, doc.error_message contains EMPTY_CHUNKS.
        """
        mock_doc = MagicMock()
        mock_doc.id = "doc-empty-2"
        mock_doc.filename = "blank.pdf"

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_doc

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.execute.return_value = mock_result

        mock_reader = MagicMock()
        mock_reader.load_data.return_value = []
        mock_reader_cls = MagicMock(return_value=mock_reader)

        # Nodes with only whitespace content
        empty_node = MagicMock()
        empty_node.get_content.return_value = "   \n  \t  "

        from models.db import DocumentStatus

        with (
            patch("services.ingestion.AsyncSessionLocal", return_value=mock_session),
            patch("services.ingestion.get_embed_model"),
            patch("services.ingestion._validate_document", return_value=(True, "")),
            patch("services.ingestion.SentenceSplitter.get_nodes_from_documents") as mock_splitter,
            patch.dict("services.ingestion._FORMAT_READERS", {"pdf": mock_reader_cls}),
        ):
            mock_splitter.return_value = [empty_node]

            from services.ingestion import ingest_document

            await ingest_document(
                document_id="doc-empty-2",
                professor_collection="prof_test",
                file_path="/fake/blank.pdf",
                file_format="pdf",
            )

        assert mock_doc.status == DocumentStatus.error
        assert "EMPTY_CHUNKS" in mock_doc.error_message


# ═══════════════════════════════════════════════════════════════════════════════
# Bug Fix: docx uses DocxReader, not PDFReader (Phase 5)
# ═══════════════════════════════════════════════════════════════════════════════

def test_docx_uses_docx_reader():
    """GIVEN _FORMAT_READERS
    WHEN looking up the "docx" key
    THEN the reader type MUST be DocxReader (not PDFReader).
    """
    from services.ingestion import _FORMAT_READERS, DocxReader, PDFReader

    docx_reader = _FORMAT_READERS.get("docx")
    assert docx_reader is not None, "docx must have a reader assigned"
    assert docx_reader is DocxReader, f"Expected DocxReader, got {docx_reader}"
    assert docx_reader is not PDFReader, "docx must NOT use PDFReader"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration Tests — POST /professors/{id}/documents (Phase 7)
# ═══════════════════════════════════════════════════════════════════════════════

class TestUploadEndpoint:
    """Integration tests for the document upload endpoint with validation."""

    ADMIN_KEY = "test-admin-key"

    @pytest.fixture(autouse=True)
    def _setup_mocks(self, tmp_path):
        """Mock external services and set up a temp upload dir."""
        import routers.admin as admin_mod
        self._upload_dir = tmp_path / "uploads"
        self._upload_dir.mkdir()
        admin_mod.UPLOAD_DIR = str(self._upload_dir)

        # These patches apply to ALL tests in this class
        self._patchers = [
            # Mock ingest_document so the background task doesn't hit the real DB
            # with string UUIDs (the upload endpoint test validates pre-upload only)
            patch("routers.admin.ingest_document"),
        ]
        for p in self._patchers:
            p.start()
        yield
        for p in self._patchers:
            p.stop()

    async def _create_professor(self, client: httpx.AsyncClient) -> UUID:
        """Create a professor and return its ID."""
        resp = await client.post(
            "/admin/professors",
            json={
                "name": "Test Prof",
                "topic": "Testing",
                "language": "en",
                "avatar_id": "avatar-1",
                "system_prompt": "You are a test",
            },
            headers={"X-Admin-Key": self.ADMIN_KEY},
        )
        assert resp.status_code == 201, f"Professor creation failed: {resp.text}"
        return resp.json()["id"]

    async def _upload_file(
        self,
        client: httpx.AsyncClient,
        professor_id: UUID,
        content: bytes,
        filename: str,
    ) -> httpx.Response:
        """Helper to upload a file to the documents endpoint."""
        return await client.post(
            f"/admin/professors/{professor_id}/documents",
            files={"file": (filename, content, "application/octet-stream")},
            headers={"X-Admin-Key": self.ADMIN_KEY},
        )

    @pytest.mark.asyncio
    async def test_valid_pdf_upload_returns_201(self, async_client: httpx.AsyncClient):
        """GIVEN a valid PDF file (correct MIME, under size limit)
        WHEN uploaded to the documents endpoint
        THEN status=201 and Document(status=pending).
        """
        prof_id = await self._create_professor(async_client)
        pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"

        resp = await self._upload_file(async_client, prof_id, pdf_content, "test.pdf")

        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["status"] == "pending"
        assert data["format"] == "pdf"
        assert data["error_message"] is None

    @pytest.mark.asyncio
    async def test_non_pdf_disguised_returns_400(self, async_client: httpx.AsyncClient):
        """GIVEN an EXE file renamed to .pdf
        WHEN uploaded
        THEN status=400 with error.code=INVALID_FILE_TYPE.
        """
        prof_id = await self._create_professor(async_client)
        exe_content = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"

        resp = await self._upload_file(async_client, prof_id, exe_content, "malicious.pdf")

        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
        detail = resp.json()["detail"]
        assert detail["error"]["code"] == "INVALID_FILE_TYPE"

    @pytest.mark.asyncio
    async def test_disallowed_extension_returns_400(self, async_client: httpx.AsyncClient):
        """GIVEN a .zip file
        WHEN uploaded
        THEN status=400 with error.code=EXTENSION_NOT_ALLOWED.
        """
        prof_id = await self._create_professor(async_client)
        zip_content = b"PK\x03\x04\x14\x00\x00\x00\x00\x00"

        resp = await self._upload_file(async_client, prof_id, zip_content, "archive.zip")

        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
        detail = resp.json()["detail"]
        assert detail["error"]["code"] == "EXTENSION_NOT_ALLOWED"


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-upload validation — validate_upload_file()
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateUploadFile:
    """Tests for admin.validate_upload_file — pre-upload layer."""

    @pytest.mark.asyncio
    async def test_valid_pdf_passes(self):
        """GIVEN a valid PDF file with pdf extension and correct MIME
        WHEN validate_upload_file is called
        THEN it returns (True, None, None).
        """
        file = MagicMock(spec=UploadFile)
        file.filename = "doc.pdf"
        file.file = MagicMock()
        file.file.read.return_value = b"%PDF-1.4 fake content"
        file.file.tell.return_value = 1000  # small file, under limit

        from routers.admin import validate_upload_file

        allowed = ["pdf", "docx", "pptx"]

        with patch("routers.admin.magic.from_buffer", return_value="application/pdf"):
            is_valid, err_code, err_msg = validate_upload_file(file, max_size_mb=50, allowed_formats=allowed)

        assert is_valid is True
        assert err_code is None
        assert err_msg is None

    @pytest.mark.asyncio
    async def test_non_pdf_disguised_as_pdf_rejected(self):
        """GIVEN an .exe renamed to .pdf
        WHEN validate_upload_file is called
        THEN it returns (False, INVALID_FILE_TYPE, ...).
        """
        file = MagicMock(spec=UploadFile)
        file.filename = "virus.exe.pdf"
        file.file = MagicMock()
        file.file.read.return_value = b"MZ\x90\x00 fake exe"

        from routers.admin import validate_upload_file

        allowed = ["pdf", "docx", "pptx"]

        with patch("routers.admin.magic.from_buffer", return_value="application/x-msdownload"):
            is_valid, err_code, err_msg = validate_upload_file(file, max_size_mb=50, allowed_formats=allowed)

        assert is_valid is False
        assert err_code == "INVALID_FILE_TYPE"
        assert err_msg is not None

    @pytest.mark.asyncio
    async def test_oversized_file_rejected(self):
        """GIVEN a file exceeding max_size_mb
        WHEN validate_upload_file is called
        THEN it returns (False, FILE_TOO_LARGE, ...).
        """
        file = MagicMock(spec=UploadFile)
        file.filename = "big.pdf"
        file.file = MagicMock()
        file.file.read.return_value = b"%PDF-1.4 content"
        # Mock tell() to report 2MB which exceeds 1MB limit
        file.file.tell.return_value = 2 * 1024 * 1024

        from routers.admin import validate_upload_file

        allowed = ["pdf"]

        with patch("routers.admin.magic.from_buffer", return_value="application/pdf"):
            is_valid, err_code, err_msg = validate_upload_file(file, max_size_mb=1, allowed_formats=allowed)

        assert is_valid is False
        assert err_code == "FILE_TOO_LARGE"
        assert err_msg is not None

    @pytest.mark.asyncio
    async def test_disallowed_extension_rejected(self):
        """GIVEN a .zip file uploaded
        WHEN validate_upload_file is called
        THEN it returns (False, EXTENSION_NOT_ALLOWED, ...).
        """
        file = MagicMock(spec=UploadFile)
        file.filename = "archive.zip"
        file.file = MagicMock()

        from routers.admin import validate_upload_file

        allowed = ["pdf", "docx"]

        is_valid, err_code, err_msg = validate_upload_file(file, max_size_mb=50, allowed_formats=allowed)

        assert is_valid is False
        assert err_code == "EXTENSION_NOT_ALLOWED"
        assert err_msg is not None

    @pytest.mark.asyncio
    async def test_file_seeked_back_after_magic_read(self):
        """GIVEN a file read for MIME detection
        WHEN validate_upload_file returns
        THEN the file pointer is seeked back to 0 (after both magic reads and size check).
        """
        file = MagicMock(spec=UploadFile)
        file.filename = "doc.pdf"
        file.file = MagicMock()
        file.file.read.return_value = b"%PDF-1.4 content"
        file.file.tell.return_value = 500

        from routers.admin import validate_upload_file

        allowed = ["pdf"]

        with patch("routers.admin.magic.from_buffer", return_value="application/pdf"):
            validate_upload_file(file, max_size_mb=50, allowed_formats=allowed)

        # seek(0) is called: after magic read, and after size check.
        # seek(0, 2) is called for size check.
        assert file.file.seek.call_count == 3
        file.file.seek.assert_any_call(0)
