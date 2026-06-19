"""Integration tests for professor notification on RAG threshold failure,
and Langfuse trace metadata on /speak endpoint.

When scope validation passes but the RAG threshold filter eliminates all
chunks, the system should:
  1. Log a WARNING with professor ID and query text
  2. Persist a ThresholdNotification event to the database

When Langfuse is enabled, the /speak endpoint should create a root trace
with professor/session/student metadata.
"""

import io
import json
from uuid import UUID
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from core.database import AsyncSessionLocal
from models.db import Language, Message, Professor, ThresholdNotification
from models.schemas import ContextChunk


@pytest_asyncio.fixture
async def test_professor(db_session):
    """Create a professor for test scenarios."""
    prof = Professor(
        name="Test Professor",
        topic="science",
        language=Language.es,
        avatar_id="test-avatar",
        collection="test_collection",
        system_prompt="You are a science professor.",
    )
    db_session.add(prof)
    await db_session.commit()
    await db_session.refresh(prof)
    return prof


@pytest.mark.asyncio
async def test_threshold_failure_creates_notification(
    async_app, async_client, test_professor, db_session
):
    """GIVEN a query that passes scope validation
    AND the RAG threshold filter returns an empty context
    WHEN the speak endpoint processes the query
    THEN a ThresholdNotification is created in the DB
    AND a WARNING log is emitted.
    """
    # Create student via API (mounted under /sessions prefix)
    student_resp = await async_client.post(
        "/sessions/students",
        json={"name": "Test Student", "email": "student@test.com", "language": "es"},
    )
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    # Create session via API
    session_resp = await async_client.post(
        "/sessions",
        json={"professor_id": str(test_professor.id), "student_id": student_id},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    # Mock services — scope passes, RAG returns empty
    with (
        patch("routers.sessions.rag") as mock_rag,
        patch("routers.sessions.llm") as mock_llm_module,
        patch("routers.sessions.stt") as mock_stt,
        patch("routers.sessions.tts") as mock_tts,
        patch("routers.sessions.memory") as mock_memory,
    ):
        mock_stt.transcribe = AsyncMock(return_value="What is quantum physics?")
        mock_llm_module.is_in_scope = AsyncMock(return_value=True)
        mock_llm_module.generate_response = AsyncMock(
            return_value="No encontré información sobre eso en mis fuentes"
        )
        mock_rag.retrieve_context = AsyncMock(return_value=[])
        mock_tts.synthesize = AsyncMock(return_value=b"audio data")
        mock_memory.get_history = AsyncMock(return_value=[])
        mock_memory.append_message = AsyncMock()

        audio_file = io.BytesIO(b"fake audio bytes")
        response = await async_client.post(
            f"/sessions/{session_id}/speak",
            files={"audio": ("test.wav", audio_file, "audio/wav")},
        )

    # Verify response is OK
    assert response.status_code == 200

    # Check that a ThresholdNotification was created
    async with AsyncSessionLocal() as check_session:
        result = await check_session.execute(select(ThresholdNotification))
        notifications = result.scalars().all()

    assert len(notifications) == 1
    assert notifications[0].professor_id == test_professor.id
    assert notifications[0].query == "What is quantum physics?"
    assert notifications[0].created_at is not None


@pytest.mark.asyncio
async def test_scope_failure_no_notification(
    async_app, async_client, test_professor, db_session
):
    """GIVEN a query that fails professor scope validation
    WHEN the speak endpoint processes the query
    THEN no ThresholdNotification is recorded.
    """
    student_resp = await async_client.post(
        "/sessions/students",
        json={"name": "Test Student 2", "email": "student2@test.com", "language": "es"},
    )
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    session_resp = await async_client.post(
        "/sessions",
        json={"professor_id": str(test_professor.id), "student_id": student_id},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    with (
        patch("routers.sessions.llm") as mock_llm_module,
        patch("routers.sessions.stt") as mock_stt,
        patch("routers.sessions.tts") as mock_tts,
        patch("routers.sessions.memory") as mock_memory,
    ):
        mock_stt.transcribe = AsyncMock(return_value="What is the weather?")
        mock_llm_module.is_in_scope = AsyncMock(return_value=False)
        mock_tts.synthesize = AsyncMock(return_value=b"audio data")
        mock_memory.get_history = AsyncMock(return_value=[])
        mock_memory.append_message = AsyncMock()

        audio_file = io.BytesIO(b"fake audio bytes")
        response = await async_client.post(
            f"/sessions/{session_id}/speak",
            files={"audio": ("test.wav", audio_file, "audio/wav")},
        )

    assert response.status_code == 200

    # Verify no notification was created
    async with AsyncSessionLocal() as check_session:
        result = await check_session.execute(select(ThresholdNotification))
        notifications = result.scalars().all()

    assert len(notifications) == 0


# ═════════════════════════════════════════════════════════════════════════════
# Langfuse Instrumentation — Traces and Metadata
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_speak_no_langfuse_errors_when_disabled(
    async_app, async_client, test_professor, db_session
):
    """GIVEN LANGFUSE_ENABLE=false (default in conftest)
    WHEN /speak is called
    THEN no Langfuse-related errors occur and the request succeeds.
    """
    student_resp = await async_client.post(
        "/sessions/students",
        json={"name": "Langfuse Student", "email": "langfuse@test.com", "language": "es"},
    )
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    session_resp = await async_client.post(
        "/sessions",
        json={"professor_id": str(test_professor.id), "student_id": student_id},
    )
    assert session_resp.status_code == 201
    session_id = UUID(session_resp.json()["id"])

    with (
        patch("routers.sessions.rag") as mock_rag,
        patch("routers.sessions.llm") as mock_llm_module,
        patch("routers.sessions.stt") as mock_stt,
        patch("routers.sessions.tts") as mock_tts,
        patch("routers.sessions.memory") as mock_memory,
    ):
        mock_stt.transcribe = AsyncMock(return_value="What is biology?")
        mock_llm_module.is_in_scope = AsyncMock(return_value=True)
        mock_llm_module.generate_response = AsyncMock(
            return_value="Biology is the study of life."
        )
        mock_rag.retrieve_context = AsyncMock(
            return_value=[
                ContextChunk(
                    text="Life is complex.",
                    source_document="bio.pdf",
                    source_document_id="doc-1",
                    score=0.95,
                )
            ]
        )
        mock_tts.synthesize = AsyncMock(return_value=b"audio data")
        mock_memory.get_history = AsyncMock(return_value=[])
        mock_memory.append_message = AsyncMock()

        audio_file = io.BytesIO(b"fake audio bytes")
        response = await async_client.post(
            f"/sessions/{session_id}/speak",
            files={"audio": ("test.wav", audio_file, "audio/wav")},
        )

    assert response.status_code == 200

    # Verify sources were saved to the Message
    async with AsyncSessionLocal() as check_session:
        result = await check_session.execute(
            select(Message).where(Message.session_id == session_id)
        )
        messages = result.scalars().all()
        # professor message should have sources_json
        prof_msgs = [m for m in messages if m.role.value == "professor"]
        assert len(prof_msgs) >= 1
        sources = json.loads(prof_msgs[-1].sources_json) if prof_msgs[-1].sources_json else []
        assert len(sources) >= 1
        assert sources[0]["document_name"] == "bio.pdf"


@pytest.mark.asyncio
async def test_speak_persists_full_response_but_sends_shorter_text_to_tts(
    async_app, async_client, test_professor, db_session
):
    student_resp = await async_client.post(
        "/sessions/students",
        json={"name": "Long Response Student", "email": "long-response@test.com", "language": "es"},
    )
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    session_resp = await async_client.post(
        "/sessions",
        json={"professor_id": str(test_professor.id), "student_id": student_id},
    )
    assert session_resp.status_code == 201
    session_id = UUID(session_resp.json()["id"])
    long_response = " ".join(["This is a detailed explanation about science."] * 80)

    with (
        patch("routers.sessions.rag") as mock_rag,
        patch("routers.sessions.llm") as mock_llm_module,
        patch("routers.sessions.stt") as mock_stt,
        patch("routers.sessions.tts") as mock_tts,
        patch("routers.sessions.memory") as mock_memory,
    ):
        mock_stt.transcribe = AsyncMock(return_value="Explain photosynthesis")
        mock_llm_module.is_in_scope = AsyncMock(return_value=True)
        mock_llm_module.generate_response = AsyncMock(return_value=long_response)
        mock_rag.retrieve_context = AsyncMock(return_value=[])
        mock_tts.synthesize = AsyncMock(return_value=b"audio data")
        mock_memory.get_history = AsyncMock(return_value=[])
        mock_memory.append_message = AsyncMock()

        audio_file = io.BytesIO(b"fake audio bytes")
        response = await async_client.post(
            f"/sessions/{session_id}/speak",
            files={"audio": ("test.wav", audio_file, "audio/wav")},
        )

    assert response.status_code == 200
    speech_text = mock_tts.synthesize.call_args.args[0]
    assert len(speech_text) < len(long_response)
    assert speech_text.endswith("I can continue with more details if you want.")

    async with AsyncSessionLocal() as check_session:
        result = await check_session.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.timestamp)
        )
        messages = result.scalars().all()

    professor_messages = [message for message in messages if message.role.value == "professor"]
    assert professor_messages[-1].content == long_response


@pytest.mark.asyncio
async def test_speak_returns_text_only_json_when_tts_fails(
    async_app, async_client, test_professor, db_session
):
    student_resp = await async_client.post(
        "/sessions/students",
        json={"name": "TTS Failure Student", "email": "tts-failure@test.com", "language": "es"},
    )
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    session_resp = await async_client.post(
        "/sessions",
        json={"professor_id": str(test_professor.id), "student_id": student_id},
    )
    assert session_resp.status_code == 201
    session_id = UUID(session_resp.json()["id"])
    response_text = "The professor answer is still available as text."

    with (
        patch("routers.sessions.rag") as mock_rag,
        patch("routers.sessions.llm") as mock_llm_module,
        patch("routers.sessions.stt") as mock_stt,
        patch("routers.sessions.tts") as mock_tts,
        patch("routers.sessions.memory") as mock_memory,
    ):
        mock_stt.transcribe = AsyncMock(return_value="Explain gravity")
        mock_llm_module.is_in_scope = AsyncMock(return_value=True)
        mock_llm_module.generate_response = AsyncMock(return_value=response_text)
        mock_rag.retrieve_context = AsyncMock(return_value=[])
        mock_tts.synthesize = AsyncMock(side_effect=RuntimeError("tts unavailable"))
        mock_memory.get_history = AsyncMock(return_value=[])
        mock_memory.append_message = AsyncMock()

        audio_file = io.BytesIO(b"fake audio bytes")
        response = await async_client.post(
            f"/sessions/{session_id}/speak",
            files={"audio": ("test.wav", audio_file, "audio/wav")},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"text": response_text, "audio": None}


@pytest.mark.asyncio
async def test_speak_creates_trace_when_langfuse_enabled(
    async_app, async_client, test_professor, db_session
):
    """GIVEN LANGFUSE_ENABLE=true with mocked Langfuse helpers
    WHEN /speak is called
    THEN a root trace is created and metadata includes professor/session details.
    """
    mock_trace = MagicMock()
    mock_trace.id = "trace-test-1"
    mock_span = MagicMock()

    def mock_create_span_impl(trace, name, **kwargs):
        """Simulate the @asynccontextmanager for testing."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _span_cm():
            yield mock_span

        return _span_cm()

    student_resp = await async_client.post(
        "/sessions/students",
        json={"name": "Trace Student", "email": "trace@test.com", "language": "es"},
    )
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    session_resp = await async_client.post(
        "/sessions",
        json={"professor_id": str(test_professor.id), "student_id": student_id},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    with (
        patch("routers.sessions.rag") as mock_rag,
        patch("routers.sessions.llm") as mock_llm_module,
        patch("routers.sessions.stt") as mock_stt,
        patch("routers.sessions.tts") as mock_tts,
        patch("routers.sessions.memory") as mock_memory,
        patch("routers.sessions.langfuse_helpers") as mock_lf,
    ):
        mock_lf.create_trace = AsyncMock(return_value=mock_trace)
        mock_lf.create_span = mock_create_span_impl
        mock_lf.get_langfuse = MagicMock(return_value=MagicMock())

        mock_stt.transcribe = AsyncMock(return_value="Tell me about cells")
        mock_llm_module.is_in_scope = AsyncMock(return_value=True)
        mock_llm_module.generate_response = AsyncMock(
            return_value="Cells are the basic unit of life."
        )
        mock_rag.retrieve_context = AsyncMock(
            return_value=[
                ContextChunk(
                    text="Cells reproduce.",
                    source_document="bio.pdf",
                    source_document_id="doc-1",
                    score=0.92,
                )
            ]
        )
        mock_tts.synthesize = AsyncMock(return_value=b"audio data")
        mock_memory.get_history = AsyncMock(return_value=[])
        mock_memory.append_message = AsyncMock()

        audio_file = io.BytesIO(b"fake audio bytes")
        response = await async_client.post(
            f"/sessions/{session_id}/speak",
            files={"audio": ("test.wav", audio_file, "audio/wav")},
        )

    assert response.status_code == 200

    # Verify create_trace was called with the right name and metadata
    mock_lf.create_trace.assert_called_once()
    call_args = mock_lf.create_trace.call_args
    assert call_args[0][0] == "speak"  # name positional arg
    metadata = call_args[1]["metadata"]
    assert metadata["professor_id"] == str(test_professor.id)
    assert metadata["professor_name"] == test_professor.name
    assert metadata["session_id"] is not None
    assert metadata["student_id"] is not None
    mock_trace.end.assert_called_once()


@pytest.mark.asyncio
async def test_speak_aborts_pipeline_when_stt_fails_with_langfuse_enabled(
    async_app, async_client, test_professor, db_session
):
    """GIVEN STT raises during a traced speak request
    WHEN the endpoint runs
    THEN the failure is surfaced, later steps do not run, and the root trace ends.
    """
    mock_trace = MagicMock()
    mock_trace.id = "trace-fail-1"
    mock_span = MagicMock()

    def mock_create_span_impl(trace, name, **kwargs):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _span_cm():
            yield mock_span

        return _span_cm()

    student_resp = await async_client.post(
        "/sessions/students",
        json={"name": "Fail Student", "email": "fail@test.com", "language": "es"},
    )
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    session_resp = await async_client.post(
        "/sessions",
        json={"professor_id": str(test_professor.id), "student_id": student_id},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    with (
        patch("routers.sessions.rag") as mock_rag,
        patch("routers.sessions.llm") as mock_llm_module,
        patch("routers.sessions.stt") as mock_stt,
        patch("routers.sessions.tts") as mock_tts,
        patch("routers.sessions.memory") as mock_memory,
        patch("routers.sessions.langfuse_helpers") as mock_lf,
        patch("core.config.settings.langfuse_enable", True),
    ):
        mock_lf.create_trace = AsyncMock(return_value=mock_trace)
        mock_lf.create_span = mock_create_span_impl

        mock_stt.transcribe = AsyncMock(side_effect=RuntimeError("stt offline"))
        mock_llm_module.is_in_scope = AsyncMock()
        mock_llm_module.generate_response = AsyncMock()
        mock_rag.retrieve_context = AsyncMock()
        mock_tts.synthesize = AsyncMock()
        mock_memory.get_history = AsyncMock(return_value=[])
        mock_memory.append_message = AsyncMock()

        audio_file = io.BytesIO(b"fake audio bytes")
        response = await async_client.post(
            f"/sessions/{session_id}/speak",
            files={"audio": ("test.wav", audio_file, "audio/wav")},
        )

    assert response.status_code == 503
    assert "No se pudo capturar" in response.json()["detail"]
    mock_rag.retrieve_context.assert_not_called()
    mock_llm_module.generate_response.assert_not_called()
    mock_tts.synthesize.assert_not_called()
    mock_trace.end.assert_called_once()


@pytest.mark.asyncio
async def test_liveavatar_connect_rejects_non_uuid_avatar_id(async_client, test_professor):
    """GIVEN a professor with a placeholder avatar_id
    WHEN LiveAvatar connect is requested
    THEN the API returns 422 before calling the external LiveAvatar service.
    """
    student_resp = await async_client.post(
        "/sessions/students",
        json={"name": "Avatar Student", "email": "avatar@test.com", "language": "es"},
    )
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    session_resp = await async_client.post(
        "/sessions",
        json={"professor_id": str(test_professor.id), "student_id": student_id},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    response = await async_client.post(f"/sessions/{session_id}/liveavatar-connect")

    assert response.status_code == 422
    assert "valid UUID" in response.json()["detail"]


# ═════════════════════════════════════════════════════════════════════════════
# Source Citations
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_speak_saves_sources_to_message(
    async_app, async_client, test_professor, db_session
):
    """GIVEN a /speak request with valid context chunks
    WHEN the response is generated
    THEN the professor Message record SHALL have sources_json with source metadata.
    """
    student_resp = await async_client.post(
        "/sessions/students",
        json={"name": "Src Student", "email": "srctest@test.com", "language": "es"},
    )
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    session_resp = await async_client.post(
        "/sessions",
        json={"professor_id": str(test_professor.id), "student_id": student_id},
    )
    assert session_resp.status_code == 201
    session_id = UUID(session_resp.json()["id"])

    with (
        patch("routers.sessions.rag") as mock_rag,
        patch("routers.sessions.llm") as mock_llm_module,
        patch("routers.sessions.stt") as mock_stt,
        patch("routers.sessions.tts") as mock_tts,
        patch("routers.sessions.memory") as mock_memory,
    ):
        mock_stt.transcribe = AsyncMock(return_value="What is biology?")
        mock_llm_module.is_in_scope = AsyncMock(return_value=True)
        mock_llm_module.generate_response = AsyncMock(
            return_value="Biology is the study of life."
        )
        mock_rag.retrieve_context = AsyncMock(
            return_value=[
                ContextChunk(
                    text="Cells are the basic unit of life.",
                    source_document="biology_101.pdf",
                    source_document_id="doc-abc",
                    source_page="5",
                    score=0.95,
                ),
                ContextChunk(
                    text="DNA contains genetic information.",
                    source_document="biology_101.pdf",
                    source_document_id="doc-abc",
                    source_page="12",
                    score=0.87,
                ),
            ]
        )
        mock_tts.synthesize = AsyncMock(return_value=b"audio data")
        mock_memory.get_history = AsyncMock(return_value=[])
        mock_memory.append_message = AsyncMock()

        audio_file = io.BytesIO(b"fake audio bytes")
        response = await async_client.post(
            f"/sessions/{session_id}/speak",
            files={"audio": ("test.wav", audio_file, "audio/wav")},
        )

    assert response.status_code == 200

    # Verify sources were persisted in the professor Message
    async with AsyncSessionLocal() as check_session:
        result = await check_session.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.timestamp)
        )
        messages = result.scalars().all()
        assert len(messages) == 2  # student + professor

        # Professor message should have sources
        prof_msg = messages[1]
        assert prof_msg.role.value == "professor"
        assert prof_msg.sources_json is not None

        sources = json.loads(prof_msg.sources_json)
        assert len(sources) == 2
        assert sources[0]["document_id"] == "doc-abc"
        assert sources[0]["document_name"] == "biology_101.pdf"
        assert sources[0]["relevance_score"] == 0.95
        assert sources[0]["page_number"] == "5"
        assert len(sources[0]["snippet"]) <= 200

        assert sources[1]["document_id"] == "doc-abc"
        assert sources[1]["relevance_score"] == 0.87
        assert sources[1]["page_number"] == "12"


@pytest.mark.asyncio
async def test_get_message_sources(
    async_app, async_client, test_professor, db_session
):
    """GIVEN a message with sources_json
    WHEN GET /sessions/{session_id}/messages/{message_id}/sources
    THEN the sources SHALL be returned.
    """
    # Create student and session via API
    student_resp = await async_client.post(
        "/sessions/students",
        json={"name": "GetSrc Student", "email": "getsrctest@test.com", "language": "es"},
    )
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    session_resp = await async_client.post(
        "/sessions",
        json={"professor_id": str(test_professor.id), "student_id": student_id},
    )
    assert session_resp.status_code == 201
    session_id = UUID(session_resp.json()["id"])

    with (
        patch("routers.sessions.rag") as mock_rag,
        patch("routers.sessions.llm") as mock_llm_module,
        patch("routers.sessions.stt") as mock_stt,
        patch("routers.sessions.tts") as mock_tts,
        patch("routers.sessions.memory") as mock_memory,
    ):
        mock_stt.transcribe = AsyncMock(return_value="Tell me about DNA")
        mock_llm_module.is_in_scope = AsyncMock(return_value=True)
        mock_llm_module.generate_response = AsyncMock(
            return_value="DNA is the molecule of heredity."
        )
        mock_rag.retrieve_context = AsyncMock(
            return_value=[
                ContextChunk(
                    text="DNA is double-stranded.",
                    source_document="genetics.pdf",
                    source_document_id="doc-xyz",
                    source_page="3",
                    score=0.91,
                )
            ]
        )
        mock_tts.synthesize = AsyncMock(return_value=b"audio data")
        mock_memory.get_history = AsyncMock(return_value=[])
        mock_memory.append_message = AsyncMock()

        audio_file = io.BytesIO(b"fake audio bytes")
        response = await async_client.post(
            f"/sessions/{session_id}/speak",
            files={"audio": ("test.wav", audio_file, "audio/wav")},
        )

    assert response.status_code == 200

    # Fetch the professor message ID
    async with AsyncSessionLocal() as check_session:
        result = await check_session.execute(
            select(Message)
            .where(Message.session_id == session_id, Message.role == "professor")
            .order_by(Message.timestamp.desc())
            .limit(1)
        )
        prof_msg = result.scalar_one()
        message_id = prof_msg.id

    # Fetch sources via the API
    sources_resp = await async_client.get(
        f"/sessions/{session_id}/messages/{message_id}/sources",
    )
    assert sources_resp.status_code == 200
    body = sources_resp.json()
    assert len(body["sources"]) == 1
    assert body["sources"][0]["document_id"] == "doc-xyz"
    assert body["sources"][0]["document_name"] == "genetics.pdf"
    assert body["sources"][0]["relevance_score"] == 0.91
    assert body["sources"][0]["page_number"] == "3"


@pytest.mark.asyncio
async def test_get_message_sources_not_found(async_client):
    """GIVEN a non-existent message_id
    WHEN GET /sessions/{session_id}/messages/{message_id}/sources
    THEN 404 is returned.
    """
    response = await async_client.get(
        "/sessions/00000000-0000-0000-0000-000000000000/messages/00000000-0000-0000-0000-000000000000/sources",
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_message_sources_empty(async_app, async_client, test_professor, db_session):
    """GIVEN a message with no sources_json
    WHEN GET /sessions/{session_id}/messages/{message_id}/sources
    THEN empty sources list is returned.
    """


# ═════════════════════════════════════════════════════════════════════════════
# Session edge cases — 404 and invalid-state handling
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_session_non_existent_professor(async_client):
    """GIVEN a non-existent professor_id
    WHEN POST /sessions
    THEN 404 is returned.
    """
    # First create a student to get a valid student_id
    student_resp = await async_client.post(
        "/sessions/students",
        json={"name": "Orphan Student", "email": "orphan@test.com", "language": "es"},
    )
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    response = await async_client.post(
        "/sessions",
        json={
            "professor_id": "00000000-0000-0000-0000-000000000000",
            "student_id": student_id,
        },
    )
    assert response.status_code == 404
    assert "professor" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_session_non_existent_student(async_client, test_professor):
    """GIVEN a non-existent student_id
    WHEN POST /sessions
    THEN 404 is returned.
    """
    response = await async_client.post(
        "/sessions",
        json={
            "professor_id": str(test_professor.id),
            "student_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert response.status_code == 404
    assert "student" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_history_non_existent_session(async_client):
    """GIVEN a non-existent session_id
    WHEN GET /sessions/{session_id}/history
    THEN empty list is returned (the endpoint returns all messages,
    which is none for a non-existent session).
    """
    response = await async_client.get(
        "/sessions/00000000-0000-0000-0000-000000000000/history",
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_end_non_existent_session(async_client):
    """GIVEN a non-existent session_id
    WHEN DELETE /sessions/{session_id}
    THEN 404 is returned.
    """
    response = await async_client.delete(
        "/sessions/00000000-0000-0000-0000-000000000000",
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_end_already_ended_session(async_client, test_professor):
    """GIVEN an already-ended session
    WHEN DELETE /sessions/{session_id} is called again
    THEN the endpoint returns 404 (session is still findable but its
    ended_at is set; the speak endpoint checks ended_at but the delete
    endpoint does not — it always succeeds as long as the session exists).
    """
    # Create student and session
    student_resp = await async_client.post(
        "/sessions/students",
        json={
            "name": "Ended Session Student",
            "email": "ended_session@test.com",
            "language": "es",
        },
    )
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    session_resp = await async_client.post(
        "/sessions",
        json={"professor_id": str(test_professor.id), "student_id": student_id},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    # End the session once
    response1 = await async_client.delete(f"/sessions/{session_id}")
    assert response1.status_code == 204

    # End it again — session still exists, so the delete sets ended_at again
    response2 = await async_client.delete(f"/sessions/{session_id}")
    assert response2.status_code == 204
    from uuid import UUID
    from models.db import MessageRole

    # Create a session
    student_resp = await async_client.post(
        "/sessions/students",
        json={"name": "NoSrc Student", "email": "nosrc@test.com", "language": "es"},
    )
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    session_resp = await async_client.post(
        "/sessions",
        json={"professor_id": str(test_professor.id), "student_id": student_id},
    )
    assert session_resp.status_code == 201
    session_id = UUID(session_resp.json()["id"])

    # Manually add a message without sources using proper UUID
    msg = Message(
        session_id=session_id,
        role=MessageRole.professor,
        content="Test content without sources",
    )
    async with AsyncSessionLocal() as sess:
        sess.add(msg)
        await sess.commit()
        await sess.refresh(msg)
        message_id = msg.id

    response = await async_client.get(
        f"/sessions/{session_id}/messages/{message_id}/sources",
    )
    assert response.status_code == 200
    assert response.json()["sources"] == []
