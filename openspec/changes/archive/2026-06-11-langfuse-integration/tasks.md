# Tasks: Langfuse Observability Integration

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~350–400 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single PR (coherent change, no autonomous slices) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

## Phase 1: Foundation — Config, Dependencies, Docker

- [x] 1.1 Add `langfuse>=2.50.0` to `requirements.txt`
- [x] 1.2 Add 5 settings to `core/config.py`: `langfuse_enable` (default False), `langfuse_secret_key`, `langfuse_public_key`, `langfuse_host`, `langfuse_release`
- [x] 1.3 Add Langfuse env vars to `.env.example`
- [x] 1.4 Add `langfuse`, `langfuse-postgres`, `langfuse-redis` services to `docker-compose.yml`
- [x] 1.5 Export `estimate_tokens()` in `services/memory.py` (rename `_estimate_tokens` → public)

## Phase 2: Langfuse Client — Init and Helpers

- [x] 2.1 Create `services/langfuse.py` with `get_langfuse()`, `create_trace()`, `create_span()` — all check `LANGFUSE_ENABLE`, return None when disabled
- [x] 2.2 Modify `main.py` lifespan: init Langfuse client, set `LangfuseCallbackHandler` on `Settings.callback_manager`, flush on shutdown via `shutdown_async()`

## Phase 3: Pipeline Instrumentation — Spans in Services

- [x] 3.1 Modify `services/llm.py`: wrap `generate_response()` and `is_in_scope()` with LLM spans; use tiktoken for input/output token counts; record model name
- [x] 3.2 Modify `services/rag.py`: integrate `LangfuseCallbackHandler` for automatic RAG retrieval tracing (chunk scores, latency)
- [x] 3.3 Modify `routers/sessions.py`: wrap `/speak` handler in root trace; child spans for STT, scope check, RAG, LLM, TTS; attach professor/session/student metadata

## Phase 4: Testing

- [x] 4.1 Create `tests/test_langfuse.py`: test helpers — init, disabled mode, create_trace returns None when disabled, create_span context manager behaviour
- [x] 4.2 Add `LANGFUSE_ENABLE=false` default in `tests/conftest.py`
- [x] 4.3 Update `tests/test_llm.py`: verify LLM spans created when enabled, skipped when disabled
- [x] 4.4 Update `tests/test_sessions.py`: verify trace metadata carries professor/session IDs
