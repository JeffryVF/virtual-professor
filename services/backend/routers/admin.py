import logging
import os
import shutil
import uuid
from uuid import UUID

import magic
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db
from dependencies.auth import verify_admin_or_deprecated_key
from models.db import Document, DocumentStatus, Message, Professor
from models.db import Session as DBSession
from models.schemas import (
    DocumentResponse,
    MessageResponse,
    ProfessorCreate,
    ProfessorResponse,
    ProfessorUpdate,
    SessionResponse,
)
from services.ingestion import delete_document_chunks, delete_qdrant_collection, ingest_document

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

UPLOAD_DIR = "/app/uploads"

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
    save_path = os.path.join(UPLOAD_DIR, str(professor_id), f"{doc_id}.{ext}")
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
