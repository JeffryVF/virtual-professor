import logging

import fitz
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.readers.base import BaseReader
from llama_index.readers.file import (
    DocxReader,
    PDFReader,
    PptxReader,
)

from core.config import settings
from core.database import AsyncSessionLocal
from models.db import DocumentChunk
from services.embeddings import get_embed_model

CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
log = logging.getLogger(__name__)

_FORMAT_READERS: dict[str, type[BaseReader]] = {
    "pdf": PDFReader,
    "docx": DocxReader,
    "pptx": PptxReader,
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

    # Non-PDF formats skip pre-ingestion PDF validation
    return (True, "")


async def ingest_document(
    document_id: str,
    professor_collection: str,
    file_path: str,
    file_format: str,
) -> None:
    """Background task: parse, chunk, embed and store a document in pgvector."""
    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import AsyncSession

    from models.db import Document, DocumentStatus

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one()
            doc.status = DocumentStatus.processing
            doc.error_message = None
            await db.commit()
            log.info("Starting document ingestion: document_id=%s format=%s", document_id, file_format)

            # Pre-ingestion validation
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

            embed_model = get_embed_model()

            # Load and parse document
            if file_format == "url":
                from pathlib import Path
                from llama_index.readers.web import SimpleWebPageReader
                url = Path(file_path).read_text().strip()
                documents = SimpleWebPageReader(html_to_text=True).load_data([url])
            elif file_format in _FORMAT_READERS:
                reader = _FORMAT_READERS[file_format]()
                documents = reader.load_data(file=file_path)
            else:
                # Fallback: read as plain text
                from llama_index.core import SimpleDirectoryReader
                documents = SimpleDirectoryReader(input_files=[file_path]).load_data()

            # Chunk
            splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
            nodes = splitter.get_nodes_from_documents(documents)

            # Post-parse validation: ensure at least one non-empty node
            if not nodes or all(not node.get_content().strip() for node in nodes):
                doc.status = DocumentStatus.error
                doc.error_message = "EMPTY_CHUNKS: Document produced no usable text content after chunking"
                await db.commit()
                log.warning("Document produced no chunks: document_id=%s", document_id)
                return

            # Fetch document for source_filename metadata
            result = await db.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one()

            # Embed all chunks in a single batch
            embeddings = embed_model.get_text_embedding_batch(
                [node.get_content() for node in nodes]
            )

            # Replace any previous chunks for this document, then insert fresh rows
            await db.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
            for idx, (node, embedding) in enumerate(zip(nodes, embeddings)):
                db.add(
                    DocumentChunk(
                        document_id=document_id,
                        professor_collection=professor_collection,
                        chunk_index=idx,
                        text=node.get_content(),
                        embedding=embedding,
                        page_label=node.metadata.get("page_label"),
                        chunk_metadata={
                            "document_id": document_id,
                            "professor_collection": professor_collection,
                            "source_filename": doc.filename,
                        },
                    )
                )

            # Mark document as ready
            doc.status = DocumentStatus.ready
            doc.chunk_count = len(nodes)
            await db.commit()
            log.info("Document ingestion completed: document_id=%s chunks=%s", document_id, len(nodes))

        except Exception as exc:
            result = await db.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one()
            doc.status = DocumentStatus.error
            doc.error_message = str(exc)
            await db.commit()
            log.exception("Document ingestion failed: document_id=%s", document_id)
            raise


async def delete_qdrant_collection(collection_name: str) -> None:
    """Delete every stored chunk for a professor collection (used when removing a professor).

    Kept under a legacy name for call-site compatibility; there is no Qdrant anymore.
    """
    from sqlalchemy import delete, select

    from models.db import Document, DocumentChunk, Professor

    async with AsyncSessionLocal() as db:
        prof_result = await db.execute(
            select(Professor).where(Professor.collection == collection_name)
        )
        prof = prof_result.scalar_one_or_none()
        if prof is not None:
            doc_result = await db.execute(
                select(Document.id).where(Document.professor_id == prof.id)
            )
            for (doc_id,) in doc_result.all():
                await db.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == doc_id)
                )
        await db.commit()


async def delete_document_chunks(professor_collection: str, document_id: str) -> None:
    """Remove all stored chunks that belong to a specific document."""
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        await db.commit()