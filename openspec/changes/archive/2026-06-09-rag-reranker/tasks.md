# Tasks: RAG Reranker

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~200–240 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Phase 1: Foundation

- [x] 1.1 Add `llama-index-postprocessor-sbert-rerank`, `sentence-transformers`, `torch` to `requirements.txt`
- [x] 1.2 Add `reranker_type`, `reranker_model`, `reranker_top_n`, `reranker_device` to `core/config.py` with defaults matching spec

## Phase 2: Reranker Adapter + BGE Impl (TDD)

- [x] 2.1 [RED] Write `tests/test_reranker.py` — `RerankerAdapter` contract tests (empty, single, valid indices)
- [x] 2.2 [RED] Write `tests/test_reranker.py` — `BGELocalReranker` ordering test with mocked scores
- [x] 2.3 [RED] Write `tests/test_reranker.py` — lazy-load test (model NOT loaded on init, IS loaded on first call)
- [x] 2.4 [RED] Write `tests/test_reranker.py` — error fallback test (model/inference failure returns empty indices, logs warning)
- [x] 2.5 [GREEN] Create `services/reranker.py` with `RerankerAdapter` ABC + `BGELocalReranker` wrapping `SentenceTransformerRerank`
- [x] 2.6 Run all phase 2 tests — verify green

## Phase 3: Pipeline Integration (TDD)

- [x] 3.1 [RED] Add integration tests to `tests/test_rag.py` — reranker enabled re-orders chunks before threshold, reranker disabled skips step, error fallback preserves original order
- [x] 3.2 [GREEN] Insert reranker step in `rag.py` `retrieve_context()` between retrieval and `filter_nodes_by_score()`
- [x] 3.3 [GREEN] Add `_get_reranker()` singleton helper with lazy init and graceful `except` fallback
- [x] 3.4 Run all tests — verify green

## Phase 4: Infrastructure

- [x] 4.1 Update `Dockerfile` — CPU-only torch via `--index-url https://download.pytorch.org/whl/cpu`
- [x] 4.2 Add reranker env vars to `.env.example` with defaults and comments
