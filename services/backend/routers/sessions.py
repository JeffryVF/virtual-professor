import json
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db
from models.db import Message, MessageRole, Professor, Student, ThresholdNotification
from models.db import Session as DBSession
from models.schemas import (
    ContextChunk,
    MessageResponse,
    MessageSource,
    MessageSourcesResponse,
    SessionCreate,
    SessionResponse,
    SpeakRequest,
    StudentCreate,
    StudentResponse,
)
from services import langfuse as langfuse_helpers
from services import llm, memory, rag, tts


log = logging.getLogger(__name__)

router = APIRouter()


def _truncate_text_for_tts(total_text: str) -> str:
    """Apply the total-length guard before sending text to TTS.

    This replaces the old ``_prepare_speech_text`` behaviour.  The full
    *total_text* is still persisted to DB and shown in the UI — only the
    copy that goes to the (expensive) TTS engine gets trimmed when it
    exceeds ``tts_max_total_chars``.
    """
    limit = settings.tts_max_total_chars
    if len(total_text) <= limit:
        return total_text
    # Chop at the last sentence boundary inside the limit
    truncated = total_text[:limit].rstrip()
    for sep in (". ", "? ", "! "):
        pos = truncated.rfind(sep)
        if pos > 0:
            return truncated[: pos + 1]
    word = truncated.rfind(" ")
    return truncated[:word] if word > 0 else truncated


# ── Students ──────────────────────────────────────────────────────────────────

@router.post("/students", response_model=StudentResponse, status_code=201)
async def create_student(data: StudentCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Student).where(Student.email == data.email))
    student = existing.scalar_one_or_none()
    if student:
        return student

    student = Student(**data.model_dump())
    db.add(student)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.execute(select(Student).where(Student.email == data.email))
        student = existing.scalar_one()
        return student
    await db.refresh(student)
    return student


# ── Sessions ──────────────────────────────────────────────────────────────────

@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(data: SessionCreate, db: AsyncSession = Depends(get_db)):
    prof = await db.execute(select(Professor).where(Professor.id == data.professor_id))
    if not prof.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Professor not found")

    student = await db.execute(select(Student).where(Student.id == data.student_id))
    if not student.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Student not found")

    session = DBSession(student_id=data.student_id, professor_id=data.professor_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.post("/{session_id}/speak")
async def speak(
    session_id: UUID,
    payload: SpeakRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        session_result = await db.execute(select(DBSession).where(DBSession.id == session_id))
        session_obj = session_result.scalar_one_or_none()
        if not session_obj or session_obj.ended_at:
            raise HTTPException(status_code=404, detail="Session not found or already ended")

        prof_result = await db.execute(select(Professor).where(Professor.id == session_obj.professor_id))
        professor = prof_result.scalar_one()
        student_result = await db.execute(select(Student).where(Student.id == session_obj.student_id))
        student = student_result.scalar_one()

        trace = await langfuse_helpers.create_trace(
            "speak",
            metadata={
                "professor_id": str(professor.id),
                "professor_name": professor.name,
                "session_id": str(session_obj.id),
                "student_id": str(student.id),
            },
        )

        try:
            # 1. Transcript arrives from the browser (Web Speech API) or typed text
            transcript = (payload.text or "").strip()
            log.info("STT input (browser): %r (empty=%s)", transcript[:100], not transcript)

            # 2. Load conversation history from Redis
            history = await memory.get_history(str(session_id))

            # Professor's target language: use it for fallback responses and
            # to constrain the LLM + TTS voice. 'both' delegates per-message.
            response_lang = tts.resolve_language(professor.language, transcript)

            # 3. Scope check — graceful fallback: default to in-scope on failure
            context_chunks: list = []
            low_relevance = False
            if not transcript.strip():
                if response_lang == "es":
                    response_text = (
                        f"No pude entender tu audio. Intenta nuevamente sobre {professor.topic}."
                    )
                else:
                    response_text = (
                        f"I couldn't understand the audio. Please try again about {professor.topic}."
                    )
            else:
                try:
                    in_scope = await llm.is_in_scope(transcript, professor.topic, trace=trace)
                except Exception as exc:
                    log.warning("Scope check failed, defaulting to in-scope: %s", exc)
                    in_scope = True

                if not in_scope:
                    if response_lang == "es":
                        response_text = (
                            f"Por favor realiza preguntas relacionadas con {professor.topic}. "
                            f"Solo puedo ayudarte con ese tema."
                        )
                    else:
                        response_text = (
                            f"Please ask questions related to {professor.topic}. "
                            f"I can only help with that subject."
                        )
                else:
                    # 4. RAG — graceful fallback: LLM-only with KB unavailable note
                    rag_failed = False
                    try:
                        async with langfuse_helpers.create_span(trace, "rag_retrieve") as span:
                            context_chunks = await rag.retrieve_context(
                                transcript,
                                professor.collection,
                                trace_id=getattr(trace, "id", None),
                                trace=trace,
                            )
                            if span is not None:
                                span.update(
                                    input={"query": transcript, "collection": professor.collection},
                                    output={"chunk_count": len(context_chunks)},
                                )
                    except Exception as exc:
                        log.warning("RAG retrieval failed, falling back to LLM-only: %s", exc)
                        rag_failed = True
                        context_chunks = [
                            ContextChunk(
                                text="Note: knowledge base unavailable",
                                source_document="",
                                source_document_id="",
                                score=0.0,
                            )
                        ]
                        if span is not None:
                            span.update(level="ERROR", status_message=str(exc))

                    # Fire-and-forget notification when scope passes but threshold filters all chunks
                    if not context_chunks and not rag_failed:
                        log.warning(
                            "RAG threshold filter eliminated all chunks for professor %s — query: %s",
                            professor.id,
                            transcript,
                        )
                        db.add(ThresholdNotification(
                            professor_id=professor.id,
                            query=transcript,
                        ))
                        await db.commit()

                        # In-scope but nothing passed the relevance floor (e.g. tiny
                        # knowledge base): re-retrieve the single best chunk with a
                        # relaxed floor so the professor still answers grounded in its
                        # real content instead of a generic "no info" dismissal.
                        relaxed = await rag.retrieve_context(
                            transcript,
                            professor.collection,
                            top_k=1,
                            min_score=0.0,
                            trace_id=getattr(trace, "id", None),
                            trace=trace,
                        )
                        if relaxed:
                            context_chunks = relaxed
                            low_relevance = True

                    # 5. LLM — graceful fallback: 503 with Spanish message
                    try:
                        response_text = await llm.generate_response(
                            system_prompt=professor.system_prompt,
                            history=history,
                            context_chunks=context_chunks,
                            query=transcript,
                            language=response_lang,
                            trace=trace,
                            low_relevance=low_relevance,
                        )
                    except Exception as exc:
                        log.warning("LLM generation failed: %s", exc)
                        raise HTTPException(
                            status_code=503,
                            detail=json.dumps({"detail": "El profesor está pensando... Intenta de nuevo.", "step": "llm"}),
                        )

            # 6. Persist messages (with source citations from RAG)
            context_sources: list[dict] = []
            if context_chunks:
                context_sources = [
                    {
                        "document_id": chunk.source_document_id,
                        "document_name": chunk.source_document,
                        "relevance_score": chunk.score,
                        "snippet": chunk.text[:200],
                        "page_number": chunk.source_page,
                    }
                    for chunk in context_chunks
                ]
            sources_json = json.dumps(context_sources) if context_sources else None

            db.add(Message(session_id=session_id, role=MessageRole.student, content=transcript))
            db.add(
                Message(
                    session_id=session_id,
                    role=MessageRole.professor,
                    content=response_text,
                    sources_json=sources_json,
                )
            )
            await db.commit()

            # 7. Update Redis memory
            await memory.append_message(str(session_id), "user", transcript)
            await memory.append_message(str(session_id), "assistant", response_text)

            # 8. TTS — Edge-TTS with graceful fallback.
            # An empty transcript gets the text-only fallback (nothing to say aloud),
            # so the browser can prompt the student again.
            if not transcript.strip():
                return {"text": response_text, "audio": None}

            speech_text = _truncate_text_for_tts(response_text)
            try:
                async with langfuse_helpers.create_span(trace, "tts_synthesize") as span:
                    audio_response = await tts.synthesize_chunked(
                        speech_text,
                        language=tts.resolve_language(professor.language, transcript),
                    )
                    if span is not None:
                        span.update(
                            input={"text_length": len(speech_text)},
                            output={"audio_bytes": len(audio_response)},
                        )
            except Exception as exc:
                log.warning("TTS synthesis failed, returning text-only: %s", exc)
                return {"text": response_text, "audio": None}

            return Response(content=audio_response, media_type="audio/mpeg")
        finally:
            if trace is not None:
                trace.end()

    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Unhandled error in speak endpoint")
        raise HTTPException(status_code=500, detail=f"Internal error: {type(exc).__name__}: {exc}")


@router.post("/{session_id}/local-avatar-connect")
async def local_avatar_connect(session_id: UUID, db: AsyncSession = Depends(get_db)):
    """Pure session validation — no external API calls, no tokens, no WebSocket URLs.

    Returns ``{status: \"ok\", session_id: \"<uuid>\"}`` if the session exists
    and has not ended.  Raises 404 otherwise.
    """
    session_result = await db.execute(select(DBSession).where(DBSession.id == session_id))
    session = session_result.scalar_one_or_none()
    if not session or session.ended_at:
        raise HTTPException(status_code=404, detail="Session not found or already ended")
    return {"status": "ok", "session_id": str(session.id)}


@router.post("/{session_id}/compress")
async def compress_session_history(session_id: UUID):
    """Compress the in-memory session history by trimming oldest messages
    until total estimated tokens fit within the configured budget."""
    removed = await memory.compress_history(str(session_id))
    return {"removed": removed, "session_id": str(session_id)}


@router.get("/{session_id}/history", response_model=list[MessageResponse])
async def get_history(session_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.timestamp)
    )
    return result.scalars().all()


@router.delete("/{session_id}", status_code=204)
async def end_session(session_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBSession).where(DBSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.ended_at = datetime.utcnow()
    await db.commit()
    await memory.clear_session(str(session_id))


@router.get("/{session_id}/messages/{message_id}/sources", response_model=MessageSourcesResponse)
async def get_message_sources(
    session_id: UUID,
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve source citations for a specific message in a session."""
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.session_id == session_id,
        )
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found in session")

    if not msg.sources_json:
        return {"sources": []}

    try:
        sources_data = json.loads(msg.sources_json)
    except (json.JSONDecodeError, TypeError):
        return {"sources": []}

    return {"sources": sources_data}
