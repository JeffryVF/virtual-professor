import os
import shutil
import uuid
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Security, UploadFile
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db
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

router = APIRouter()

UPLOAD_DIR = "/app/uploads"

_admin_key_scheme = APIKeyHeader(name="X-Admin-Key", auto_error=True)


async def verify_admin(api_key: str = Security(_admin_key_scheme)):
    if api_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")


# ── Professors ────────────────────────────────────────────────────────────────

@router.post("/professors", response_model=ProfessorResponse, status_code=201)
async def create_professor(
    data: ProfessorCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
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
    _: None = Depends(verify_admin),
):
    result = await db.execute(select(Professor))
    return result.scalars().all()


@router.get("/professors/{professor_id}", response_model=ProfessorResponse)
async def get_professor(
    professor_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
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
    _: None = Depends(verify_admin),
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
    _: None = Depends(verify_admin),
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
    _: None = Depends(verify_admin),
):
    result = await db.execute(select(Professor).where(Professor.id == professor_id))
    prof = result.scalar_one_or_none()
    if not prof:
        raise HTTPException(status_code=404, detail="Professor not found")

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
    _: None = Depends(verify_admin),
):
    result = await db.execute(select(Document).where(Document.professor_id == professor_id))
    return result.scalars().all()


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
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
    _: None = Depends(verify_admin),
):
    result = await db.execute(select(DBSession).order_by(DBSession.started_at.desc()))
    return result.scalars().all()


@router.get("/sessions/{session_id}/history", response_model=list[MessageResponse])
async def session_history(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.timestamp)
    )
    return result.scalars().all()
