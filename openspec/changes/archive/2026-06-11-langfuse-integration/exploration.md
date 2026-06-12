## Exploration: Langfuse Observability Integration

### Current State

Today the pipeline has **zero observability** — no tracing, no monitoring, no latency tracking per call.

**Pipeline flow (no Langfuse):**

```
POST /sessions/{id}/speak
  ├── 1. STT (httpx → Whisper)          — no tracing
  ├── 2. Scope check (httpx → Ollama)   — no tracing
  │      llm.is_in_scope()
  ├── 3. RAG retrieval (Qdrant)         — no tracing
  │      rag.retrieve_context()
  │        ├── Qdrant search
  │        ├── Reranker (BGE cross-encoder)
  │        └── Score filter
  ├── 4. LLM generation (httpx → Ollama) — no tracing
  │      llm.generate_response()
  ├── 5. TTS (httpx → Kokoro)           — no tracing
  └── 6. Redis memory + DB persist      — no tracing
```

**Key findings from code inspection:**

| Aspect | Current State |
|--------|---------------|
| LLM calls | Direct httpx POST to Ollama (`/api/generate`) in `llm.py` |
| RAG | LlamaIndex `VectorStoreIndex` + `aretrieve()` in `rag.py` |
| Reranker | `BGELocalReranker` wrapper around `SentenceTransformerRerank` in `reranker.py` |
| Token counting | Already implemented in `memory.py` via `tiktoken` (`cl100k_base`) — function `_estimate_tokens()` exists but is private |
| Async | Full async pipeline — every service function is `async def` |
| Test pattern | `unittest.mock` with `AsyncMock`, `MagicMock`, `patch` on module-level names |
| Existing trace_id | `ContextChunk` schema has `trace_id: str | None = None` (line 117 of `schemas.py`) — unused, already defined |
| Dependency mgmt | `requirements.txt` (no `pyproject.toml` for deps, only for pytest config) |
| Config | `pydantic-settings` via `.env` file, `Settings` class in `core/config.py` |

**Metadata available for tracing:**

- `session_id` (UUID) — available in `routers/sessions.py`
- `professor_id`, `professor.topic`, `professor.name`, `professor.language` — from DB query in `/speak`
- `student_id` — from session DB record
- `transcript` (user query), `response_text` (LLM output)
- `context_chunks` with scores (after reranker), source documents
- Token counts — estimable with existing `tiktoken` setup in `memory.py`

---

### Affected Areas

| File | Why Affected |
|------|-------------|
| `core/config.py` | New `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST`, `LANGFUSE_ENABLE` settings |
| `services/langfuse.py` | **NEW** — Langfuse client wrapper with async-safe helpers, trace factories, singleton management |
| `services/llm.py` | Instrument `generate_response()` and `is_in_scope()` with spans; capture prompt/response/tokens/latency |
| `services/rag.py` | Option A: instrument `retrieve_context()` manually; Option B: attach `LlamaIndexCallbackHandler` globally |
| `services/reranker.py` | If not captured by LlamaIndex callback, instrument `rerank()` with span |
| `routers/sessions.py` | Create root trace per `/speak` request; orchestrate child spans; attach metadata (professor, session, student) |
| `services/memory.py` | Export `estimate_tokens()` as public utility for cost tracking |
| `main.py` | Initialize Langfuse client in `lifespan`; attach `LlamaIndexCallbackHandler` to `Settings` (if Option B) |
| `requirements.txt` | Add `langfuse>=2.50.0` |
| `Dockerfile` | No change needed (`pip install` picks up `requirements.txt`) |
| `.env.example` | New `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `LANGFUSE_ENABLE` entries |
| `tests/conftest.py` | Set `LANGFUSE_ENABLE=false` for test isolation |
| `tests/test_llm.py` | New tests: verify Langfuse spans are created/not created depending on config |
| `tests/test_sessions.py` | New tests: verify trace created on `/speak`, metadata attached, errors captured |
| `tests/test_langfuse.py` | **NEW** — tests for Langfuse client wrapper (init, disabled mode, flush) |

---

### Approaches

#### 1. ✅ Hybrid: Manual tracing on pipeline + LlamaIndex CallbackHandler (RECOMMENDED)

Combine two integration modes:

- **Manual spans** for LLM calls (`llm.py`), STT, TTS, and the pipeline orchestrator (`routers/sessions.py`) using `langfuse.trace()` and `trace.span()` directly
- **LlamaIndexCallbackHandler** for automatic tracing of `rag.retrieve_context()` — captures Qdrant search, reranker scores, node metadata

**Architecture diagram:**

```
Trace: /speak {session_id, professor_id, student_id}
  ├── Span: STT (transcribe)
  │     └── input: audio_bytes size, format
  ├── Span: Scope check (is_in_scope)
  │     ├── input: query, topic
  │     ├── output: boolean
  │     ├── tokens: prompt ~20 tokens
  │     └── latency
  ├── Span: RAG retrieval (retrieve_context)  ← LlamaIndexCallbackHandler
  │     ├── Span: Qdrant vector search
  │     ├── Span: BGE Reranker
  │     │     └── scores: [0.92, 0.87, 0.65, ...]
  │     └── Span: Score filter
  │           └── chunks_before: 5, chunks_after: 3
  ├── Span: LLM generation (generate_response)
  │     ├── input: system_prompt, query, context_chunks
  │     ├── output: response_text
  │     ├── input_tokens: ~850 (tiktoken)
  │     ├── output_tokens: ~210 (tiktoken)
  │     ├── model: ollama/llama3.2
  │     └── latency: ~2.3s
  └── Span: TTS (synthesize)
        ├── input: response_text length
        └── latency: ~1.1s
```

**Pros:**
- Covers the FULL pipeline — no blind spots
- LlamaIndex callback captures RAG internals (scores, nodes) automatically without manual instrumentation
- Async-safe — manual `trace()`/`span()` works predictably with `async def`
- Easy to mock in tests (see "Risks" section for pattern)
- Can toggle individual spans on/off per service
- `trace_id` can be propagated to `ContextChunk.trace_id` for LLM-to-RAG correlation
- Backwards-compatible — if Langfuse is disabled, the code path is a no-op

**Cons:**
- Two integration points instead of one (manual + LlamaIndex handler)
- LlamaIndex callback handler requires setting global `Settings.callback_manager` — may interact with other callbacks
- Manual span creation requires disciplined `try/finally` or context manager usage to close spans on errors
- More test surface than a single decorator approach

**Effort: Medium** (~2-3 days dev + test)

**Files to create:** `services/langfuse.py`, `tests/test_langfuse.py`

---

#### 2. Pure manual tracing (no LlamaIndex handler)

Use `langfuse.trace()` + `trace.span()` for every pipeline step. Do NOT use the LlamaIndex callback.

**Pros:**
- Single integration pattern (manual only)
- Full control over what data is captured
- No global state changes (no `Settings.callback_manager` mutation)
- Simpler mental model

**Cons:**
- RAG internals (Qdrant scores, reranker results) must be instrumented manually in `rag.py` and `reranker.py`
- More code in existing files
- Loses automatic node-level detail from LlamaIndex operations
- Need to manually extract scores from `NodeWithScore` objects

**Effort: Medium** (~2-3 days) — same lines of code, just distributed differently

---

#### 3. @observe() decorators only

Use Langfuse's `@observe()` on every async service function, relying on the decorator to auto-instrument.

**Pros:**
- Minimal code changes — just add `@observe()` decorators
- Auto-captures function args/return values
- Creates parent-child span hierarchy automatically

**Cons:**
- `@observe()` on async functions has had reliability issues in Langfuse SDK (race conditions in event flushing, context loss across `await` boundaries)
- Cannot easily group pipeline spans under a single trace — each decorator creates an independent observation
- Hard to attach custom metadata (professor data, session data) at the trace level — requires `langfuse_context.update_current_trace()` which has its own async issues
- Difficult to mock — decorator is applied at import time, patching requires mocking at module level
- No LlamaIndex callback integration out of the box
- Less control over token counting and cost estimation — would need a wrapper around the decorator

**Effort: Low** (decorator placement only) but **High risk** in async context

---

#### 4. Langfuse + OpenAI SDK wrapper (via litellm or openai-python with custom base_url)

Route Ollama calls through the OpenAI SDK (Ollama supports OpenAI-compatible API), then use Langfuse's OpenAI SDK callback.

**Pros:**
- Langfuse's OpenAI integration is mature and well-tested
- Auto-captures tokens, model, latency, prompts
- Could also use `litellm` for a unified LLM interface

**Cons:**
- Major refactor — changing how ALL LLM calls work (`generate_response`, `is_in_scope`)
- `is_in_scope` uses `temperature=0` and expects a simple "yes"/"no" response — this works with Ollama's OpenAI-compatible endpoint but changes the API surface
- Does not solve RAG/STT/TTS tracing — only LLM calls
- Highest effort for partial coverage
- Adds a dependency (openai-python) that currently doesn't exist

**Effort: High** (~4-5 days) — refactor + test + instrument

---

### Recommendation

**Approach 1 — Hybrid manual tracing + LlamaIndex CallbackHandler**.

**Rationale:**

1. **Full coverage** — every step of the pipeline gets traced: STT, scope check, RAG (with LlamaIndex internals), LLM, TTS. No blind spots.

2. **Right tool for each job**:
   - `LlamaIndexCallbackHandler` captures RAG internals (Qdrant scores, reranker results) automatically — the data is already there, just route it.
   - Manual `trace()`/`span()` for everything else gives full control over what metadata to attach, including professor/topic/session-level context that decorators can't easily express.

3. **Async-safe** — manual span creation with `contextmanager` patterns is predictable in async code. No decorator async bugs to fight.

4. **Testable** — the Langfuse client wrapper is a thin abstraction that can be disabled via config or mocked in tests. The existing `patch("routers.sessions.llm")` pattern extends naturally to `patch("services.langfuse.get_client")`.

5. **Existing trace_id field** — `ContextChunk.trace_id` is already defined in `schemas.py`. We can propagate the Langfuse trace ID to RAG chunks for correlation.

6. **Token counting** — `tiktoken` is already imported in `memory.py`. We make `estimate_tokens()` public and reuse it for cost estimation in LLM spans.

7. **No LLM SDK refactor needed** — the current `httpx` → Ollama pattern stays. We instrument around it, not replace it.

**Key design decision — Langfuse client wrapper pattern:**

```python
# services/langfuse.py
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from langfuse import Langfuse

from core.config import settings

_langfuse: Langfuse | None = None

def get_langfuse() -> Langfuse | None:
    """Return the Langfuse singleton, or None if disabled."""
    global _langfuse
    if not settings.langfuse_enable:
        return None
    if _langfuse is None:
        _langfuse = Langfuse(
            secret_key=settings.langfuse_secret_key,
            public_key=settings.langfuse_public_key,
            host=settings.langfuse_host,
            release=settings.langfuse_release,
        )
    return _langfuse


async def flush_langfuse() -> None:
    """Flush pending Langfuse events. Safe to call even if disabled."""
    lf = get_langfuse()
    if lf is not None:
        await lf.shutdown_async()


def shutdown_langfuse() -> None:
    """Synchronous flush for app shutdown (non-async)."""
    lf = get_langfuse()
    if lf is not None:
        lf.shutdown()
```

---

### Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Async compatibility** — Langfuse SDK is primarily sync; some ops block | Medium | Use `langfuse>=2.50.0` which has `shutdown_async()`. Span creation (`trace.span()`) is sync and fast — no blocking on hot path. Configure background flush with `threading` (default behavior). |
| **Mocking in tests** — existing tests patch module-level names; Langfuse client wrapper must be mock-able | Low | Test pattern: `patch("services.langfuse.get_langfuse", return_value=None)` in conftest to disable. Individual tests can re-enable with a MockLangfuse. See detailed pattern in "Test Mocking Strategy" below. |
| **LlamaIndexCallbackHandler conflict** — if other callbacks are added later, they share a `CallbackManager` | Low | The handler is added to `Settings.callback_manager` at startup via `CallbackManager([handler])`. If other callbacks are needed later, merge them into a single `CallbackManager`. |
| **Langfuse API latency** — blocking on flush or network call | Low | Langfuse SDK flushes asynchronously via background thread. `trace()`/`span()` create local objects and queue them. Configure `LANGFUSE_FLUSH_AT=10` and `LANGFUSE_FLUSH_INTERVAL=30` for non-blocking operation. |
| **API key exposure** — env var could leak in CI/logs | Low | `LANGFUSE_SECRET_KEY` is a standard secret. Already handled by `.env` pattern. Warn in proposal to never log it. |
| **Cost tracking accuracy** — tiktoken uses `cl100k_base` (GPT-4), not Llama's tokenizer | Low | `cl100k_base` is close enough for estimation. Note in design: "not exact, but consistent — good for trend monitoring, not billing." |
| **Trace/Span orphaned on exception** — if code raises before `span.end()` is called | Medium | Use `@asynccontextmanager` pattern for spans: `async with create_span("name"):` ensures `end()` is called even on exception. Or use `try/finally` blocks. |
| **Memory leak** — Langfuse cache growing unbounded | Low | Set `LANGFUSE_MAX_RETRIES=1` and configure TTL. The SDK already manages its own internal queue with configurable limits. |

#### Test Mocking Strategy

```python
# In conftest.py:
os.environ.setdefault("LANGFUSE_ENABLE", "false")

# In individual tests that need to verify Langfuse interaction:
@pytest.mark.asyncio
async def test_speak_creates_trace(mocker):
    mock_lf = MagicMock(spec=Langfuse)
    mock_trace = MagicMock()
    mock_lf.trace.return_value = mock_trace

    with patch("services.langfuse.get_langfuse", return_value=mock_lf):
        # ... test the speak endpoint
        pass

    # Assert trace was created with correct metadata
    mock_lf.trace.assert_called_once()
    assert "session_id" in mock_lf.trace.call_args[1]["input"]
```

This follows the existing project pattern (`patch("routers.sessions.llm")`) and adds no new mocking complexity.

---

### Integration Points Detail

#### Session-level trace (routers/sessions.py)

```python
# Pseudocode — rough insertion points
async def speak(session_id, audio, db):
    session = await db.get(...)
    professor = await db.get(...)

    lf = get_langfuse()
    trace = lf.trace(
        name="speak",
        session_id=str(session_id),
        user_id=str(session.student_id),
        metadata={
            "professor_id": str(professor.id),
            "professor_topic": professor.topic,
            "professor_language": professor.language.value,
            "professor_name": professor.name,
        },
    ) if lf else None

    try:
        # STT
        async with trace.span(name="stt") if trace else nullcontext():
            transcript = await stt.transcribe(audio_bytes)

        # Scope check
        async with trace.span(name="scope_check") if trace else nullcontext():
            in_scope = await llm.is_in_scope(transcript, professor.topic)

        # RAG + LLM
        if in_scope:
            async with trace.span(name="rag", ...) if trace else nullcontext():
                context_chunks = await rag.retrieve_context(...)
            async with trace.span(name="llm", ...) if trace else nullcontext():
                response_text = await llm.generate_response(...)

        # TTS
        async with trace.span(name="tts") if trace else nullcontext():
            audio_response = await tts.synthesize(response_text)

        return Response(content=audio_response, media_type="audio/wav")
    finally:
        if trace:
            trace.end()
        if lf:
            await flush_langfuse()
```

A cleaner approach: create a `LangfusePipeline` context manager class that handles the null/double-check pattern and exposes `trace` and `span()`:

```python
class LangfusePipeline:
    """Context manager wrapping a Langfuse trace.

    Usage:
        async with LangfusePipeline(name="speak", ...) as pipeline:
            async with pipeline.span("stt"):
                ...
    """

    def __init__(self, ...):
        self._lf = get_langfuse()
        self.trace = self._lf.trace(...) if self._lf else None

    @asynccontextmanager
    async def span(self, name: str, **kwargs):
        if self.trace is None:
            yield None
            return
        span = self.trace.span(name=name, **kwargs)
        try:
            yield span
        except Exception:
            span.end(status="error")
            raise
        span.end()

    async def close(self):
        if self.trace:
            self.trace.end()
        if self._lf:
            await flush_langfuse()
```

#### LLM span (services/llm.py)

```python
async def generate_response(system_prompt, history, context_chunks, query, trace=None):
    if not context_chunks:
        return GRACEFUL_NO_CONTEXT

    # If a trace is provided, create a child span
    span = trace.span(name="llm.generate_response") if trace else None

    start = time.monotonic()
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(...)
    elapsed = time.monotonic() - start

    if span:
        token_count_input = estimate_tokens(system_prompt + str(history) + str(context_chunks))
        token_count_output = estimate_tokens(response.text)
        span.end(
            output=response.text,
            usage={
                "input": token_count_input,
                "output": token_count_output,
                "unit": "TOKENS",
            },
            metadata={"latency_seconds": elapsed}
        )

    return response.text
```

**Note on span model**: The cleanest pattern is to pass an optional `span` argument down the call chain. The caller (session router) creates the span. The callee adds usage/metadata and ends the span.

---

### Env Config

```env
# ── Langfuse Observability ─────────────────────────────────────
# Set to "true" and provide a secret key to enable LLM observability
LANGFUSE_ENABLE=false
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_RELEASE=0.1.0
```

In `core/config.py`:
```python
class Settings(BaseSettings):
    # ... existing settings ...
    langfuse_enable: bool = False
    langfuse_secret_key: str = ""
    langfuse_public_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_release: str = "0.1.0"
```

The `langfuse_enable` boolean is the primary gate — all Langfuse code checks this before making any SDK calls. This makes disabling in tests trivial (`LANGFUSE_ENABLE=false`, already default).

---

### Ready for Proposal

**Yes.** Exploration is complete. All integration points identified, approaches compared, risks documented.

**What the orchestrator needs to know:**
- Change name: `langfuse-integration`
- Recommended approach: **Hybrid (Approach 1)** — manual tracing on pipeline steps + LlamaIndexCallbackHandler for RAG internals
- Artifact is at `openspec/changes/langfuse-integration/exploration.md`
- Next phase: Proposal (sdd-propose)
- The delivery strategy is a **single PR** — this is a self-contained instrumentation change with no architectural refactor. All changes are back-to-front compatible. The ~400-line budget guard: **Low risk** — this is primarily new file creation (`services/langfuse.py`), not cascading changes across the stack.
