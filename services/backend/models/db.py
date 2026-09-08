import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.config import settings
from core.database import Base


class Language(enum.Enum):
    es = "es"
    en = "en"
    both = "both"


class DocumentStatus(enum.Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    error = "error"


class MessageRole(enum.Enum):
    student = "student"
    professor = "professor"


class ThresholdNotification(Base):
    __tablename__ = "threshold_notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    professor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("professors.id"))
    query: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class Professor(Base):
    __tablename__ = "professors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(String(200))
    language: Mapped[Language] = mapped_column(SAEnum(Language))
    avatar_id: Mapped[str] = mapped_column(String(100))
    collection: Mapped[str] = mapped_column(String(100), unique=True)
    system_prompt: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    documents: Mapped[list["Document"]] = relationship(back_populates="professor", cascade="all, delete-orphan")
    sessions: Mapped[list["Session"]] = relationship(back_populates="professor")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    professor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("professors.id"))
    filename: Mapped[str] = mapped_column(String(500))
    format: Mapped[str] = mapped_column(String(20))
    status: Mapped[DocumentStatus] = mapped_column(SAEnum(DocumentStatus), default=DocumentStatus.pending)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    professor: Mapped["Professor"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    language: Mapped[Language] = mapped_column(SAEnum(Language))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    sessions: Mapped[list["Session"]] = relationship(back_populates="student")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"))
    professor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("professors.id"))
    started_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    credits_used: Mapped[float] = mapped_column(Float, default=0.0)

    student: Mapped["Student"] = relationship(back_populates="sessions")
    professor: Mapped["Professor"] = relationship(back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id"))
    role: Mapped[MessageRole] = mapped_column(SAEnum(MessageRole))
    content: Mapped[str] = mapped_column(Text)
    audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sources_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    session: Mapped["Session"] = relationship(back_populates="messages")


class DocumentChunk(Base):
    """A stored RAG chunk with its embedding (pgvector)."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_document_chunks_collection", "professor_collection"),
        Index("ix_document_chunks_document", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    professor_collection: Mapped[str] = mapped_column(String(100))
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embed_dim))
    page_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    chunk_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    document: Mapped["Document"] = relationship(back_populates="chunks")
