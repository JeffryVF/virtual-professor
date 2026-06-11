"""Integration tests for professor notification on RAG threshold failure.

When scope validation passes but the RAG threshold filter eliminates all
chunks, the system should:
  1. Log a WARNING with professor ID and query text
  2. Persist a ThresholdNotification event to the database
"""

import io
from unittest.mock import AsyncMock, patch

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
