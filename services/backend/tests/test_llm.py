"""Tests for LLM empty-context early return.

When context_chunks is empty, the LLM should return the graceful
message immediately without calling Ollama.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.llm import generate_response

GRACEFUL_MESSAGE = "No encontré información sobre eso en mis fuentes"


class TestEmptyContextEarlyReturn:
    """Tests for the early-return behavior when context is empty."""

    @pytest.mark.asyncio
    async def test_empty_context_returns_graceful_message(self):
        """GIVEN empty context_chunks list
        WHEN generate_response is called
        THEN the graceful message is returned without calling Ollama.
        """
        result = await generate_response(
            system_prompt="You are a helpful assistant",
            history=[],
            context_chunks=[],
            query="What is photosynthesis?",
        )
        assert result == GRACEFUL_MESSAGE

    @pytest.mark.asyncio
    async def test_non_empty_context_calls_ollama(self):
        """GIVEN a context list with at least one chunk
        WHEN generate_response is called
        THEN Ollama is called and the response is returned normally.
        """
        mock_response_data = {
            "response": "Photosynthesis is the process plants use to convert light into energy."
        }

        mock_response = MagicMock()
        mock_response.json.return_value = mock_response_data

        with patch("services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await generate_response(
                system_prompt="You are a helpful assistant",
                history=[{"role": "user", "content": "Hello"}],
                context_chunks=["Plants use sunlight."],
                query="What is photosynthesis?",
            )

        assert result == mock_response_data["response"]
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_context_does_not_call_ollama(self):
        """GIVEN empty context_chunks
        WHEN generate_response is called
        THEN Ollama is NOT called.
        """
        with patch("services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock()

            result = await generate_response(
                system_prompt="You are a helpful assistant",
                history=[],
                context_chunks=[],
                query="What is photosynthesis?",
            )

        assert result == GRACEFUL_MESSAGE
        mock_client.post.assert_not_called()
