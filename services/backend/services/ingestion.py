import asyncio
import logging
import os

import fitz
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.readers.base import BaseReader
from llama_index.core.schema import NodeRelationship, RelatedNodeInfo
from llama_index.readers.file import (
    DocxReader,
    PDFReader,
    PptxReader,
)
from llama_index.vector_stores.qdrant import QdrantVectorStore
from sqlalchemy import or_, select

from core.config import settings
from core.database import AsyncSessionLocal
from core.qdrant import get_qdrant_client
from models.db import Document, DocumentStatus, Professor
from services.embeddings import get_embed_model
from services.qdrant_store import (
    VP_DOCUMENT_ID_KEY,
    delete_collection,
    delete_document_points,
    ensure_collection,
)

log = logging.getLogger(__name__)

CHUNK_SIZE = 512
CHUNK_OVERLAP = 50

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


def document_source_path(
    professor_id,
    document_id,
    file_format: str,
    upload_dir: str | None = None,
) -> str:
    """On-disk path used at upload time and when resuming vectorization."""
    return os.path.join(
        upload_dir or settings.upload_dir,
        str(professor_id),
        f"{document_id}.{file_format}",
    )


def stamp_chunk_document_id(node, document_id: str) -> None:
    """Bind a chunk to the Postgres document UUID in LlamaIndex + Qdrant payload.

    LlamaIndex copies ``node.ref_doc_id`` onto payload ``document_id`` / ``doc_id``,
    overwriting any metadata value. Set the SOURCE relationship so deletes and
    the admin chunk list match the uploaded document, not the PDF reader id.
    """
    doc_id = str(document_id)
    node.metadata["document_id"] = doc_id
    node.metadata[VP_DOCUMENT_ID_KEY] = doc_id
    node.relationships[NodeRelationship.SOURCE] = RelatedNodeInfo(node_id=doc_id)


def _index_nodes(nodes, professor_collection: str) -> bool:
    """Embed and upsert nodes into the professor's Qdrant collection.

    Returns True when the collection was recreated because EMBED_DIM changed.
    """
    qdrant = get_qdrant_client()
    try:
        wiped = ensure_collection(qdrant, professor_collection)
        embed_model = get_embed_model()
        vector_store = QdrantVectorStore(client=qdrant, collection_name=professor_collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        VectorStoreIndex(nodes, storage_context=storage_context, embed_model=embed_model)
        return wiped
    finally:
        qdrant.close()


async def ingest_document(
    document_id: str,
    professor_collection: str,
    file_path: str,
    file_format: str,
) -> None:
    """Background task: parse, chunk, embed and store a document in Qdrant."""
    wiped = False
    professor_id = None
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

            if file_format == "url":
                from pathlib import Path
                from llama_index.readers.web import SimpleWebPageReader
                url = Path(file_path).read_text().strip()
                documents = SimpleWebPageReader(html_to_text=True).load_data([url])
            elif file_format in _FORMAT_READERS:
                reader = _FORMAT_READERS[file_format]()
                documents = reader.load_data(file=file_path)
            else:
                from llama_index.core import SimpleDirectoryReader
                documents = SimpleDirectoryReader(input_files=[file_path]).load_data()

            splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
            nodes = splitter.get_nodes_from_documents(documents)

            if not nodes or all(not node.get_content().strip() for node in nodes):
                doc.status = DocumentStatus.error
                doc.error_message = "EMPTY_CHUNKS: Document produced no usable text content after chunking"
                await db.commit()
                log.warning("Document produced no chunks: document_id=%s", document_id)
                return

            for idx, node in enumerate(nodes):
                stamp_chunk_document_id(node, document_id)
                node.metadata["professor_collection"] = professor_collection
                node.metadata["source_filename"] = doc.filename
                node.metadata["chunk_index"] = idx
                if "page_label" not in node.metadata:
                    node.metadata["page_label"] = node.metadata.get("page_number")

            await asyncio.to_thread(delete_document_points, professor_collection, document_id)
            wiped = await asyncio.to_thread(_index_nodes, nodes, professor_collection)
            professor_id = doc.professor_id

            doc.status = DocumentStatus.ready
            doc.chunk_count = len(nodes)
            await db.commit()
            log.warning(
                "Document ingestion completed: document_id=%s chunks=%s",
                document_id,
                len(nodes),
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

    if wiped and professor_id is not None:
        await _reembed_professor_after_dim_change(
            professor_id, document_id, professor_collection
        )


async def _reembed_professor_after_dim_change(
    professor_id,
    skip_document_id: str,
    professor_collection: str,
) -> None:
    """Re-ingest sibling documents after a Qdrant collection is resized."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Document).where(
                Document.professor_id == professor_id,
                Document.id != skip_document_id,
                Document.status != DocumentStatus.error,
            )
        )
        others = list(result.scalars().all())

    if not others:
        return

    log.warning(
        "Re-embedding %s sibling document(s) after EMBED_DIM change in %s",
        len(others),
        professor_collection,
    )
    for other in others:
        save_path = document_source_path(other.professor_id, other.id, other.format)
        if not os.path.isfile(save_path):
            log.warning(
                "Skipping re-embed of %s: source file is missing",
                other.id,
            )
            continue
        try:
            await ingest_document(
                str(other.id), professor_collection, save_path, other.format
            )
        except Exception:
            log.exception("Failed to re-embed sibling document %s", other.id)


async def resume_incomplete_ingestion() -> None:
    """Embed documents that never finished indexing, if the source file still exists.

    Covers crashed uploads (``pending``/``processing``) and ready rows that
    recorded zero chunks (interrupted before Qdrant upsert).
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Document, Professor)
            .join(Professor, Document.professor_id == Professor.id)
            .where(
                or_(
                    Document.status.in_(
                        (DocumentStatus.pending, DocumentStatus.processing)
                    ),
                    Document.chunk_count == 0,
                )
            )
            .where(Document.status != DocumentStatus.error)
        )
        jobs = list(result.all())

    if not jobs:
        return

    log.warning("Vectorizing %s document(s) missing Qdrant embeddings", len(jobs))
    for doc, prof in jobs:
        save_path = document_source_path(doc.professor_id, doc.id, doc.format)
        if not os.path.isfile(save_path):
            async with AsyncSessionLocal() as db:
                fresh = await db.get(Document, doc.id)
                if fresh is None:
                    continue
                fresh.status = DocumentStatus.error
                fresh.error_message = (
                    "SOURCE_MISSING: uploaded file is gone. Re-upload the document to vectorize it."
                )
                await db.commit()
            continue
        try:
            await ingest_document(str(doc.id), prof.collection, save_path, doc.format)
        except Exception:
            log.exception("Failed to vectorize document %s on startup", doc.id)


async def delete_qdrant_collection(collection_name: str) -> None:
    """Delete the professor's Qdrant collection (used when removing a professor)."""
    await asyncio.to_thread(delete_collection, collection_name)


async def delete_document_chunks(professor_collection: str, document_id: str) -> None:
    """Remove all Qdrant points that belong to a specific document."""
    await asyncio.to_thread(delete_document_points, professor_collection, document_id)
