# Apply Progress: langfuse-integration

## Goal
Close the Langfuse verify blockers by fixing startup wiring, reranker tracing, and failure-path behavior, then record strict-TDD evidence.

## Files Changed
- `services/backend/main.py` — added module logger for lifespan wiring
- `services/backend/routers/sessions.py` — STT failure now aborts the pipeline; RAG call passes trace context
- `services/backend/services/rag.py` — added explicit reranker tracing and error propagation
- `services/backend/tests/test_langfuse.py` — added lifespan coverage
- `services/backend/tests/test_rag.py` — added reranker tracing / failure-path coverage
- `services/backend/tests/test_sessions.py` — added STT failure-path coverage
- `services/backend/tests/test_langfuse.py` — added runtime evidence for config defaults, callback wiring, and compose services

## Cumulative Task Progress
- 14/14 tasks complete
- This batch resolved the remaining verify blockers:
  - `main.py` logger `NameError`
  - missing reranker tracing
  - non-compliant failure-path behavior
  - missing strict-TDD artifact evidence
  - runtime proof gaps for Langfuse config defaults, callback wiring, and compose services

## TDD Cycle Evidence
| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| Main lifespan logger | `services/backend/tests/test_langfuse.py` | Unit | ⚠️ stale `test.db` caused initial fixture collision; clean rerun passed | ✅ Written | ✅ Passed | ✅ Lifespan + existing helper cases | ✅ Clean |
| Reranker tracing | `services/backend/tests/test_rag.py` | Unit | ✅ targeted reranker tests passed before/after cleanup | ✅ Written | ✅ Passed | ✅ Success + error cases | ✅ Clean |
| STT failure aborts pipeline | `services/backend/tests/test_sessions.py` | Integration | ✅ session Langfuse tests passed before/after cleanup | ✅ Written | ✅ Passed | ✅ Failure path + happy path | ✅ Clean |
| Apply-progress artifact | `openspec/changes/langfuse-integration/apply-progress.md` | N/A | N/A (new artifact) | ✅ Written | ✅ Saved | ➖ Single output | ✅ Clean |
| Config defaults runtime proof | `services/backend/tests/test_langfuse.py` | Unit | ✅ existing Langfuse tests passed before edit | ✅ Written | ✅ Passed | ✅ No-env + documented defaults | ➖ None needed |
| Callback handler wiring runtime proof | `services/backend/tests/test_langfuse.py` | Integration | ✅ existing lifespan test passed before edit | ✅ Written | ✅ Passed | ✅ Handler instantiation + `add_handler(...)` | ✅ Clean |
| Compose service declaration proof | `services/backend/tests/test_langfuse.py` | Unit | ✅ existing Langfuse tests passed before edit | ✅ Written | ✅ Passed | ✅ `langfuse`, `langfuse-postgres`, `langfuse-redis` | ➖ None needed |

## Verification Notes
- Full backend suite passed: `89 passed`
- Langfuse-enabled `/speak` trace metadata and shutdown wiring are covered
- Reranker span now records query, chunk count, and ordering; failures propagate
- Added runtime evidence for Langfuse config defaults, callback-handler attachment, and docker-compose service declarations
