import logging

import httpx

from core.config import settings
from models.schemas import ContextChunk
from services.memory import estimate_tokens

log = logging.getLogger(__name__)


GRACEFUL_NO_CONTEXT = "No encontré información sobre eso en mis fuentes"


def _chat_url() -> str:
    return f"{settings.zai_base_url.rstrip('/')}/chat/completions"


def _chat_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.zai_api_key}",
        "Content-Type": "application/json",
    }


def _extract_content(data: dict) -> str:
    """Pull the assistant text from a Z.AI / OpenAI-compatible response."""
    message = data["choices"][0]["message"]
    return (message.get("content") or "").strip()


async def _chat_complete(
    messages: list[dict],
    *,
    max_tokens: int | None = None,
    timeout: float = 60,
) -> str:
    """Call Z.AI chat completions with thinking disabled (voice-friendly)."""
    payload = {
        "model": settings.zai_llm_model,
        "messages": messages,
        "thinking": {"type": "disabled"},
        "max_tokens": max_tokens or settings.llm_max_tokens,
        "temperature": 0.6,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(_chat_url(), json=payload, headers=_chat_headers())
        response.raise_for_status()
        return _extract_content(response.json())


async def generate_response(
    system_prompt: str,
    history: list[dict],
    context_chunks: list[ContextChunk],
    query: str,
    trace: "LangfuseTrace | None" = None,
) -> str:
    """Build a prompt with RAG context and conversation history, call Z.AI.

    Each ``ContextChunk`` is prefixed with a ``[Source: filename]`` label when
    ``source_document`` is non-empty.  If ``context_chunks`` is empty, returns
    a graceful message immediately without calling the LLM.

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
    user_prompt = (
        f"Conversation so far:\n{history_text}\n\n"
        f"Student question: {query}\n\n"
        f"Knowledge:\n{context}"
    )

    citation_instruction = (
        "Cuando uses información de las fuentes, indica el documento "
        "usando la etiqueta [Source: ...] que aparece antes del texto. "
        "No inventes fuentes para fragmentos sin etiqueta."
    )

    conciseness_instruction = (
        "Responde de forma breve y directa, idealmente 1 a 3 frases. "
        "Tu respuesta se usará para síntesis de voz, así que debe ser "
        "concisa y natural al hablar. Si el estudiante pide más detalles, "
        "puedes ampliar, pero por defecto sé breve."
    )

    system_content = (
        f"{system_prompt}\n\n"
        f"Use the following knowledge to answer the student's question. "
        f"If the answer is not in the knowledge, say you don't have that information.\n\n"
        f"{citation_instruction}\n\n"
        f"{conciseness_instruction}"
    )
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_prompt},
    ]

    input_tokens = estimate_tokens(user_prompt) + estimate_tokens(system_content)

    # ── Langfuse span ────────────────────────────────────────────────────
    if trace is not None:
        from services.langfuse import create_span

        async with create_span(trace, "llm_generate") as span:
            try:
                output_text = await _chat_complete(messages, timeout=60)
            except Exception as exc:
                if span is not None:
                    span.update(level="ERROR", status_message=str(exc))
                raise

            output_tokens = estimate_tokens(output_text)
            if span is not None:
                span.update(
                    input=user_prompt,
                    output=output_text,
                    model=settings.zai_llm_model,
                    usage_details={"input": input_tokens, "output": output_tokens},
                )
            return output_text

    return await _chat_complete(messages, timeout=60)


# Stop words used when extracting topic keywords for the fast-path check.
_STOP_WORDS = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "en", "por", "para", "con", "sin", "sobre",
    "a", "al", "e", "y", "o", "u", "lo", "como",
    "the", "a", "an", "of", "in", "to", "for", "with", "on", "at",
    "introducción", "introduction", "intro", "i",
})

# Domain-specific keyword expansions: when a topic keyword is detected, related
# technical terms are also accepted without needing the LLM fallback.
_DOMAIN_KEYWORDS: dict[str, frozenset[str]] = {
    # Programming / Computer Science
    "programación": frozenset({
        "algoritmo", "algoritmos", "variable", "variables", "función", "funciones",
        "bucle", "bucles", "loop", "loops", "código", "codigo", "software",
        "dato", "datos", "array", "arrays", "lista", "listas", "objeto", "objetos",
        "clase", "clases", "método", "metodo", "métodos", "metodos",
        "python", "java", "javascript", "html", "css", "compilador", "intérprete",
        "debug", "depuración", "depuracion", "sintaxis", "string", "entero",
        "booleano", "condición", "condicion", "condicional", "iteración", "iteracion",
        "recursión", "recursion", "recursivo", "puntero", "punteros", "memoria",
        "archivo", "archivos", "fichero", "ficheros", "entrada", "salida",
        "parámetro", "parametro", "parámetros", "parametros", "argumento", "argumentos",
        "retorno", "return", "if", "else", "while", "for",
        "programar", "programando", "programador",
    }),
}


def _topic_keywords(topic: str) -> list[str]:
    """Extract meaningful keywords from a topic string (e.g., 'Programación' from 'Introducción a la Programación')."""
    words = topic.lower().split()
    return [w for w in words if w not in _STOP_WORDS and len(w) > 2]


def _domain_related(query_lower: str, topic_lower: str) -> bool:
    """Check if the query contains related technical terms for the topic's domain."""
    for topic_word in topic_lower.split():
        if topic_word in _DOMAIN_KEYWORDS:
            # Query may be in-scope even without exact topic keyword if it contains
            # a related technical term
            related = _DOMAIN_KEYWORDS[topic_word]
            query_words = set(query_lower.split())
            if query_words & related:
                return True
    return False


async def is_in_scope(query: str, topic: str, trace: "LangfuseTrace | None" = None) -> bool:
    """Check whether the student's query is related to the professor's topic.

    Uses keyword matching first (fast path), then falls back to the LLM for
    ambiguous cases. Supports bilingual queries (English / Spanish).

    When ``trace`` is provided (Langfuse enabled), a child span is created
    for the scope check step.
    """
    query_lower = query.lower()
    topic_lower = topic.lower()

    # Fast path 1: exact topic match
    if topic_lower in query_lower:
        return True

    # Fast path 2: individual topic keywords (e.g., "programación" from "Introducción a la Programación")
    for kw in _topic_keywords(topic):
        if kw in query_lower:
            return True

    # Fast path 3: domain-related terms (e.g., "algoritmo" when topic is programming)
    if _domain_related(query_lower, topic_lower):
        return True

    # LLM fallback for ambiguous queries
    result = await _llm_check_scope(query, topic)

    if trace is not None:
        from services.langfuse import create_span

        async with create_span(trace, "scope_check") as span:
            if span is not None:
                span.update(
                    input={"query": query, "topic": topic, "method": "llm"},
                    output={"in_scope": result},
                )

    return result


async def _llm_check_scope(query: str, topic: str) -> bool:
    """Ask the LLM whether the student's query falls within the professor's topic."""
    keywords = _topic_keywords(topic)
    topic_short = keywords[0].capitalize() if keywords else topic

    messages = [
        {
            "role": "system",
            "content": (
                "You are a classifier. Determine if the student's question is about "
                "the professor's topic. Answer YES or NO only."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Topic: {topic_short}\n"
                f"Student: {query}\n"
                f"Is this about {topic_short}? YES or NO:"
            ),
        },
    ]

    answer = (await _chat_complete(messages, max_tokens=8, timeout=30)).upper()
    log.info("Scope LLM check for %r on %r → %s", query[:80], topic, answer)
    return answer.startswith("YES")
