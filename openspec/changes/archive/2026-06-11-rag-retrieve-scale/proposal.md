# Proposal: RAG Retrieve Scale

## Intent

The RAG pipeline retrieves only `top_k=5` from Qdrant and the BGE cross-encoder reranker only sees those 5 chunks — underutilizing its ability to rank 30-50 candidates. The reranker should score a wider candidate pool (40), then truncate to a configurable top-N before the score threshold filter. This improves recall without increasing LLM context size.

## Scope

### In Scope
- Add `retrieval_top_k` (env `RAG_RETRIEVAL_TOP_K`, default 40) to `core/config.py`
- Replace hardcoded `TOP_K = 5` in `rag.py` with `settings.retrieval_top_k`
- Remove `nodes[:top_n]` pre-reranker cap in `rag.py` — reranker sees ALL retrieved chunks
- Add `nodes[:reranker_top_n]` **post**-reranker truncation before score threshold
- Update `_get_reranker()` to pass `retrieval_top_k` as `top_n` to `BGELocalReranker` so the cross-encoder scores all candidates
- Update tests: adjust mock expectations for `top_k=40`, verify post-rerank truncation, verify score threshold applies after truncation

### Out of Scope
- Contextual compression (explicitly deferred)
- `RerankerAdapter` interface or `BGELocalReranker` internal API changes
- Reranker model, device, or type settings
- Changes to `rag-relevance-filtering` behavior (score threshold stays unchanged)

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `rag-reranking`: 
  - `reranker_top_n` semantics change: from "chunks to rerank" → "chunks to keep after reranking"
  - Pipeline integration: reranker now processes ALL retrieved chunks, not just top N
  - New config param `retrieval_top_k` (int, default 40) via `RAG_RETRIEVAL_TOP_K` env var
  - Post-reranker top-N truncation added before score threshold filter
  - `reranker_top_n` description in config changes from "Chunks to rerank" to "Chunks to keep after reranking"

## Approach

```
Query → Retrieve top_k=40 (Qdrant HNSW) →
  BGE Reranker on all 40 →
  Keep top reranker_top_n chunks (default 6) →
  Score threshold filter (0.75) →
    LLM with up to 6 chunks
```

1. `config.py`: add `retrieval_top_k: int = 40` (env `RAG_RETRIEVAL_TOP_K`)
2. `rag.py`: delete `TOP_K = 5`, use `settings.retrieval_top_k` in `as_retriever()`, pass all nodes to reranker, apply `nodes[:settings.reranker_top_n]` after reranker, then filter by score
3. `_get_reranker()`: pass `top_n=settings.retrieval_top_k` so `SentenceTransformerRerank` scores all candidates
4. Tests: update `top_k` values in mocks (5→40), add assertions verifying post-rerank truncation

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `services/backend/core/config.py` | Modified | Add `retrieval_top_k` setting |
| `services/backend/services/rag.py` | Modified | Remove hardcoded `TOP_K`, refactor reranker pipeline |
| `services/backend/services/reranker.py` | None | No internal changes needed |
| `services/backend/tests/test_rag.py` | Modified | Update mocks, add truncation tests |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Qdrant latency at `top_k=40` vs `top_k=5` | Medium | HNSW is sub-1ms per query at this scale; benchmark in staging |
| Reranker latency with 40 chunks (8× increase) | Medium | BGE-reranker-v2-m3 handles 40 in ~200ms on CPU; if needed, GPU device via env |
| Reranker singleton's `top_n` coupled to `retrieval_top_k` | Low | Both are startup-level configs, cannot change mid-flight |

## Rollback Plan

Set `RAG_RETRIEVAL_TOP_K=5` and `RERANKER_TOP_N=5` — pipeline reverts to current behavior exactly. No code revert needed.

## Dependencies

None.

## Success Criteria

- [ ] `RAG_RETRIEVAL_TOP_K` env var controls Qdrant retrieval count, defaulting to 40
- [ ] Reranker receives all `retrieval_top_k` chunks, not just `reranker_top_n`
- [ ] `reranker_top_n` controls post-rerank truncation (not pre-rerank cap)
- [ ] Score threshold filter runs AFTER top-N truncation
- [ ] All existing tests pass with updated mock values
- [ ] New tests verify the post-reranker truncation behavior
