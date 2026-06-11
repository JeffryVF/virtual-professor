# Tasks: RAG Retrieve Scale

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 80–120 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

## Phase 1: Configuration (RED → GREEN → REFACTOR)

- [x] 1.1 RED: Write test asserting `Settings().retrieval_top_k == 40` and `Settings().reranker_top_n == 6`
- [x] 1.2 GREEN: Add `retrieval_top_k: int = 40` (env `RAG_RETRIEVAL_TOP_K`) to `core/config.py`; change `reranker_top_n: int = 5` → `int = 6`; update docstring to "chunks to keep after reranking"
- [x] 1.3 REFACTOR: Remove any stale comments referencing old `reranker_top_n` semantics

## Phase 2: RAG Pipeline Core (RED → GREEN → REFACTOR)

- [x] 2.1 RED: Write test verifying reranker receives ALL nodes (not just first `reranker_top_n`); write test that unconditional `nodes[:reranker_top_n]` truncation applies even with `reranker_type="none"`
- [x] 2.2 GREEN: Remove `TOP_K = 5`; use `settings.retrieval_top_k` in `as_retriever()`; pass all nodes to reranker (`reranker.rerank(query, nodes)`); simplify post-rerank to `nodes = [nodes[i] for i in indices]`; add `nodes = nodes[:settings.reranker_top_n]` unconditionally after reranker block
- [x] 2.3 REFACTOR: Move truncation outside `if reranker enabled` block; remove dead `top_n` variable

## Phase 3: Reranker Coupling (RED → GREEN → REFACTOR)

- [x] 3.1 RED: Write test asserting `_get_reranker()` constructs `BGELocalReranker` with `top_n=settings.retrieval_top_k`
- [x] 3.2 GREEN: Change `_get_reranker()` in `services/rag.py` to pass `top_n=settings.retrieval_top_k` instead of `settings.reranker_top_n`
- [x] 3.3 REFACTOR: Verify `BGELocalReranker.__init__` contract in `services/reranker.py` is unchanged; no other call sites affected

## Phase 4: Test Updates & Edge Cases (RED → GREEN → REFACTOR)

- [x] 4.1 RED: Update all `top_k=5` → `top_k=40` in integration test mock calls (`test_rag.py`); rewrite `test_reranker_top_n_limits_reranked_chunks` to assert post-reranker truncation (all 5 chunks reach reranker, only `reranker_top_n=2` survive)
- [x] 4.2 GREEN: Add edge case test for `retrieval_top_k < reranker_top_n` (3 retrieved, 6 kept — no IndexError, all 3 pass through)
- [x] 4.3 REFACTOR: Run full suite with `conda run -n aiedu python -m pytest services/backend/tests -v`; clean up stale assertions; remove `_reset_reranker()` calls from tests that no longer manipulate the singleton across test boundaries
