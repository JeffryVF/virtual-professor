# Design: Langfuse Observability Integration

## Technical Approach

Langfuse Python SDK v2 initialized directly in FastAPI's lifespan — no wrapper class, Python module import is already singleton. `services/langfuse.py` exposes helpers that check `LANGFUSE_ENABLE` first and return `None` when disabled, keeping call sites clean with a single guard point. Hybrid tracing: `@asynccontextmanager` spans for pipeline orchestration and LLM calls; `LangfuseCallbackHandler` on LlamaIndex `Settings.callback_manager` for RAG internals. Token estimation via existing `tiktoken` `cl100k_base`. Self-hosted via `docker-compose.yml` with its own PostgreSQL and Redis.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| **Client lifecycle** | Module-level instance, init in lifespan, flush on shutdown | Singleton class wrapper | Python module import is already singleton; wrapper adds zero value |
| **Tracing pattern** | Manual spans + LlamaIndexCallbackHandler | All-manual or all-decorator | Best coverage — LlamaIndex auto-captures embed/query/rerank; manual spans for everything else |
| **Null check** | `get_langfuse()` returns `None` if disabled | Conditional checks everywhere | One guard point, zero cognitive overhead at call sites |
| **Span lifecycle** | `@asynccontextmanager` | try/finally blocks | Guarantees `end()` on exception, no dangling spans |
| **Token counting** | `tiktoken` `cl100k_base` | `p50k_base`, no counting | Already in project; close enough for Llama3 cost trends |

## Data Flow

```
Student → POST /sessions/{id}/speak
           │
           TRACE "langfuse_pipeline"
           ├─ SPAN stt_transcribe (latency, audio_size)
           ├─ SPAN scope_check (latency, result)
           ├─ SPAN rag_retrieve (latency, chunk_count, scores)
           │   └─ [auto] LlamaIndex: embed → query → rerank → filter
           ├─ SPAN llm_generate (latency, input_tokens, output_tokens, model)
           └─ SPAN tts_synthesize (latency, text_length)

Metadata on every trace: professor_id, professor_name, session_id, student_id
```

Spans use `async with create_span(trace, "step_name"):`. The context manager calls `span.end()` on both success and exception. When disabled, `create_span` yields `None` and the body runs as no-op.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `services/langfuse.py` | Create | `get_langfuse()`, `create_trace()`, `create_span()`, `flush_langfuse()` |
| `core/config.py` | Modify | Add `langfuse_enable`, `langfuse_secret_key`, `langfuse_public_key`, `langfuse_host`, `langfuse_release` |
| `main.py` | Modify | Init Langfuse in lifespan startup, flush on shutdown, wire `LangfuseCallbackHandler` to `Settings.callback_manager` |
| `routers/sessions.py` | Modify | Wrap `/speak` body in root trace + child spans for each pipeline step |
| `services/llm.py` | Modify | Wrap `generate_response` and `is_in_scope` with LLM spans + token counts via `memory.estimate_tokens()` |
| `services/rag.py` | Modify | Import callback handler; optionally set `trace_id` on `ContextChunk` for correlation |
| `services/memory.py` | Modify | Export `estimate_tokens()` (rename `_estimate_tokens` → public) |
| `requirements.txt` | Modify | Add `langfuse>=2.50.0` |
| `.env.example` | Modify | Add 5 Langfuse env vars with comments |
| `docker-compose.yml` | Modify | Add `langfuse`, `langfuse-postgres`, `langfuse-redis` services |
| `tests/conftest.py` | Modify | Set `LANGFUSE_ENABLE=false` |
| `tests/test_langfuse.py` | Create | Unit tests for langfuse helpers |
| `tests/test_sessions.py` | Modify | Verify `/speak` no-ops trace creation when disabled |

## Key Implementation Details

**`services/langfuse.py`** module pattern — no class, no singleton:

```python
_langfuse: Langfuse | None = None

def get_langfuse() -> Langfuse | None:
    return _langfuse

def init_langfuse():
    global _langfuse
    if settings.langfuse_enable:
        _langfuse = Langfuse(
            secret_key=settings.langfuse_secret_key,
            public_key=settings.langfuse_public_key,
            host=settings.langfuse_host,
            release=settings.langfuse_release,
        )

async def flush_langfuse():
    if _langfuse:
        await _langfuse.shutdown_async()
```

**Span helper** — async context manager guarantees cleanup:

```python
@asynccontextmanager
async def create_span(trace, name, **kwargs):
    if not trace:
        yield None
        return
    span = trace.span(name=name, **kwargs)
    try:
        yield span
    except Exception:
        span.end()
        raise
    span.end()
```

**Token counting** in LLM spans: call `memory.estimate_tokens(prompt)` and `memory.estimate_tokens(response)` before/after the Ollama call, set `usage.input` and `usage.output` on the span.

## Testing Strategy

| Layer | What | How |
|-------|------|-----|
| Unit | Langfuse helpers | `patch("langfuse.Langfuse")`, verify no-ops when disabled, verify client calls when enabled |
| Unit | LLM spans | Mock httpx + tiktoken, verify `create_span` called with token counts |
| Integration | Pipeline trace | `/speak` with `LANGFUSE_ENABLE=false` (existing mocks); verify no Langfuse errors |
| Integration | Metadata flow | Verify trace metadata carries professor/session/student IDs |

## Open Questions

None — all decisions resolved with user.
