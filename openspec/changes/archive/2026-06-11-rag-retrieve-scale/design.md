# Design: RAG Retrieve Scale

## Technical Approach

Remove the hardcoded `TOP_K=5` bottleneck, let the BGE reranker score ALL retrieved candidates (default 40 via `rag_retrieval_top_k`), then truncate to a configurable number (`reranker_top_n`, default 6) before the score threshold. The reranker's internal `top_n` gets set to `rag_retrieval_top_k` so `SentenceTransformerRerank.postprocess_nodes` scores the full candidate pool instead of culling early.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|--------------|-----------|
| Retrieval count | `rag_retrieval_top_k` env var (default 40) | Hardcoded 40, hardcoded 50 | Configurable → no code change to tune; 40 sits in the user-suggested 30-50 range |
| Pre-reranker cap | REMOVED — reranker sees all candidates | Keep at 5, increase to 10 | User explicitly wants reranker to score the wider pool; capping before defeats the purpose |
| Top-N truncation | `nodes[:settings.reranker_top_n]` unconditionally after reranker step | Conditional (only with reranker), keep only score filter | Score filter alone can pass too many chunks; top-N gives predictable LLM context size regardless of reranker status |
| Score filter position | After post-reranker truncation | Before truncation, before reranker | Filtering after truncation catches edge cases where even top-6 are garbage-masked; before reranker would waste cross-encoder work on below-threshold items; before truncation is redundant but harmless safety net |
| Reranker `top_n` coupling | `top_n=settings.rag_retrieval_top_k` in `_get_reranker()` | Keep at `reranker_top_n`, use a separate param | `SentenceTransformerRerank.top_n` controls how many items to score, not how many to return; must match pool size to score all candidates |
| `BGELocalReranker` internal API | No changes | New `top_n` param | Internal API untouched; only call-site changes at singleton construction |
| `TOP_K` constant | REMOVED | Keep as `settings.rag_retrieval_top_k` fallback | Module-level constant is dead code once `retrieve_context` uses settings directly |

## Data Flow

```
Student query
    │
    ▼
rag.retrieve_context(query, professor_collection, top_k=settings.rag_retrieval_top_k)
    │
    ├── Qdrant dense HNSW search (top_k=40)
    │
    ├── BGE Reranker on ALL 40 nodes (was: only first 5)
    │   └── SentenceTransformerRerank.postprocess_nodes(nodes, query_str=query)
    │       └── top_n=settings.rag_retrieval_top_k (was: top_n=settings.reranker_top_n)
    │
    ├── Top-N truncation (ALWAYS): nodes = nodes[:settings.reranker_top_n]
    │   └── Applies regardless of reranker status — ensures predictable LLM context size
    │
    ├── Score threshold filter (unchanged): nodes with score >= 0.75
    │
    └── Build ContextChunk[] from NodeWithScore[]
        └── To LLM
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `services/backend/core/config.py` | Modify | Add `rag_retrieval_top_k: int = 40` (env `RAG_RETRIEVAL_TOP_K`); update `reranker_top_n` docstring from "chunks passed to cross-encoder" to "chunks to keep after reranking" |
| `services/backend/services/rag.py` | Modify | Remove `TOP_K = 5`; use `settings.rag_retrieval_top_k` in `retrieve_context()`; pass ALL nodes to reranker; add post-reranker truncation; update `_get_reranker()` to pass `top_n=settings.rag_retrieval_top_k` |
| `services/backend/tests/test_rag.py` | Modify | Update all `top_k=5` → `top_k=40` in mock calls; update `test_reranker_top_n_limits_reranked_chunks` to test post-reranker truncation instead of pre-reranker cap; add test for `rag_retrieval_top_k < reranker_top_n` edge case |

## Interfaces / Contracts

```python
# core/config.py — add
rag_retrieval_top_k: int = 40  # env: RAG_RETRIEVAL_TOP_K (RAG_MIN_RELEVANCE_SCORE is separate)

# reranker_top_n semantics change:
reranker_top_n: int = 6  # was: 5, semantics: "chunks passed to cross-encoder"
                         # now: "chunks to keep after reranking"
```

```python
# services/rag.py — core pipeline changes

# DELETE:
TOP_K = 5

# retriever now uses settings:
retriever = index.as_retriever(similarity_top_k=settings.rag_retrieval_top_k)

# reranker gets ALL nodes + top_n=rag_retrieval_top_k so SentenceTransformerRerank scores everything:
reranker = _get_reranker()
indices = reranker.rerank(query, nodes)           # was: nodes[:top_n]
nodes = [nodes[i] for i in indices]                # was: reranked_part + nodes[top_n:]

# ALWAYS truncate to reranker_top_n (whether reranker ran or not):
nodes = nodes[:settings.reranker_top_n]

# score filter stays unchanged:
filtered = filter_nodes_by_score(nodes, settings.rag_min_relevance_score)
```

```python
# _get_reranker() — top_n coupling:
# BEFORE:
BGELocalReranker(model=..., top_n=settings.reranker_top_n, ...)
# AFTER:
BGELocalReranker(model=..., top_n=settings.rag_retrieval_top_k, ...)
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `filter_nodes_by_score` | Unchanged — already tested; verify it still works on truncated lists |
| Integration | Post-reranker truncation keeps exactly `reranker_top_n` chunks | Mock reranker to return reordered 40 nodes; assert truncation to 6; assert remaining 6 are the highest-scored |
| Integration | Score threshold applies after truncation | Truncate to 6, set 3 below threshold; assert only 3 returned |
| Integration | Edge case: `rag_retrieval_top_k < reranker_top_n` | Set `rag_retrieval_top_k=3`, `reranker_top_n=6`; assert no `IndexError`; all 3 pass through |
| Integration | Reranker fallback on error | Unchanged — error still preserves original order; verify with 40 nodes |
| Integration | Reranker disabled (no-op) | With `reranker_type=none`, assert truncation to `reranker_top_n` still applies (truncation is unconditional) |

## Migration / Rollout

No migration required. The new config defaults (`RAG_RETRIEVAL_TOP_K=40`, `RERANKER_TOP_N=6`) change RAG behavior on deploy, but **rollback to exact current behavior** is a single env change:

```
RAG_RETRIEVAL_TOP_K=5  RERANKER_TOP_N=5  →  exact current pipeline
```

No code revert needed. Benchmark latency/staging before production deploy.

## Open Questions

- [x] Should post-reranker truncation apply even when reranker is disabled? **RESOLVED: Yes, always truncate.** Truncation is now outside the `if reranker enabled` block. Ensures predictable LLM context size regardless of reranker status.
