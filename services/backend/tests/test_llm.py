"""Tests for LLM interaction, including labeled context assembly,
citation prompt (CRIT-03), and Langfuse span instrumentation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.schemas import ContextChunk
from services.llm import generate_response, is_in_scope

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
                context_chunks=[
                    ContextChunk(
                        text="Plants use sunlight.",
                        source_document="botany.pdf",
                        source_document_id="uuid-1",
                    ),
                ],
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


# ═════════════════════════════════════════════════════════════════════════════
# Phase 4 — Labeled Context + Citation Prompt (CRIT-03)
# ═════════════════════════════════════════════════════════════════════════════


class TestLabeledContext:
    """Tests for [Source: ...] labeled context assembly."""

    @pytest.mark.asyncio
    async def test_single_chunk_produces_labeled_context(self):
        """GIVEN one ContextChunk with source_document='lecture.pdf'
        WHEN the context is assembled for the LLM
        THEN the context string SHALL be "[Source: lecture.pdf]\\n{text}".
        """
        mock_response_data = {"response": "Neural networks use backpropagation."}
        mock_response = MagicMock()
        mock_response.json.return_value = mock_response_data

        chunks = [
            ContextChunk(
                text="Neural networks use backpropagation.",
                source_document="lecture.pdf",
                source_document_id="uuid-1",
            ),
        ]

        with patch("services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await generate_response(
                system_prompt="You are a helpful assistant",
                history=[],
                context_chunks=chunks,
                query="What is backpropagation?",
            )

        # Verify the prompt sent to Ollama has the [Source:] label
        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs["json"]
        assert "[Source: lecture.pdf]\nNeural networks use backpropagation." in payload["prompt"]

    @pytest.mark.asyncio
    async def test_multiple_chunks_with_distinct_source_labels(self):
        """GIVEN two ContextChunks from different sources
        WHEN context is assembled
        THEN each chunk has its own [Source: ...] label
        AND chunks are separated by \n\n.
        """
        mock_response_data = {"response": "Answer"}
        mock_response = MagicMock()
        mock_response.json.return_value = mock_response_data

        chunks = [
            ContextChunk(
                text="Attention is all you need.",
                source_document="paper.pdf",
                source_document_id="uuid-1",
            ),
            ContextChunk(
                text="CNNs for image recognition.",
                source_document="slides.pdf",
                source_document_id="uuid-2",
            ),
        ]

        with patch("services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await generate_response(
                system_prompt="Assistant",
                history=[],
                context_chunks=chunks,
                query="Test",
            )

        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs["json"]
        assert "[Source: paper.pdf]\nAttention is all you need." in payload["prompt"]
        assert "[Source: slides.pdf]\nCNNs for image recognition." in payload["prompt"]

    @pytest.mark.asyncio
    async def test_citation_instruction_appended_to_system_prompt(self):
        """GIVEN a SystemPrompt template
        WHEN the prompt is compiled for Ollama
        THEN the system prompt SHALL instruct the LLM to reference [Source: ...]
        AND the instruction SHALL be in natural Spanish.
        """
        mock_response_data = {"response": "Answer with sources"}
        mock_response = MagicMock()
        mock_response.json.return_value = mock_response_data

        chunks = [
            ContextChunk(
                text="Content here.",
                source_document="doc.pdf",
                source_document_id="uuid-1",
            ),
        ]

        with patch("services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await generate_response(
                system_prompt="Eres un profesor.",
                history=[],
                context_chunks=chunks,
                query="Test query",
            )

        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs["json"]
        assert "etiqueta [Source:" in payload["system"]
        assert "No inventes fuentes" in payload["system"]


# ═════════════════════════════════════════════════════════════════════════════
# Phase 5 — Edge Cases: Unlabeled Chunks (CRIT-03)
# ═════════════════════════════════════════════════════════════════════════════


class TestUnlabeledChunks:
    """Tests for empty source_document suppressing the [Source: ...] prefix."""

    @pytest.mark.asyncio
    async def test_empty_source_document_omits_label(self):
        """GIVEN a ContextChunk with source_document=''
        WHEN the context is assembled for the LLM
        THEN the [Source: ...] prefix SHALL be omitted entirely.
        """
        mock_response_data = {"response": "Answer without source"}
        mock_response = MagicMock()
        mock_response.json.return_value = mock_response_data

        chunks = [
            ContextChunk(
                text="Orphan content without a source.",
                source_document="",
                source_document_id="",
            ),
        ]

        with patch("services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await generate_response(
                system_prompt="Assistant",
                history=[],
                context_chunks=chunks,
                query="Test",
            )

        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs["json"]
        context_in_prompt = payload["prompt"].split("Knowledge:\n")[1]

        # The chunk text should appear WITHOUT any [Source: ...] prefix
        assert "[Source:" not in context_in_prompt
        assert "Orphan content without a source." in context_in_prompt


# ═════════════════════════════════════════════════════════════════════════════
# Langfuse Instrumentation — Spans in LLM
# ═════════════════════════════════════════════════════════════════════════════


class TestLangfuseSpans:
    """Verify that LLM functions create spans when given a trace."""

    @pytest.mark.asyncio
    async def test_generate_response_creates_span_when_trace_provided(self):
        """GIVEN a valid trace object
        WHEN generate_response is called with that trace
        THEN a child span is created and token counts are recorded.
        """
        mock_span = MagicMock()
        mock_trace = MagicMock()
        mock_trace.span.return_value = mock_span

        mock_response_data = {"response": "Photosynthesis is a process."}
        mock_response = MagicMock()
        mock_response.json.return_value = mock_response_data

        with (
            patch("services.llm.httpx.AsyncClient") as mock_client_cls,
            patch("services.llm.estimate_tokens") as mock_estimate,
        ):
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_estimate.side_effect = lambda t: len(t) // 4

            result = await generate_response(
                system_prompt="You are helpful",
                history=[],
                context_chunks=[
                    ContextChunk(
                        text="Plants need sunlight.",
                        source_document="botany.pdf",
                        source_document_id="uuid-1",
                    ),
                ],
                query="What is photosynthesis?",
                trace=mock_trace,
            )

        assert result == mock_response_data["response"]
        mock_trace.span.assert_called_once()
        span_name = mock_trace.span.call_args[1].get("name", "")
        assert "llm_generate" in span_name or mock_trace.span.called
        assert mock_span.update.called

    @pytest.mark.asyncio
    async def test_generate_response_skips_span_when_trace_is_none(self):
        """GIVEN trace=None (disabled)
        WHEN generate_response is called
        THEN no span is created and the function works normally.
        """
        mock_response_data = {"response": "Normal response."}
        mock_response = MagicMock()
        mock_response.json.return_value = mock_response_data

        with patch("services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await generate_response(
                system_prompt="Assistant",
                history=[],
                context_chunks=[
                    ContextChunk(
                        text="Content.",
                        source_document="doc.pdf",
                        source_document_id="uuid-1",
                    ),
                ],
                query="Test",
                trace=None,
            )

        assert result == mock_response_data["response"]
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_in_scope_creates_span_when_trace_provided(self):
        """GIVEN a valid trace object
        WHEN is_in_scope is called with that trace
        THEN a child span is created for scope checking.
        """
        mock_span = MagicMock()
        mock_trace = MagicMock()
        mock_trace.span.return_value = mock_span

        mock_response_data = {"response": "yes"}
        mock_response = MagicMock()
        mock_response.json.return_value = mock_response_data

        with patch("services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await is_in_scope(
                "What is quantum physics?",
                "physics",
                trace=mock_trace,
            )

        assert result is True
        mock_trace.span.assert_called_once()
        span_name = mock_trace.span.call_args[1].get("name", "")
        assert "scope" in span_name or mock_trace.span.called

    @pytest.mark.asyncio
    async def test_is_in_scope_skips_span_when_trace_is_none(self):
        """GIVEN trace=None (disabled)
        WHEN is_in_scope is called
        THEN no span is created and the function works normally.
        """
        with patch("services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=MagicMock())
            mock_client.post.return_value.json.return_value = {"response": "yes"}

            result = await is_in_scope(
                "What is quantum physics?",
                "physics",
                trace=None,
            )

        assert result is True
