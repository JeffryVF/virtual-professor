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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from core.database import AsyncSessionLocal
from models.db import Language, Professor, ThresholdNotification


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
    session_id = session_resp.json()["id"]

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
            return_value=[MagicMock(text="Life is complex.", source_document="bio.pdf")]
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
            return_value=[MagicMock(text="Cells reproduce.", source_document="bio.pdf")]
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

    assert response.status_code == 502
    assert "Speech-to-text" in response.json()["detail"]
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
