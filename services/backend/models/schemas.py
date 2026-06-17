from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr


class LanguageEnum(str, Enum):
    es = "es"
    en = "en"
    both = "both"


class DocumentStatusEnum(str, Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    error = "error"


# ── Professor ────────────────────────────────────────────────────────────────

class ProfessorCreate(BaseModel):
    name: str
    topic: str
    language: LanguageEnum
    avatar_id: str
    system_prompt: str


class ProfessorUpdate(BaseModel):
    name: Optional[str] = None
    topic: Optional[str] = None
    language: Optional[LanguageEnum] = None
    avatar_id: Optional[str] = None
    system_prompt: Optional[str] = None


class ProfessorResponse(BaseModel):
    id: UUID
    name: str
    topic: str
    language: LanguageEnum
    avatar_id: str
    collection: str
    system_prompt: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Document ─────────────────────────────────────────────────────────────────

class DocumentResponse(BaseModel):
    id: UUID
    professor_id: UUID
    filename: str
    format: str
    status: DocumentStatusEnum
    chunk_count: int
    error_message: Optional[str]
    uploaded_at: datetime

    model_config = {"from_attributes": True}


# ── Student ───────────────────────────────────────────────────────────────────

class StudentCreate(BaseModel):
    name: str
    email: str
    language: LanguageEnum


class StudentResponse(BaseModel):
    id: UUID
    name: str
    email: str
    language: LanguageEnum
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Session ───────────────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    student_id: UUID
    professor_id: UUID


class SessionResponse(BaseModel):
    id: UUID
    student_id: UUID
    professor_id: UUID
    started_at: datetime
    ended_at: Optional[datetime]
    credits_used: float

    model_config = {"from_attributes": True}


# ── RAG ───────────────────────────────────────────────────────────────────────

class ContextChunk(BaseModel):
    """A chunk of retrieved context with source document provenance.

    Carries the chunk text along with metadata identifying which document
    it came from, enabling the LLM to cite sources inline.
    """

    text: str
    source_document: str
    source_document_id: str
    source_page: str | None = None
    trace_id: str | None = None
    score: float | None = None


# ── Message ───────────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    audio_path: Optional[str]
    sources_json: Optional[str] = None
    timestamp: datetime

    model_config = {"from_attributes": True}


# ── Chunks ────────────────────────────────────────────────────────────────────

class ChunkDetail(BaseModel):
    """A single chunk from a document stored in Qdrant."""

    chunk_index: int
    text: str
    score: float | None = None
    page_number: str | None = None


class DocumentChunksResponse(BaseModel):
    """Paginated chunks for a specific document."""

    document_id: str
    document_name: str
    total_chunks: int
    chunks: list[ChunkDetail]


# ── Indexing Status ───────────────────────────────────────────────────────────

class CollectionStatus(BaseModel):
    """Indexing status for a single professor collection."""

    professor_id: str
    professor_name: str
    collection: str
    total_documents: int
    documents_by_status: dict[str, int]
    total_chunks: int
    qdrant_points: int
    last_indexed_at: str | None = None
    last_error: str | None = None


class IndexingStatusResponse(BaseModel):
    """Aggregated indexing status across all collections."""

    collections: list[CollectionStatus]
    summary: dict[str, int]


# ── Sources ───────────────────────────────────────────────────────────────────

class MessageSource(BaseModel):
    """Source document citation for a single message."""

    document_id: str
    document_name: str
    relevance_score: float | None = None
    snippet: str
    page_number: str | None = None


class MessageSourcesResponse(BaseModel):
    """Sources used to generate a specific message."""

    sources: list[MessageSource]
