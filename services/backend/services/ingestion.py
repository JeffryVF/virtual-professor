"""Upload professor documents to Cloudflare AI Search for indexing."""

from __future__ import annotations

import logging
import os
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import fitz
import httpx

from core import cloudflare
from core.config import settings
from core.database import AsyncSessionLocal
from models.db import Document, DocumentStatus, Professor
from sqlalchemy import select

log = logging.getLogger(__name__)

_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "html": "text/html",
    "md": "text/markdown",
}


def _validate_document(file_path: str, file_format: str, max_pages: int) -> tuple[bool, str]:
    """Validate a document before ingestion.

    For PDFs (via PyMuPDF/fitz):
      - Reject if password-protected
      - Reject if page count exceeds max_pages
      - Reject if no page has extractable text (scanned/image-only)
    For other formats (docx, pptx, txt): no PDF-specific checks.

    Returns (is_valid, error_message). On success, error_message is empty string.
    """
    if file_format == "pdf":
        try:
            doc = fitz.open(file_path)
        except Exception:
            return (False, "PDF_CORRUPT: PDF file is corrupted or cannot be opened")

        with doc:
            if doc.is_encrypted:
                return (False, "PDF_PASSWORD_PROTECTED: PDF is password-protected and cannot be processed")

            if doc.page_count > max_pages:
                return (
                    False,
                    f"PDF_TOO_MANY_PAGES: PDF has {doc.page_count} pages, maximum is {max_pages}",
                )

            for page in doc:
                text = page.get_text().strip()
                if text:
                    return (True, "")

            return (False, "PDF_NO_EXTRACTABLE_TEXT: PDF contains no extractable text (possible scanned document)")

    return (True, "")


def document_source_path(
    professor_id,
    document_id,
    file_format: str,
    upload_dir: str | None = None,
) -> str:
    """On-disk path used at upload time and when resuming indexing."""
    return os.path.join(
        upload_dir or settings.upload_dir,
        str(professor_id),
        f"{document_id}.{file_format}",
    )


def _pptx_to_text(file_path: str) -> str:
    """Extract slide text from a PPTX without Office/LlamaIndex readers."""
    texts: list[str] = []
    with zipfile.ZipFile(file_path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
        for name in names:
            root = ET.fromstring(archive.read(name))
            for node in root.iter():
                if node.tag.endswith("}t") and node.text:
                    texts.append(node.text)
    return "\n".join(texts)


async def _payload_for_upload(
    file_path: str,
    file_format: str,
    filename: str,
    collection: str,
    document_id: str,
) -> tuple[str, bytes, str]:
    """Return (item_key, bytes, content_type) ready for Cloudflare."""
    if file_format == "url":
        url = Path(file_path).read_text().strip()
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
            body = response.content
            content_type = response.headers.get("content-type", "text/html").split(";")[0]
        upload_name = filename if filename.endswith((".html", ".htm", ".txt", ".md")) else f"{Path(filename).stem}.html"
        if "html" not in content_type and not content_type.startswith("text/"):
            content_type = "text/html"
        return cloudflare.item_key(collection, document_id, upload_name), body, content_type

    if file_format == "pptx":
        text = _pptx_to_text(file_path)
        if not text.strip():
            raise ValueError("EMPTY_CHUNKS: Document produced no usable text content")
        key = cloudflare.item_key(collection, document_id, f"{Path(filename).stem}.txt")
        return key, text.encode("utf-8"), "text/plain"

    content = Path(file_path).read_bytes()
    content_type = _CONTENT_TYPES.get(file_format, "application/octet-stream")
    return cloudflare.item_key(collection, document_id, filename), content, content_type


async def ingest_document(
    document_id: str,
    professor_collection: str,
    file_path: str,
    file_format: str,
) -> None:
    """Background task: validate and index a document in Cloudflare AI Search."""
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one_or_none()
            if doc is None:
                log.error("ingest_document: document %s not found", document_id)
                return
            doc.status = DocumentStatus.processing
            doc.error_message = None
            await db.commit()
            log.warning(
                "Starting document ingestion: document_id=%s format=%s",
                document_id,
                file_format,
            )

            is_valid, error_msg = _validate_document(
                file_path,
                file_format,
                max_pages=settings.upload_max_pages,
            )
            if not is_valid:
                doc.status = DocumentStatus.error
                doc.error_message = error_msg
                await db.commit()
                log.warning("Document validation failed: document_id=%s error=%s", document_id, error_msg)
                return

            key, content, content_type = await _payload_for_upload(
                file_path,
                file_format,
                doc.filename,
                professor_collection,
                document_id,
            )
            if not content.strip():
                doc.status = DocumentStatus.error
                doc.error_message = "EMPTY_CHUNKS: Document produced no usable text content after chunking"
                await db.commit()
                log.warning("Document produced no content: document_id=%s", document_id)
                return

            item = await cloudflare.upload_item(key, content, content_type)
            status = str(item.get("status") or "completed").lower()
            if status == "error":
                doc.status = DocumentStatus.error
                doc.error_message = str(item.get("error") or item.get("message") or "Cloudflare indexing failed")
                await db.commit()
                return

            doc.status = DocumentStatus.ready
            doc.chunk_count = int(item.get("chunks_count") or item.get("chunk_count") or 0)
            await db.commit()
            log.warning(
                "Document ingestion completed: document_id=%s chunks=%s key=%s",
                document_id,
                doc.chunk_count,
                key,
            )
        except Exception as exc:
            log.exception("Document ingestion failed: document_id=%s", document_id)
            result = await db.execute(select(Document).where(Document.id == document_id))
            failed = result.scalar_one_or_none()
            if failed is not None:
                failed.status = DocumentStatus.error
                failed.error_message = str(exc)
                await db.commit()
            raise


async def resume_incomplete_ingestion() -> None:
    """Re-index documents that never finished uploading to Cloudflare."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Document, Professor)
            .join(Professor, Document.professor_id == Professor.id)
            .where(
                Document.status.in_(
                    (DocumentStatus.pending, DocumentStatus.processing)
                )
            )
        )
        jobs = list(result.all())

    if not jobs:
        return

    log.warning("Re-indexing %s document(s) in Cloudflare AI Search", len(jobs))
    for doc, prof in jobs:
        save_path = document_source_path(doc.professor_id, doc.id, doc.format)
        if not os.path.isfile(save_path):
            async with AsyncSessionLocal() as db:
                fresh = await db.get(Document, doc.id)
                if fresh is None:
                    continue
                fresh.status = DocumentStatus.error
                fresh.error_message = (
                    "SOURCE_MISSING: uploaded file is gone. Re-upload the document to index it."
                )
                await db.commit()
            continue
        try:
            await ingest_document(str(doc.id), prof.collection, save_path, doc.format)
        except Exception:
            log.exception("Failed to index document %s on startup", doc.id)


async def delete_professor_index(collection_name: str) -> None:
    """Delete every Cloudflare item stored under a professor collection prefix."""
    if not cloudflare.is_configured():
        return
    items = await cloudflare.list_items()
    prefix = f"{collection_name}/"
    for item in items:
        key = str(item.get("key") or "")
        item_id = str(item.get("id") or "")
        if key.startswith(prefix) and item_id:
            await cloudflare.delete_item(item_id)


async def delete_qdrant_collection(collection_name: str) -> None:
    """Legacy alias used by admin professor deletion."""
    await delete_professor_index(collection_name)


async def delete_document_chunks(professor_collection: str, document_id: str) -> None:
    """Remove the Cloudflare item(s) that belong to a specific document."""
    if not cloudflare.is_configured():
        return
    items = await cloudflare.list_items()
    prefix = f"{professor_collection}/{document_id}/"
    for item in items:
        key = str(item.get("key") or "")
        item_id = str(item.get("id") or "")
        if key.startswith(prefix) and item_id:
            await cloudflare.delete_item(item_id)
