# Proposal: Langfuse Observability Integration

## Intent

Zero tracing on any pipeline call — blind debugging, no latency or cost data, no professor audit trail. Add Langfuse for full observability.

## Scope

### In Scope
- Langfuse self-hosted in `docker-compose.yml` (+ its own PostgreSQL + Redis)
- Root trace per `/speak` + child spans: STT → scope → RAG → reranker → LLM → TTS
- LLM cost via tiktoken (`cl100k_base`, already in project)
- Metadata: professor name/ID, session ID, student ID
- Init in FastAPI lifespan; flush on shutdown via `shutdown_async()`
- `services/langfuse.py` — `get_langfuse()`, `flush_langfuse()`, null-check, no singleton
- Env vars: `LANGFUSE_ENABLE`, `_SECRET_KEY`, `_PUBLIC_KEY`, `_HOST`, `_RELEASE`
- LlamaIndex `CallbackManager` + handler for RAG internals
- Populate existing `ContextChunk.trace_id` for correlation
- Disabled by default (`LANGFUSE_ENABLE=false`)
- Tests with mocked Langfuse (existing `unittest.mock`/`AsyncMock`)

### Out of Scope
Ragas/DeepEval, Langfuse scores/datasets, student dashboards, CRIT-03 citations

## Capabilities

> Pure instrumentation — no existing spec modified.

### New
- `observability-langfuse`: Full pipeline tracing, cost tracking, metadata enrichment

### Modified
None

## Approach

Langfuse Python SDK v2. Init in `main.py` lifespan. `services/langfuse.py` exposes `get_langfuse() → Langfuse | None` + `flush_langfuse()`. `/speak` wraps in root trace with metadata. Each service call gets a child span via `async with` (guarantees `end()` on exception). LlamaIndex `Settings.callback_manager` gets `LangfuseCallbackHandler`. Flush via `shutdown_async()`.

## Affected Areas

| Area | Change |
|------|--------|
| `services/langfuse.py` | **NEW** |
| `core/config.py` | **MODIFIED** — 5 env vars |
| `routers/sessions.py` | **MODIFIED** — root trace |
| `services/llm.py` | **MODIFIED** — spans + tokens |
| `services/rag.py` | **MODIFIED** — callback handler |
| `main.py` | **MODIFIED** — init/shutdown |
| `docker-compose.yml` | **MODIFIED** — Langfuse + DBs |
| `.env.example`, `requirements.txt` | **MODIFIED** — vars + dep |
| `tests/conftest.py` | **MODIFIED** — disabled default |
| `tests/test_langfuse.py` | **NEW** |
| `tests/test_sessions.py` | **MODIFIED** |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Async SDK compat | Low | `langfuse>=2.50.0` + `shutdown_async()` |
| Orphaned spans | Med | `async with` guarantees `end()` |
| Test isolation | Low | `LANGFUSE_ENABLE=false`; `patch()` |
| Token accuracy | Low | `cl100k_base` ≈ Llama; trends ok |

## Rollback Plan

Set `LANGFUSE_ENABLE=false`, remove env vars, revert `docker-compose.yml`.

## Dependencies

- `langfuse>=2.50.0`

## Success Criteria

- [ ] `/speak` produces root trace + spans visible in Langfuse UI
- [ ] LLM spans show estimated input/output tokens
- [ ] Professor/session/student metadata on every trace
- [ ] All tests pass with `LANGFUSE_ENABLE=false`
- [ ] Integration tests verify span creation when enabled
