# Proposal: RAG Reranker

## Intent

CRIT-01 filtered irrelevant chunks, but rankings still rely on cosine similarity — a shallow signal. A cross-encoder reranker scores query-chunk pairs with deeper semantic understanding, lifting useful chunks to the top before LLM consumption.

## Scope

### In Scope
- `RerankerAdapter` abstract interface + `BGELocalReranker` implementation
- Integration into `retrieve_context()` (rerank after retrieval, before threshold filter)
- Config via `config.py`: `reranker_type`, `reranker_model`, `reranker_top_n`, `reranker_device`
- Dependencies: `llama-index-postprocessor-sbert-rerank`, `sentence-transformers`, CPU-only `torch`
- Dockerfile adjustments + latency/memory benchmarks in verification

### Out of Scope
- API adapter implementations (GLM, Gemini, Cohere)
- Qdrant hybrid search — deferred as separate change
- Re-indexing existing collections

## Capabilities

### New Capabilities
- `rag-reranking`: reranks retrieved chunks using a pluggable cross-encoder model before threshold filtering and LLM consumption

### Modified Capabilities
None — `rag-relevance-filtering` defines "filter by score" generically. Scores now come from the reranker; no spec-level behavior change.

## Approach

Insert `SentenceTransformerRerank` (BAAI/bge-reranker-v2-m3) between retrieval and threshold filter, wrapped in a `RerankerAdapter` abstract interface for future adapter swaps. Pipeline: retrieve → rerank → threshold filter → LLM. Threshold values may need recalibration for reranker score range.

## Affected Areas

| Area | Impact |
|------|--------|
| `services/backend/services/rag.py` | Modified — insert reranker step |
| `services/backend/core/config.py` | Modified — reranker config fields |
| `services/backend/requirements.txt` | Modified — 3 new deps |
| `services/backend/Dockerfile` | Modified — CPU-only torch install |
| `services/backend/tests/test_rag.py` | Modified — reranker tests |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Latency +500ms-1.5s/query | Med | Benchmark; reduce top_k; lighter model fallback |
| Memory ~2.2GB for BGE model | Med | Monitor; consider quantized ONNX; increase Docker memory limit |
| Docker image size +1-2GB (torch) | Med | CPU-only `--index-url`; clean pip cache in build |
| Model cold start (560MB download) | Low | Pre-download model in Dockerfile |
| Threshold needs recalibration for reranker scores | Med | Document in deployment notes; calibrate during verification |

## Rollback Plan

1. Set `reranker_type: ""` in config — pipeline skips reranker, falls back to raw vector scores
2. Revert Dockerfile if image size problematic — keep old image tag
3. Previous model image remains deployable

## Dependencies

- `llama-index-postprocessor-sbert-rerank>=0.5.0`
- `sentence-transformers>=3.0.0`
- `torch` (CPU-only via `--index-url https://download.pytorch.org/whl/cpu`)
- Model: `BAAI/bge-reranker-v2-m3` (~560MB, downloaded on first run)

## Success Criteria

- [ ] All test scenarios pass with reranker enabled (scores from cross-encoder)
- [ ] Reranker scores feed into existing `RAG_MIN_RELEVANCE_SCORE` threshold filter
- [ ] Abstract interface supports swapping implementations without changing `rag.py` pipeline
- [ ] Docker image builds successfully with CPU-only torch
- [ ] Latency benchmark: <2s added per query (baseline before optimization)
