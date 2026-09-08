"""Integration tests for admin endpoints: document chunks, indexing status, and reindex."""

from unittest.mock import patch

import pytest
import pytest_asyncio

from uuid import UUID

from core.config import settings
from models.db import Document, DocumentStatus, Language, Professor


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def qdrant_payload_store(monkeypatch):
    """In-memory stand-in for Qdrant points used by admin chunk endpoints."""
    store: dict[tuple[str, str], list[dict]] = {}

    def list_points(collection_name: str, document_id: str):
        return list(store.get((collection_name, str(document_id)), []))

    def count_points(collection_name: str) -> int:
        return sum(len(v) for (c, _), v in store.items() if c == collection_name)

    monkeypatch.setattr("routers.admin.list_document_points", list_points)
    monkeypatch.setattr("routers.admin.count_collection_points", count_points)
    return store


@pytest_asyncio.fixture
async def ready_doc_chunks(qdrant_payload_store, test_professor, test_document_ready):
    """Store ``n`` fake Qdrant payloads for the ready document."""

    async def _add(n: int, text_factory=lambda i: f"Chunk {i} content here"):
        chunks = [
            {
                "chunk_index": i,
                "text": text_factory(i),
                "page_label": str(i + 1),
            }
            for i in range(n)
        ]
        qdrant_payload_store[(test_professor.collection, str(test_document_ready.id))] = chunks
        return chunks

    return _add


@pytest_asyncio.fixture
async def test_professor(db_session):
    """Create a professor for test scenarios."""
    prof = Professor(
        name="Test Professor",
        topic="science",
        language=Language.es,
        avatar_id="test-avatar",
        collection="test_collection",
        system_prompt="You are a science professor.",
    )
    db_session.add(prof)
    await db_session.commit()
    await db_session.refresh(prof)
    return prof


@pytest_asyncio.fixture
async def test_document_ready(db_session, test_professor):
    """Create a ready document."""
    doc = Document(
        professor_id=test_professor.id,
        filename="test.pdf",
        format="pdf",
        status=DocumentStatus.ready,
        chunk_count=5,
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc


@pytest_asyncio.fixture
async def test_document_pending(db_session, test_professor):
    """Create a pending document."""
    doc = Document(
        professor_id=test_professor.id,
        filename="pending.pdf",
        format="pdf",
        status=DocumentStatus.pending,
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc


@pytest_asyncio.fixture
async def test_document_error(db_session, test_professor):
    """Create an error document."""
    doc = Document(
        professor_id=test_professor.id,
        filename="error.pdf",
        format="pdf",
        status=DocumentStatus.error,
        error_message="Something went wrong",
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc


@pytest.mark.asyncio
async def test_upload_document_returns_409_when_professor_document_limit_reached(
    async_client, admin_token, test_professor, monkeypatch
):
    """GIVEN a professor at the document limit
    WHEN uploading another document
    THEN the API returns 409 instead of raising an internal NameError.
    """
    monkeypatch.setattr("routers.admin.settings.professor_max_documents", 0)

    response = await async_client.post(
        f"/admin/professors/{test_professor.id}/documents",
        files={"file": ("test.pdf", b"%PDF-1.4 test content", "application/pdf")},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 409
    assert "max" in response.json()["detail"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/documents/{document_id}/chunks
# ══════════════════════════════════════════════════════════════════════════════


class TestGetDocumentChunks:
    """Tests for the GET /admin/documents/{document_id}/chunks endpoint."""

    @pytest.mark.asyncio
    async def test_chunks_document_not_found(
        self, async_client, admin_token
    ):
        """GIVEN a non-existent document_id
        WHEN GET /admin/documents/{document_id}/chunks
        THEN 404 is returned.
        """
        response = await async_client.get(
            "/admin/documents/00000000-0000-0000-0000-000000000000/chunks",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404
        assert "Document not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_chunks_document_not_ready(
        self, async_client, admin_token, test_document_pending
    ):
        """GIVEN a document with status != ready
        WHEN GET /admin/documents/{document_id}/chunks
        THEN 400 is returned.
        """
        response = await async_client.get(
            f"/admin/documents/{test_document_pending.id}/chunks",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 400
        assert "expected 'ready'" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_chunks_empty_collection(
        self, async_client, admin_token, test_document_ready
    ):
        """GIVEN a ready document with no stored chunks
        WHEN GET /admin/documents/{document_id}/chunks
        THEN returns empty chunks list.
        """
        response = await async_client.get(
            f"/admin/documents/{test_document_ready.id}/chunks",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total_chunks"] == 0
        assert body["chunks"] == []
        assert body["document_id"] == str(test_document_ready.id)
        assert body["document_name"] == "test.pdf"

    @pytest.mark.asyncio
    async def test_chunks_with_points(
        self, async_client, admin_token, test_document_ready, ready_doc_chunks
    ):
        """GIVEN a ready document with stored Qdrant chunks
        WHEN GET /admin/documents/{document_id}/chunks
        THEN returns paginated chunks with correct fields.
        """
        await ready_doc_chunks(3)

        response = await async_client.get(
            f"/admin/documents/{test_document_ready.id}/chunks",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total_chunks"] == 3
        assert len(body["chunks"]) == 3
        for idx, chunk in enumerate(body["chunks"]):
            assert chunk["chunk_index"] == idx
            assert chunk["text"] == f"Chunk {idx} content here"
            assert chunk["page_number"] == str(idx + 1)
            assert chunk["score"] is None

    @pytest.mark.asyncio
    async def test_chunks_truncation(
        self, async_client, admin_token, test_document_ready, ready_doc_chunks
    ):
        """GIVEN the full=false query param (default)
        WHEN text exceeds 500 characters
        THEN text SHALL be truncated to 500 chars.
        """
        await ready_doc_chunks(1, text_factory=lambda i: "A" * 1000)

        response = await async_client.get(
            f"/admin/documents/{test_document_ready.id}/chunks",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        chunk = response.json()["chunks"][0]
        assert len(chunk["text"]) == 500

    @pytest.mark.asyncio
    async def test_chunks_full_text(
        self, async_client, admin_token, test_document_ready, ready_doc_chunks
    ):
        """GIVEN the full=true query param
        WHEN text exceeds 500 characters
        THEN text SHALL NOT be truncated.
        """
        await ready_doc_chunks(1, text_factory=lambda i: "A" * 1000)

        response = await async_client.get(
            f"/admin/documents/{test_document_ready.id}/chunks",
            params={"full": "true"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        chunk = response.json()["chunks"][0]
        assert len(chunk["text"]) == 1000

    @pytest.mark.asyncio
    async def test_chunks_pagination(
        self, async_client, admin_token, test_document_ready, ready_doc_chunks
    ):
        """GIVEN offset=1&limit=2 with 4 total chunks
        WHEN GET /admin/documents/{document_id}/chunks
        THEN returns 2 chunks starting from index 1.
        """
        await ready_doc_chunks(4)

        response = await async_client.get(
            f"/admin/documents/{test_document_ready.id}/chunks",
            params={"offset": "1", "limit": "2"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["chunks"]) == 2
        assert body["chunks"][0]["chunk_index"] == 1
        assert body["chunks"][0]["text"] == "Chunk 1 content here"
        assert body["chunks"][1]["chunk_index"] == 2
        assert body["chunks"][1]["text"] == "Chunk 2 content here"

    @pytest.mark.asyncio
    async def test_chunks_limit_max_200(
        self, async_client, admin_token, test_document_ready
    ):
        """GIVEN limit=300 (exceeds max 200)
        THEN the API returns 422 (validation error).
        """
        response = await async_client.get(
            f"/admin/documents/{test_document_ready.id}/chunks",
            params={"limit": "300"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/indexing/status
# ══════════════════════════════════════════════════════════════════════════════


class TestGetIndexingStatus:
    """Tests for the GET /admin/indexing/status endpoint."""

    @pytest.mark.asyncio
    async def test_indexing_status_empty(
        self, async_client, admin_token
    ):
        """GIVEN no professors exist
        WHEN GET /admin/indexing/status
        THEN returns empty collections list with zero summary.
        """
        response = await async_client.get(
            "/admin/indexing/status",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["collections"] == []
        assert body["summary"]["total_collections"] == 0
        assert body["summary"]["total_documents"] == 0

    @pytest.mark.asyncio
    async def test_indexing_status_with_professor_no_docs(
        self, async_client, admin_token, test_professor
    ):
        """GIVEN a professor with no documents
        WHEN GET /admin/indexing/status
        THEN returns collection with zero counts.
        """
        response = await async_client.get(
            "/admin/indexing/status",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["collections"]) == 1
        col = body["collections"][0]
        assert col["professor_id"] == str(test_professor.id)
        assert col["professor_name"] == test_professor.name
        assert col["total_documents"] == 0
        assert col["documents_by_status"] == {}
        assert col["total_chunks"] == 0
        assert col["stored_chunks"] == 0
        assert col["last_indexed_at"] is None
        assert col["last_error"] is None

    @pytest.mark.asyncio
    async def test_indexing_status_with_docs(
        self, async_client, admin_token, test_professor,
        test_document_ready, test_document_pending, test_document_error,
        ready_doc_chunks,
    ):
        """GIVEN a professor with documents in various states
        WHEN GET /admin/indexing/status
        THEN returns correct counts and status breakdown.
        """
        await ready_doc_chunks(3)

        response = await async_client.get(
            "/admin/indexing/status",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["collections"]) == 1
        col = body["collections"][0]

        assert col["total_documents"] == 3
        assert col["documents_by_status"]["ready"] == 1
        assert col["documents_by_status"]["pending"] == 1
        assert col["documents_by_status"]["error"] == 1
        assert col["total_chunks"] == 5  # only ready doc has chunk_count=5
        assert col["stored_chunks"] == 3  # points actually in Qdrant for this collection
        assert col["last_indexed_at"] is not None  # ready doc has uploaded_at
        assert col["last_error"] == "Something went wrong"

        summary = body["summary"]
        assert summary["total_collections"] == 1
        assert summary["total_documents"] == 3
        assert summary["total_chunks"] == 5
        assert summary["collections_with_errors"] == 1

    @pytest.mark.asyncio
    async def test_indexing_status_stored_chunks_empty(
        self, async_client, admin_token, test_professor, test_document_ready
    ):
        """GIVEN a professor whose collection has no stored chunks yet
        WHEN GET /admin/indexing/status
        THEN stored_chunks SHALL be 0 (no error).
        """
        response = await async_client.get(
            "/admin/indexing/status",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        col = response.json()["collections"][0]
        assert col["stored_chunks"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# POST /admin/documents/{document_id}/reindex
# ══════════════════════════════════════════════════════════════════════════════


class TestReindexDocument:
    """Tests for the POST /admin/documents/{document_id}/reindex endpoint."""

    @pytest.mark.asyncio
    async def test_reindex_document_not_found(
        self, async_client, admin_token
    ):
        """GIVEN a non-existent document_id
        WHEN POST /admin/documents/{document_id}/reindex
        THEN 404 is returned.
        """
        response = await async_client.post(
            "/admin/documents/00000000-0000-0000-0000-000000000000/reindex",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_reindex_pending_status(
        self, async_client, admin_token, test_document_pending
    ):
        """GIVEN a document with status pending
        WHEN POST /admin/documents/{document_id}/reindex
        THEN 409 is returned.
        """
        response = await async_client.post(
            f"/admin/documents/{test_document_pending.id}/reindex",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 409
        assert "Cannot reindex" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_reindex_ready_document(
        self, async_client, admin_token, test_document_ready, test_professor
    ):
        """GIVEN a ready document
        WHEN POST /admin/documents/{document_id}/reindex
        THEN status resets to pending and 202 is returned.
        """
        with (
            patch("routers.admin.delete_document_chunks") as mock_delete,
            patch("routers.admin.ingest_document") as mock_ingest,
        ):
            mock_delete.return_value = None

            response = await async_client.post(
                f"/admin/documents/{test_document_ready.id}/reindex",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "reindexing"
        assert body["document_id"] == str(test_document_ready.id)
        mock_delete.assert_called_once_with(
            test_professor.collection, str(test_document_ready.id)
        )

    @pytest.mark.asyncio
    async def test_reindex_ready_document_resets_status(
        self, async_client, admin_token, test_document_ready, db_session
    ):
        """GIVEN a ready document being reindexed
        WHEN the endpoint runs
        THEN the document status is reset to pending and error_message cleared.
        """
        with (
            patch("routers.admin.delete_document_chunks"),
            patch("routers.admin.ingest_document"),
        ):
            response = await async_client.post(
                f"/admin/documents/{test_document_ready.id}/reindex",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 202

        # Verify DB state
        from sqlalchemy import select
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as check_session:
            result = await check_session.execute(
                select(Document).where(Document.id == test_document_ready.id)
            )
            doc = result.scalar_one()
            assert doc.status == DocumentStatus.pending
            assert doc.error_message is None

    @pytest.mark.asyncio
    async def test_reindex_cooldown(
        self, async_client, admin_token, test_document_ready, db_session
    ):
        """GIVEN a reindex was just performed
        WHEN POST /admin/documents/{document_id}/reindex within 60 seconds
        THEN 429 is returned.
        """
        # Clear any previous cooldown state
        import routers.admin as admin_module
        admin_module._reindex_cooldown.clear()

        with (
            patch("routers.admin.delete_document_chunks"),
            patch("routers.admin.ingest_document"),
        ):
            # First reindex should succeed
            response1 = await async_client.post(
                f"/admin/documents/{test_document_ready.id}/reindex",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert response1.status_code == 202

            # Reset document status back to ready for the second call
            # (first reindex reset it to pending, which would cause 409 before cooldown)
            from models.db import DocumentStatus as DocStatus
            test_document_ready.status = DocStatus.ready
            await db_session.commit()

            # Second immediate reindex should hit cooldown
            response2 = await async_client.post(
                f"/admin/documents/{test_document_ready.id}/reindex",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert response2.status_code == 429
            assert "cooldown" in response2.json()["detail"].lower()

        # Clean up
        admin_module._reindex_cooldown.clear()

    @pytest.mark.asyncio
    async def test_reindex_error_document(
        self, async_client, admin_token, test_document_error
    ):
        """GIVEN a document with error status
        WHEN POST /admin/documents/{document_id}/reindex
        THEN the reindex proceeds (not blocked by error status).
        """
        import routers.admin as admin_module
        admin_module._reindex_cooldown.clear()

        with (
            patch("routers.admin.delete_document_chunks"),
            patch("routers.admin.ingest_document"),
        ):
            response = await async_client.post(
                f"/admin/documents/{test_document_error.id}/reindex",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 202
        admin_module._reindex_cooldown.clear()


# ══════════════════════════════════════════════════════════════════════════════
# Admin auth guard tests
# ══════════════════════════════════════════════════════════════════════════════


class TestAdminAuthGuards:
    """Verify that new admin endpoints reject non-admin tokens."""

    @pytest.mark.asyncio
    async def test_chunks_requires_admin(self, async_client, student_token):
        """GIVEN a student token
        WHEN GET /admin/documents/.../chunks
        THEN 403 is returned.
        """
        response = await async_client.get(
            "/admin/documents/00000000-0000-0000-0000-000000000000/chunks",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_indexing_status_requires_admin(self, async_client, student_token):
        """GIVEN a student token
        WHEN GET /admin/indexing/status
        THEN 403 is returned.
        """
        response = await async_client.get(
            "/admin/indexing/status",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_reindex_requires_admin(self, async_client, student_token):
        """GIVEN a student token
        WHEN POST /admin/documents/.../reindex
        THEN 403 is returned.
        """
        response = await async_client.post(
            "/admin/documents/00000000-0000-0000-0000-000000000000/reindex",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert response.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# Professor CRUD
# ══════════════════════════════════════════════════════════════════════════════


class TestProfessorCrud:
    """Integration tests for professor CRUD via admin API."""

    PROFESSOR_DATA = {
        "name": "CRUD Test Professor",
        "topic": "mathematics",
        "language": "en",
        "avatar_id": "crud-avatar",
        "system_prompt": "You are a math professor.",
    }

    @pytest.mark.asyncio
    async def test_create_professor(self, async_client, admin_headers):
        """GIVEN valid professor data
        WHEN POST /admin/professors
        THEN 201 with the professor data including auto-generated fields.
        """
        response = await async_client.post(
            "/admin/professors",
            json=self.PROFESSOR_DATA,
            headers=admin_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["name"] == self.PROFESSOR_DATA["name"]
        assert body["topic"] == self.PROFESSOR_DATA["topic"]
        assert body["language"] == self.PROFESSOR_DATA["language"]
        assert body["collection"].startswith("prof_")
        assert "id" in body
        assert "created_at" in body

    @pytest.mark.asyncio
    async def test_create_professor_no_auth(self, async_client):
        """GIVEN no Authorization header
        WHEN POST /admin/professors
        THEN 403 is returned.
        """
        response = await async_client.post(
            "/admin/professors",
            json=self.PROFESSOR_DATA,
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_professor_as_student(self, async_client, auth_headers):
        """GIVEN a student token (not admin)
        WHEN POST /admin/professors
        THEN 403 is returned.
        """
        response = await async_client.post(
            "/admin/professors",
            json=self.PROFESSOR_DATA,
            headers=auth_headers,
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_professors(self, async_client, admin_headers, test_professor):
        """GIVEN at least one professor exists
        WHEN GET /admin/professors
        THEN 200 with a non-empty list.
        """
        response = await async_client.get(
            "/admin/professors",
            headers=admin_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) >= 1
        ids = [p["id"] for p in body]
        prof_id = str(test_professor.id) if hasattr(test_professor, "id") else test_professor["id"]
        assert prof_id in ids

    @pytest.mark.asyncio
    async def test_get_nonexistent_professor(self, async_client, admin_headers):
        """GIVEN a non-existent professor_id
        WHEN GET /admin/professors/{professor_id}
        THEN 404 is returned.
        """
        response = await async_client.get(
            "/admin/professors/00000000-0000-0000-0000-000000000000",
            headers=admin_headers,
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_professor(self, async_client, admin_headers, test_professor):
        """GIVEN an existing professor
        WHEN PATCH /admin/professors/{professor_id} with updated fields
        THEN 200 with the updated professor data.
        """
        prof_id = str(test_professor.id) if hasattr(test_professor, "id") else test_professor["id"]
        response = await async_client.patch(
            f"/admin/professors/{prof_id}",
            json={"name": "Updated Name", "topic": "physics"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Updated Name"
        assert body["topic"] == "physics"
        # Unchanged fields should remain
        expected_lang = (test_professor.language.value if hasattr(test_professor, "language")
                         else test_professor["language"])
        assert body["language"] == expected_lang

    @pytest.mark.asyncio
    async def test_update_nonexistent_professor(self, async_client, admin_headers):
        """GIVEN a non-existent professor_id
        WHEN PATCH /admin/professors/{professor_id}
        THEN 404 is returned.
        """
        response = await async_client.patch(
            "/admin/professors/00000000-0000-0000-0000-000000000000",
            json={"name": "Nope"},
            headers=admin_headers,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_professor(self, async_client, admin_headers):
        """GIVEN an existing professor
        WHEN DELETE /admin/professors/{professor_id}
        THEN 204 is returned and the professor is no longer fetchable.
        """
        import uuid

        with patch("routers.admin.delete_qdrant_collection"):
            # Create a fresh professor to delete (cannot rely on injected test_professor)
            create_resp = await async_client.post(
                "/admin/professors",
                json=self.PROFESSOR_DATA,
                headers=admin_headers,
            )
            assert create_resp.status_code == 201
            fresh_prof_id = create_resp.json()["id"]

            # Delete it
            delete_resp = await async_client.delete(
                f"/admin/professors/{fresh_prof_id}",
                headers=admin_headers,
            )
            assert delete_resp.status_code == 204

            # Verify it's gone
            get_resp = await async_client.get(
                f"/admin/professors/{fresh_prof_id}",
                headers=admin_headers,
            )
            assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_professor(self, async_client, admin_headers):
        """GIVEN a non-existent professor_id
        WHEN DELETE /admin/professors/{professor_id}
        THEN 404 is returned.
        """
        response = await async_client.delete(
            "/admin/professors/00000000-0000-0000-0000-000000000000",
            headers=admin_headers,
        )
        assert response.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Document upload edge cases
# ══════════════════════════════════════════════════════════════════════════════


class TestDocumentUploadEdgeCases:
    """Tests for document upload validation via admin API."""

    @pytest.mark.asyncio
    async def test_upload_invalid_format_exe(
        self, async_client, admin_headers, test_professor
    ):
        """GIVEN an .exe file (disallowed extension)
        WHEN POST /admin/professors/{professor_id}/documents
        THEN 400 with EXTENSION_NOT_ALLOWED error code.
        """
        prof_id = str(test_professor.id) if hasattr(test_professor, "id") else test_professor["id"]
        response = await async_client.post(
            f"/admin/professors/{prof_id}/documents",
            files={"file": ("virus.exe", b"MZ\x90\x00fake exe", "application/octet-stream")},
            headers=admin_headers,
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error"]["code"] == "EXTENSION_NOT_ALLOWED"
