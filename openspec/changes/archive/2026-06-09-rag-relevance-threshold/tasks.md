# Tasks: RAG Relevance Threshold

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~210 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | All phases combined | Single PR | ~210 lines, well under 400-line budget, no split needed |

## Phase 1: Config Foundation

- [x] 1.1 Add `rag_min_relevance_score: float` (required, no default) to `core/config.py` Settings class
- [x] 1.2 Set `RAG_MIN_RELEVANCE_SCORE=0.75` in `.env.example` for deploy documentation

## Phase 2: RAG Score Filter

- [x] 2.1 RED: Write `tests/test_rag.py` — test filter includes qualifying chunks, excludes low-scoring chunks, returns `[]` on empty
- [x] 2.2 GREEN: Add score filter in `services/rag.py` — filter `nodes` by `node.score >= settings.rag_min_relevance_score` before extracting content

## Phase 3: LLM Empty-Context Handling

- [x] 3.1 RED: Write `tests/test_llm.py` — test empty context returns graceful message, non-empty context calls Ollama normally
- [x] 3.2 GREEN: Add early return in `services/llm.py` — if `context_chunks` is empty, return graceful message without calling Ollama

## Phase 4: Professor Notification

- [x] 4.1 Add `ThresholdNotification` table in `models/db.py` (professor_id, query, created_at) with SQLAlchemy model
- [x] 4.2 RED: Write notification integration test in `tests/test_sessions.py` — scope passes + threshold fails → log warning + DB event
- [x] 4.3 GREEN: Add notification logic in `routers/sessions.py` — after scope check, if `context_chunks` is empty → fire-and-forget: `logging.warning` + `db.add(ThresholdNotification(...))`

## Phase 5: Test Infrastructure

- [x] 5.1 Add `RAG_MIN_RELEVANCE_SCORE=0.0` to `tests/conftest.py` env var defaults
- [x] 5.2 Run full test suite (`conda run -n aiedu python -m pytest services/backend/tests -v`) and fix any regressions
