import logging
from datetime import datetime
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models.db import Message, MessageRole, Professor, Student, ThresholdNotification
from models.db import Session as DBSession
from models.schemas import (
    MessageResponse,
    SessionCreate,
    SessionResponse,
    StudentCreate,
    StudentResponse,
)
from services import llm, memory, rag, stt, tts
from services.liveavatar import create_session_token, start_session

log = logging.getLogger(__name__)

router = APIRouter()


# ── Students ──────────────────────────────────────────────────────────────────

@router.post("/students", response_model=StudentResponse, status_code=201)
async def create_student(data: StudentCreate, db: AsyncSession = Depends(get_db)):
    student = Student(**data.model_dump())
    db.add(student)
    await db.commit()
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
    audio: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        session_result = await db.execute(select(DBSession).where(DBSession.id == session_id))
        session = session_result.scalar_one_or_none()
        if not session or session.ended_at:
            raise HTTPException(status_code=404, detail="Session not found or already ended")

        prof_result = await db.execute(select(Professor).where(Professor.id == session.professor_id))
        professor = prof_result.scalar_one()

        # 1. STT
        audio_bytes = await audio.read()
        try:
            transcript = await stt.transcribe(audio_bytes)
        except httpx.HTTPStatusError as exc:
            log.warning("STT service error (HTTP %s): %s", exc.response.status_code, exc.response.text[:200])
            transcript = ""
        except Exception as exc:
            log.warning("STT processing error: %s", exc)
            transcript = ""

        # 2. Load conversation history from Redis
        history = await memory.get_history(str(session_id))

        # 3. Scope check + RAG + LLM
        if not transcript.strip():
            response_text = (
                f"No pude entender tu audio. Intenta nuevamente sobre {professor.topic}. / "
                f"I couldn't understand the audio. Please try again about {professor.topic}."
            )
        elif not await llm.is_in_scope(transcript, professor.topic):
            response_text = (
                f"Por favor realiza preguntas relacionadas con {professor.topic}. "
                f"Solo puedo ayudarte con ese tema. / "
                f"Please ask questions related to {professor.topic}. "
                f"I can only help with that subject."
            )
        else:
            context_chunks = await rag.retrieve_context(transcript, professor.collection)

            # Fire-and-forget notification when scope passes but threshold filters all chunks
            if not context_chunks:
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

            response_text = await llm.generate_response(
                system_prompt=professor.system_prompt,
                history=history,
                context_chunks=context_chunks,
                query=transcript,
            )

        # 4. TTS
        try:
            audio_response = await tts.synthesize(response_text)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Text-to-speech service error on {exc.request.url}: {exc.response.text}",
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Text-to-speech processing failed: {type(exc).__name__}: {exc!r}")

        # 5. Persist messages
        db.add(Message(session_id=session_id, role=MessageRole.student, content=transcript))
        db.add(Message(session_id=session_id, role=MessageRole.professor, content=response_text))
        await db.commit()

        # 6. Update Redis memory
        await memory.append_message(str(session_id), "user", transcript)
        await memory.append_message(str(session_id), "assistant", response_text)

        return Response(content=audio_response, media_type="audio/wav")

    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Unhandled error in speak endpoint")
        raise HTTPException(status_code=500, detail=f"Internal error: {type(exc).__name__}: {exc}")


@router.post("/{session_id}/liveavatar-connect")
async def liveavatar_connect(session_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        session_result = await db.execute(select(DBSession).where(DBSession.id == session_id))
        session = session_result.scalar_one_or_none()
        if not session or session.ended_at:
            raise HTTPException(status_code=404, detail="Session not found or already ended")

        prof_result = await db.execute(select(Professor).where(Professor.id == session.professor_id))
        professor = prof_result.scalar_one()

        token_data = await create_session_token(professor.avatar_id)
        session_data = await start_session(token_data["session_token"])

        return {
            "livekit_url": session_data["livekit_url"],
            "livekit_client_token": session_data["livekit_client_token"],
            "ws_url": session_data["ws_url"],
            "liveavatar_session_id": session_data["session_id"],
        }
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        error_text = exc.response.text.lower()
        if exc.response.status_code == 403 and "4032" in error_text and "session concurrency limit reached" in error_text:
            raise HTTPException(
                status_code=503,
                detail="LiveAvatar is at capacity right now. Try again in a moment or continue in audio-only mode.",
            )
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"LiveAvatar API error on {exc.request.url}: {exc.response.text}",
        )
    except Exception as exc:
        log.exception("Unhandled error in liveavatar-connect")
        raise HTTPException(status_code=500, detail=f"Internal error: {type(exc).__name__}: {exc}")


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
