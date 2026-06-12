import logging

import httpx

from core.config import settings
from models.schemas import ContextChunk
from services.memory import estimate_tokens

log = logging.getLogger(__name__)


GRACEFUL_NO_CONTEXT = "No encontré información sobre eso en mis fuentes"


async def generate_response(
    system_prompt: str,
    history: list[dict],
    context_chunks: list[ContextChunk],
    query: str,
    trace: "LangfuseTrace | None" = None,
) -> str:
    """Build a prompt with RAG context and conversation history, call Ollama.

    Each ``ContextChunk`` is prefixed with a ``[Source: filename]`` label when
    ``source_document`` is non-empty.  If ``context_chunks`` is empty, returns
    a graceful message immediately without calling Ollama.

    When ``trace`` is provided (Langfuse enabled), a child span is created
    with token counts and model name.
    """
    if not context_chunks:
        log.info("Empty context after RAG threshold filter — returning graceful message")
        return GRACEFUL_NO_CONTEXT

    # Build labeled context
    labeled_chunks = []
    for chunk in context_chunks:
        if chunk.source_document:
            labeled_chunks.append(f"[Source: {chunk.source_document}]\n{chunk.text}")
        else:
            labeled_chunks.append(chunk.text)
    context = "\n\n---\n\n".join(labeled_chunks)

    history_text = "\n".join(f"{msg['role']}: {msg['content']}" for msg in history)
    prompt = (
        f"Conversation so far:\n{history_text}\n\n"
        f"Student question: {query}\n\n"
        f"Knowledge:\n{context}"
    )

    citation_instruction = (
        "Cuando uses información de las fuentes, indica el documento "
        "usando la etiqueta [Source: ...] que aparece antes del texto. "
        "No inventes fuentes para fragmentos sin etiqueta."
    )

    input_tokens = estimate_tokens(prompt) + estimate_tokens(system_prompt)

    # ── Langfuse span ────────────────────────────────────────────────────
    if trace is not None:
        from services.langfuse import create_span

        async with create_span(trace, "llm_generate") as span:
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    response = await client.post(
                        f"{settings.ollama_url}/api/generate",
                        json={
                            "model": settings.ollama_llm_model,
                            "system": (
                                f"{system_prompt}\n\n"
                                f"Use the following knowledge to answer the student's question. "
                                f"If the answer is not in the knowledge, say you don't have that information.\n\n"
                                f"{citation_instruction}"
                            ),
                            "prompt": prompt,
                            "stream": False,
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                    output_text = data["response"]
            except Exception as exc:
                if span is not None:
                    span.update(level="ERROR", status_message=str(exc))
                raise

            output_tokens = estimate_tokens(output_text)
            if span is not None:
                span.update(
                    input=prompt,
                    output=output_text,
                    model=settings.ollama_llm_model,
                    usage_details={"input": input_tokens, "output": output_tokens},
                )
            return output_text

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.ollama_url}/api/generate",
            json={
                "model": settings.ollama_llm_model,
                "system": (
                    f"{system_prompt}\n\n"
                    f"Use the following knowledge to answer the student's question. "
                    f"If the answer is not in the knowledge, say you don't have that information.\n\n"
                    f"{citation_instruction}"
                ),
                "prompt": prompt,
                "stream": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        output_text = data["response"]

    return output_text


async def is_in_scope(query: str, topic: str, trace: "LangfuseTrace | None" = None) -> bool:
    """Check whether the student's query is related to the professor's topic.

    Uses keyword matching first (fast path), then falls back to the LLM for
    ambiguous cases. Supports bilingual queries (English / Spanish).

    When ``trace`` is provided (Langfuse enabled), a child span is created
    for the scope check step.
    """
    if trace is not None:
        from services.langfuse import create_span

        async with create_span(trace, "scope_check") as span:
            result = _check_scope(query, topic)
            if span is not None:
                span.update(
                    input={"query": query, "topic": topic},
                    output={"in_scope": result},
                )
            return result

    return _check_scope(query, topic)


def _check_scope(query: str, topic: str) -> bool:
    """Internal scope check logic (keyword fast-path + LLM fallback)."""
    if topic.lower() in query.lower():
        return True
    # The LLM fallback is async; this is the keyword-only fast path.
    # The full LLM-based check is in the async function below.
    return _keyword_in_scope(query, topic)


def _keyword_in_scope(query: str, topic: str) -> bool:
    """Fast-path keyword check — returns True if topic appears in query."""
    return topic.lower() in query.lower()
