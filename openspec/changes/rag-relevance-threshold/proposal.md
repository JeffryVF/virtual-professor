# Proposal: RAG Relevance Threshold

## Intent

RAG pipeline always returns top_k=5 chunks regardless of relevance. When no chunks are relevant, the LLM receives noise and hallucinates. This adds a minimum similarity threshold so the system stops gracefully instead of fabricating answers.

## Scope

### In Scope
- Relevance score filter in `rag.py` with configurable threshold
- Graceful empty-context response from `llm.py`
- Professor notification when scope passes but threshold fails
- Config setting in `config.py` with env override

### Out of Scope
- Reranker (CRIT-02, future Release 2)
- Citation tracking (CRIT-03, future Release 2)
- Partial/graded responses
- Per-professor threshold override (deferred)

## Capabilities

### New Capabilities
- `rag-relevance-filtering`: Filter retrieved chunks by minimum cosine similarity score; graceful empty-context response; professor notification on threshold failure.

### Modified Capabilities
- None

## Approach

1. **`core/config.py`** — Add `rag_min_relevance_score: float = 0.75`
2. **`services/rag.py`** — Filter nodes by `node.score >= settings.rag_min_relevance_score`; return `[]` if none pass
3. **`services/llm.py`** — Accept empty `context_chunks` → return `"No encontré información sobre eso en mis fuentes"`
4. **`routers/sessions.py`** — After scope check passes, if context is empty → log + notify professor (async fire-and-forget)
5. **Notification** — Log-based (`logging.warning`) + store event in DB for dashboard visibility. No email/webhook yet.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `core/config.py` | Modified | Add `rag_min_relevance_score` |
| `services/rag.py` | Modified | Score filter in `retrieve_context` |
| `services/llm.py` | Modified | Handle empty `context_chunks` |
| `routers/sessions.py` | Modified | Threshold-failure → professor notification |
| `tests/` | New | Tests for all changes (Strict TDD) |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Threshold too high (false negatives) | Medium | Default 0.75 pre-validated; fully configurable via env |
| Threshold too low (false positives persist) | Low | Start at 0.75, tune with real data |
| Notification adds latency | Low | Fire-and-forget logging + DB write, non-blocking |

## Rollback Plan

Set `RAG_MIN_RELEVANCE_SCORE=0.0` in `.env` → all chunks pass → behavior identical to pre-change. Alternatively revert the 4 modified files.

## Dependencies

- None. Independent change per CRIT-01 priority matrix.

## Success Criteria

- [ ] Query matching existing content → chunks returned with score >= 0.75
- [ ] Query with no relevant content → `"No encontré información sobre eso en mis fuentes"`
- [ ] Scope check passes + threshold fails → professor notification logged
- [ ] Threshold overridable via `.env` or `Settings` constructor
- [ ] All existing tests pass
