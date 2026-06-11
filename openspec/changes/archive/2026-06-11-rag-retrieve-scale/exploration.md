# Exploration: RAG Retrieve Scale

## Current State

The pipeline today:

```
Query → Retrieve top_k=5 (dense vector, Qdrant HNSW) →
  BGE Reranker on up to reranker_top_n=5 chunks
    (score threshold 0.75) →
      LLM with ALL passing chunks (no top-N truncation)
```

Current flaws:
1. **Retrieve only 5** — the reranker never sees more than 5 candidates
2. **Reranker underutilized** — a cross-encoder over 5 chunks is pointless; it shines at 30-50
3. **No top-N cutoff after reranking** — score threshold alone can still pass too many low-value chunks

## Target Pipeline

```
Query → Retrieve top_k=40 (Qdrant, HNSW) →
  BGE Reranker on all 40 →
  Keep top_n=6 →
  Score threshold filter (0.75) →
    LLM with up to 6 compact chunks
```

**Contextual Compression** was explored and deferred to a future iteration. It's not needed at this scale where chunks are 512 tokens and we only send 5-8 chunks.

## Affected Areas

- `services/backend/services/rag.py` — `TOP_K=5` → 40, reranker over all vs first N, add top-N post-rerank truncation
- `services/backend/services/reranker.py` — Remove/rework `top_n` hard cap, let it see all chunks
- `services/backend/core/config.py` — New settings: `retrieval_top_k`, `reranker_top_n` (used for post-rerank cutoff, not pre-rerank limit)
- `services/backend/tests/` — Update tests to reflect new counts

## Recommendation

Simple retune: increase `TOP_K` to 40, remove the `nodes[:top_n]` cap before the reranker, and add a `top_n` truncation step AFTER the reranker. All settings configurable via env vars.

Effort: Low (~1 session).
