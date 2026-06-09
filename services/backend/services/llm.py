import logging

import httpx

from core.config import settings

log = logging.getLogger(__name__)


async def generate_response(
    system_prompt: str,
    history: list[dict],
    context_chunks: list[str],
    query: str,
) -> str:
    """Build a prompt with RAG context and conversation history, call Ollama."""
    context = "\n\n---\n\n".join(context_chunks)
    history_text = "\n".join(f"{msg['role']}: {msg['content']}" for msg in history)
    prompt = (
        f"Conversation so far:\n{history_text}\n\n"
        f"Student question: {query}\n\n"
        f"Knowledge:\n{context}"
    )

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.ollama_url}/api/generate",
            json={
                "model": settings.ollama_llm_model,
                "system": (
                    f"{system_prompt}\n\n"
                    f"Use the following knowledge to answer the student's question. "
                    f"If the answer is not in the knowledge, say you don't have that information."
                ),
                "prompt": prompt,
                "stream": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["response"]


async def is_in_scope(query: str, topic: str) -> bool:
    """Check whether the student's query is related to the professor's topic.

    Uses keyword matching first (fast path), then falls back to the LLM for
    ambiguous cases. Supports bilingual queries (English / Spanish).
    """
    if topic.lower() in query.lower():
        return True

    prompt = (
        f"The professor's topic is \"{topic}\". "
        f"The student may ask in English or Spanish.\n\n"
        f"Is the following question related to \"{topic}\"? "
        f"Answer with only \"yes\" or \"no\".\n"
        f"Question: {query}"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.post(
                f"{settings.ollama_url}/api/generate",
                json={
                    "model": settings.ollama_llm_model,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0,
                },
            )
            response.raise_for_status()
            answer = response.json()["response"].strip().lower()
            return answer.startswith("yes")
        except Exception as exc:
            log.warning("Scope check LLM call failed: %s — defaulting to in-scope", exc)
            return True
