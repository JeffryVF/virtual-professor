import json
import logging
import os
import shutil
import time
import uuid
from uuid import UUID

import magic
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db
from dependencies.auth import require_admin, verify_admin_or_deprecated_key
from models.db import Document, DocumentStatus, Message, Professor
from models.db import Session as DBSession
from models.schemas import (
    ChunkDetail,
    CollectionStatus,
    DocumentChunksResponse,
    DocumentResponse,
    IndexingStatusResponse,
    MessageResponse,
    ProfessorCreate,
    ProfessorResponse,
    ProfessorUpdate,
    SessionResponse,
)
from services.ingestion import (
    delete_document_chunks,
    delete_qdrant_collection,
    document_source_path,
    ingest_document,
)
from services.rag import list_document_chunks


log = logging.getLogger(__name__)

# Structured error codes for pre-upload validation
# Maps error_code -> (http_status, default_message)
ERROR_RESPONSES: dict[str, tuple[int, str]] = {
    "EXTENSION_NOT_ALLOWED": (400, "File extension is not in the allowed formats list"),
    "INVALID_FILE_TYPE": (400, "File MIME type does not match its declared extension"),
    "FILE_TOO_LARGE": (413, "File size exceeds the maximum allowed size"),
}


def validate_upload_file(
    file: UploadFile,
    max_size_mb: int,
    allowed_formats: list[str],
) -> tuple[bool, str | None, str | None]:
    """Validate an uploaded file before saving it to disk.

    Checks (in order):
      1. Extension is in the allowed list
      2. MIME type (via magic bytes) matches the claimed extension
      3. File size does not exceed the limit

    After reading magic bytes, the file pointer is seeked back to 0.

    Returns (is_valid, error_code, error_message).
    """
    # 1. Extension check
    ext = os.path.splitext(file.filename or "")[1].lstrip(".").lower()
    if not ext or ext not in allowed_formats:
        return (
            False,
            "EXTENSION_NOT_ALLOWED",
            f"File extension '.{ext}' is not allowed. Allowed: {', '.join(allowed_formats)}",
        )

    # 2. MIME type check (for formats with predictable magic bytes)
    magic_bytes = file.file.read(4096)
    try:
        detected_mime = magic.from_buffer(magic_bytes, mime=True)
    except Exception:
        detected_mime = ""

    file.file.seek(0)

    _EXPECTED_MIME_PREFIXES = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml",
    }
    expected_prefix = _EXPECTED_MIME_PREFIXES.get(ext)
    if expected_prefix and not detected_mime.startswith(expected_prefix):
        return (
            False,
            "INVALID_FILE_TYPE",
            f"File MIME type '{detected_mime}' does not match extension '.{ext}'",
        )

    # 3. File size check
    file.file.seek(0, 2)  # seek to end
    size_bytes = file.file.tell()
    file.file.seek(0)

    max_bytes = max_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        size_mb = size_bytes / (1024 * 1024)
        return (
            False,
            "FILE_TOO_LARGE",
            f"File size {size_mb:.1f} MB exceeds maximum of {max_size_mb} MB",
        )

    return (True, None, None)

router = APIRouter()

UPLOAD_DIR = settings.upload_dir

# ── Professors ────────────────────────────────────────────────────────────────

@router.post("/professors", response_model=ProfessorResponse, status_code=201)
async def create_professor(
    data: ProfessorCreate,
    db: AsyncSession = Depends(get_db),
    _ = Depends(verify_admin_or_deprecated_key),
):
    collection = f"prof_{uuid.uuid4().hex[:12]}"
    professor = Professor(**data.model_dump(), collection=collection)
    db.add(professor)
    await db.commit()
    await db.refresh(professor)
    return professor


@router.get("/professors", response_model=list[ProfessorResponse])
async def list_professors(
    db: AsyncSession = Depends(get_db),
    _ = Depends(verify_admin_or_deprecated_key),
):
    result = await db.execute(select(Professor))
    return result.scalars().all()


@router.get("/professors/{professor_id}", response_model=ProfessorResponse)
async def get_professor(
    professor_id: UUID,
    db: AsyncSession = Depends(get_db),
    _ = Depends(verify_admin_or_deprecated_key),
):
    result = await db.execute(select(Professor).where(Professor.id == professor_id))
    prof = result.scalar_one_or_none()
    if not prof:
        raise HTTPException(status_code=404, detail="Professor not found")
    return prof


@router.patch("/professors/{professor_id}", response_model=ProfessorResponse)
async def update_professor(
    professor_id: UUID,
    data: ProfessorUpdate,
    db: AsyncSession = Depends(get_db),
    _ = Depends(verify_admin_or_deprecated_key),
):
    result = await db.execute(select(Professor).where(Professor.id == professor_id))
    prof = result.scalar_one_or_none()
    if not prof:
        raise HTTPException(status_code=404, detail="Professor not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(prof, field, value)
    await db.commit()
    await db.refresh(prof)
    return prof


@router.delete("/professors/{professor_id}", status_code=204)
async def delete_professor(
    professor_id: UUID,
    db: AsyncSession = Depends(get_db),
    _ = Depends(verify_admin_or_deprecated_key),
):
    result = await db.execute(select(Professor).where(Professor.id == professor_id))
    prof = result.scalar_one_or_none()
    if not prof:
        raise HTTPException(status_code=404, detail="Professor not found")
    await delete_qdrant_collection(prof.collection)
    await db.delete(prof)
    await db.commit()


# ── Documents ─────────────────────────────────────────────────────────────────

@router.post("/professors/{professor_id}/documents", response_model=DocumentResponse, status_code=201)
async def upload_document(
    professor_id: UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _ = Depends(verify_admin_or_deprecated_key),
):
    result = await db.execute(select(Professor).where(Professor.id == professor_id))
    prof = result.scalar_one_or_none()
    if not prof:
        raise HTTPException(status_code=404, detail="Professor not found")

    # ── Document count limit ────────────────────────────────────────────────
    count_result = await db.execute(
        select(func.count(Document.id)).where(Document.professor_id == professor_id)
    )
    doc_count = count_result.scalar() or 0
    if doc_count >= settings.professor_max_documents:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Professor already has {doc_count} documents (max: {settings.professor_max_documents}). "
            f"Remove existing documents before uploading new ones.",
        )

    # ── Processing check ───────────────────────────────────────────────────
    processing_result = await db.execute(
        select(Document.id).where(
            Document.professor_id == professor_id,
            Document.status == DocumentStatus.processing,
        ).limit(1)
    )
    if processing_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another document is currently being processed for this professor. "
            "Wait for processing to complete before uploading another.",
        )

    # Pre-upload validation
    allowed = settings.upload_allowed_formats.split(",")
    is_valid, err_code, err_msg = validate_upload_file(
        file,
        max_size_mb=settings.upload_max_size_mb,
        allowed_formats=allowed,
    )
    if not is_valid:
        status_code, default_msg = ERROR_RESPONSES.get(err_code or "", (400, "Validation failed"))
        raise HTTPException(
            status_code=status_code,
            detail={"error": {"code": err_code, "message": err_msg or default_msg}},
        )

    ext = os.path.splitext(file.filename or "")[1].lstrip(".").lower() or "bin"
    doc_id = uuid.uuid4()
    save_path = document_source_path(professor_id, doc_id, ext, upload_dir=UPLOAD_DIR)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    doc = Document(
        id=doc_id,
        professor_id=professor_id,
        filename=file.filename or f"{doc_id}.{ext}",
        format=ext,
        status=DocumentStatus.pending,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Background task opens its own DB session — do not pass `db` here
    background_tasks.add_task(ingest_document, str(doc_id), prof.collection, save_path, ext)
    return doc


@router.get("/professors/{professor_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    professor_id: UUID,
    db: AsyncSession = Depends(get_db),
    _ = Depends(verify_admin_or_deprecated_key),
):
    result = await db.execute(select(Document).where(Document.professor_id == professor_id))
    return result.scalars().all()


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    _ = Depends(verify_admin_or_deprecated_key),
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    prof_result = await db.execute(select(Professor).where(Professor.id == doc.professor_id))
    prof = prof_result.scalar_one()

    await delete_document_chunks(prof.collection, str(document_id))
    await db.delete(doc)
    await db.commit()


# ── Chunks ─────────────────────────────────────────────────────────────────────

@router.get("/documents/{document_id}/chunks", response_model=DocumentChunksResponse)
async def get_document_chunks(
    document_id: UUID,
    full: bool = Query(False, description="Return full text instead of truncated 500 chars"),
    offset: int = Query(0, ge=0, description="Zero-based offset for pagination"),
    limit: int = Query(50, ge=1, le=200, description="Page size (max 200)"),
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_admin_or_deprecated_key),
):
    """Return paginated chunks for a specific document from Cloudflare AI Search."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.status != DocumentStatus.ready:
        raise HTTPException(
            status_code=400,
            detail=f"Document status is '{doc.status.value}', expected 'ready'",
        )

    prof_result = await db.execute(select(Professor).where(Professor.id == doc.professor_id))
    prof = prof_result.scalar_one()
    scored = await list_document_chunks(
        prof.collection,
        str(document_id),
        doc.filename,
        offset=offset,
        limit=limit,
    )
    if offset == 0:
        total = len(scored)
    else:
        total = doc.chunk_count or (offset + len(scored))

    chunks: list[ChunkDetail] = []
    for idx, chunk in enumerate(scored, start=offset):
        display_text = chunk.text[:500] if not full else chunk.text
        chunks.append(
            ChunkDetail(
                chunk_index=idx,
                text=display_text,
                score=chunk.score,
                page_number=chunk.page_label,
            )
        )

    return DocumentChunksResponse(
        document_id=str(document_id),
        document_name=doc.filename,
        total_chunks=total,
        chunks=chunks,
    )


# ── Reindex ───────────────────────────────────────────────────────────────────

# In-memory cooldown: no more than 1 reindex per document per 60 seconds
_reindex_cooldown: dict[str, float] = {}


@router.post("/documents/{document_id}/reindex", status_code=202)
async def reindex_document(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_admin_or_deprecated_key),
):
    """Reset a document to pending and re-run ingestion via background task."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc_id_str = str(document_id)

    # Cooldown check first — prevents hammering regardless of document status
    now = time.time()
    last = _reindex_cooldown.get(doc_id_str, 0)
    if now - last < 60:
        remaining = int(60 - (now - last))
        raise HTTPException(
            status_code=429,
            detail=f"Reindex cooldown active: try again in {remaining}s",
        )
    _reindex_cooldown[doc_id_str] = now

    if doc.status in (DocumentStatus.pending, DocumentStatus.processing):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot reindex document with status '{doc.status.value}'",
        )

    # Reset document
    doc.status = DocumentStatus.pending
    doc.error_message = None
    await db.commit()

    # Get professor for collection name
    prof_result = await db.execute(select(Professor).where(Professor.id == doc.professor_id))
    prof = prof_result.scalar_one()

    # Delete existing document chunks
    await delete_document_chunks(prof.collection, doc_id_str)

    # Construct file path
    save_path = document_source_path(doc.professor_id, doc_id_str, doc.format, upload_dir=UPLOAD_DIR)

    # Schedule background ingestion
    background_tasks.add_task(ingest_document, doc_id_str, prof.collection, save_path, doc.format)

    return {"status": "reindexing", "document_id": doc_id_str}


# ── Indexing Status ───────────────────────────────────────────────────────────

@router.get("/indexing/status", response_model=IndexingStatusResponse)
async def get_indexing_status(
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_admin_or_deprecated_key),
):
    """Return per-collection indexing statistics for all professors."""
    prof_result = await db.execute(select(Professor))
    professors = prof_result.scalars().all()

    collection_statuses: list[CollectionStatus] = []

    for prof in professors:
        # Document stats from DB
        doc_count_result = await db.execute(
            select(Document.status, func.count(Document.id)).where(
                Document.professor_id == prof.id
            ).group_by(Document.status)
        )
        doc_counts: dict[str, int] = {}
        for status_value, count in doc_count_result:
            doc_counts[status_value.value] = count

        # Sum chunk_count
        chunk_sum_result = await db.execute(
            select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
                Document.professor_id == prof.id
            )
        )
        total_chunks = chunk_sum_result.scalar() or 0

        # Total documents
        total_docs_result = await db.execute(
            select(func.count(Document.id)).where(Document.professor_id == prof.id)
        )
        total_documents = total_docs_result.scalar() or 0

        # Last indexed at (most recent ready document)
        last_ready_result = await db.execute(
            select(Document.uploaded_at)
            .where(Document.professor_id == prof.id, Document.status == DocumentStatus.ready)
            .order_by(Document.uploaded_at.desc())
            .limit(1)
        )
        last_ready = last_ready_result.scalar_one_or_none()
        last_indexed_at = last_ready.isoformat() if last_ready else None

        # Last error (most recent error document's message)
        last_error_result = await db.execute(
            select(Document.error_message)
            .where(Document.professor_id == prof.id, Document.status == DocumentStatus.error)
            .order_by(Document.uploaded_at.desc())
            .limit(1)
        )
        last_error = last_error_result.scalar_one_or_none()

        stored_chunks = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
                        Document.professor_id == prof.id,
                        Document.status == DocumentStatus.ready,
                    )
                )
            ).scalar()
            or 0
        )

        collection_statuses.append(
            CollectionStatus(
                professor_id=str(prof.id),
                professor_name=prof.name,
                collection=prof.collection,
                total_documents=total_documents,
                documents_by_status=doc_counts,
                total_chunks=total_chunks,
                stored_chunks=stored_chunks,
                last_indexed_at=last_indexed_at,
                last_error=last_error,
            )
        )

    # Compute summary
    total_collections = len(collection_statuses)
    total_documents = sum(c.total_documents for c in collection_statuses)
    total_chunks = sum(c.total_chunks for c in collection_statuses)
    collections_with_errors = sum(
        1 for c in collection_statuses if c.last_error is not None
    )

    return IndexingStatusResponse(
        collections=collection_statuses,
        summary={
            "total_collections": total_collections,
            "total_documents": total_documents,
            "total_chunks": total_chunks,
            "collections_with_errors": collections_with_errors,
        },
    )


# ── Sessions (admin view) ─────────────────────────────────────────────────────

@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    _ = Depends(verify_admin_or_deprecated_key),
):
    result = await db.execute(select(DBSession).order_by(DBSession.started_at.desc()))
    return result.scalars().all()


@router.get("/sessions/{session_id}/history", response_model=list[MessageResponse])
async def session_history(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    _ = Depends(verify_admin_or_deprecated_key),
):
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.timestamp)
    )
    return result.scalars().all()
