## Exploration: CRIT-02 — RAG Reranker

### Current State

The RAG pipeline after CRIT-01 (relevance threshold) works as follows:

1. **Retrieval** (`services/backend/services/rag.py`):
   - Connects to Qdrant via `AsyncQdrantClient`
   - Creates `OllamaEmbedding` with `nomic-embed-text` (768-dim, cosine distance)
   - Builds `VectorStoreIndex.from_vector_store()` 
   - Retrieves `top_k=5` nodes via dense vector cosine similarity — **this is the only ranking signal**
   - Filters by `RAG_MIN_RELEVANCE_SCORE` (CRIT-01)
   - Returns qualifying node content strings

2. **Ingestion** (`services/backend/services/ingestion.py`):
   - Creates Qdrant collections with `VectorParams(size=768, distance=Distance.COSINE)` — dense vectors only
   - `CHUNK_SIZE=512`, `CHUNK_OVERLAP=50`
   - `EMBED_DIM=768` (nomic-embed-text)

3. **LLM** (`services/backend/services/llm.py`):
   - Empty context → graceful "no info" message (CRIT-01)
   - Otherwise builds prompt with context and calls Ollama

**Key insight**: The pipeline has zero re-ranking. The top-1 chunk is whatever had the highest cosine similarity to the query embedding, which often is NOT the most useful chunk for the LLM.

### Affected Areas

- `services/backend/services/rag.py` — core retrieval function `retrieve_context()` needs reranker integration
- `services/backend/requirements.txt` — new dependencies for the chosen approach
- `services/backend/Dockerfile` — system deps if torch/sentence-transformers are added (currently python:3.11-slim)
- `services/backend/tests/test_rag.py` — new tests for reranker behavior
- `services/backend/core/config.py` — optional: env vars for reranker model name, device, etc.

### Infrastructure Details

| Component | Current Version | Notes |
|-----------|----------------|-------|
| qdrant-client | 1.18.0 | Supports sparse vectors and hybrid search since 1.7+ |
| Qdrant Docker | `latest` (no pin) | Supports BM25, SPLADE++, RRF fusion |
| llama-index-core | 0.14.22 | Has `SentenceTransformerRerank` in core.postprocessor |
| torch | NOT installed | Would be pulled by sentence-transformers |
| sentence-transformers | NOT installed | Needed for cross-encoder models |

### Approaches

#### 1. ✅ BGE Reranker via SentenceTransformerRerank (RECOMMENDED)

Add a `SentenceTransformerRerank` node postprocessor using `BAAI/bge-reranker-v2-m3` — a multilingual cross-encoder (0.6B params) that scores query-passage pairs directly.

**Integration**: ~10-15 lines added to `retrieve_context()` in `rag.py`:

```python
from llama_index.core.postprocessor import SentenceTransformerRerank

reranker = SentenceTransformerRerank(
    model="BAAI/bge-reranker-v2-m3",
    top_n=top_k,
    device="cpu",
)
nodes = await retriever.aretrieve(query)
reranked = reranker.postprocess_nodes(nodes, query_str=query)
filtered = filter_nodes_by_score(reranked, settings.rag_min_relevance_score)
```

- **Pros**:
  - True cross-encoder reranking (direct relevance scoring, not just embedding similarity)
  - Multilingual (supports Spanish — critical for this project)
  - Clean LlamaIndex integration via postprocessor pattern
  - No infra changes (no Docker, no new services)
  - Model open source (Apache 2.0), no API keys
  - CPU inference feasible for top_k=5

- **Cons**:
  - Adds ~500ms-1.5s latency per query on CPU (benchmark needed with real data)
  - torch + sentence-transformers add ~1-2GB to Docker image
  - ~560MB model download on first run (~2.2GB RAM at inference)
  - Need to ensure Docker container has enough memory

- **Dependencies**:
  - `llama-index-postprocessor-sbert-rerank>=0.5.0`
  - `sentence-transformers>=3.0.0` (pulls torch)
  - Consider `--extra-index-url https://download.pytorch.org/whl/cpu` for CPU-only smaller install

- **Effort**: Low (~1-2 hours implementation, plus testing)

#### 2. Qdrant Hybrid Search (Dense + Sparse)

Use Qdrant's built-in hybrid search with dense vectors + BM25 sparse vectors, combined via Reciprocal Rank Fusion (RRF).

- **Pros**:
  - No extra Python ML dependencies
  - Improved recall through keyword matching (BM25)
  - Leverages existing Qdrant investment
  - No new model to download or serve

- **Cons**:
  - **Not a reranker** — changes the initial retrieval, doesn't re-score dense results
  - Requires re-indexing all existing collections to add sparse vectors
  - Ingestion pipeline changes needed (`ingestion.py`)
  - BM25 doesn't understand semantics beyond keyword overlap
  - Won't give the MRR improvement expected from a cross-encoder reranker
  - Qdrant `latest` Docker image needs pinning to ensure sparse vector support

- **Effort**: Medium (~4-6 hours for re-indexing + retrieval changes)

#### 3. External Reranker API (Cohere)

Use Cohere's hosted rerank API endpoint.

- **Pros**:
  - Zero local compute overhead
  - State-of-the-art accuracy
  - Simple API integration

- **Cons**:
  - Requires API key and internet access
  - Recurring cost (~$0.001 per rerank call)
  - Adds ~100-200ms network latency
  - External dependency for a core pipeline feature
  - No offline/development fallback
  - Not aligned with project's local-first architecture

- **Effort**: Low (~1 hour)

### Recommendation

**Option 1 — BGE Reranker via SentenceTransformerRerank**.

Rationale:
1. It's a true cross-encoder reranker, which directly addresses the CRIT-02 goal of improving chunk ordering beyond cosine similarity
2. Integrates cleanly with the existing LlamaIndex pipeline (node postprocessor pattern)
3. BGE-reranker-v2-m3 supports multilingual, crucial for Spanish queries
4. No infrastructure changes — everything runs in the existing backend container
5. The dependency weight (torch + sentence-transformers) is a one-time build cost
6. CPU inference is feasible: 5 pairs × 100-300ms = 500ms-1.5s per query

**Potential enhancement**: After Option 1 is implemented, Option 2 (Qdrant hybrid) could be added as a separate change to improve initial recall, further boosting MRR.

### Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Latency** — reranker adds 0.5-1.5s on CPU | Medium | Benchmark with real queries; consider smaller model (e.g., `cross-encoder/ms-marco-MiniLM-L-2-v2`) or reduce top_k |
| **Memory** — ~2.2GB RAM for BGE model | High | Monitor container memory; consider quantized ONNX version; potentially increase Docker memory limit |
| **Docker image size** — torch adds 1-2GB | Medium | Use `pip install torch --index-url https://download.pytorch.org/whl/cpu` for smaller install |
| **Model cold start** — 560MB download on first request | Low | Pre-download model in Dockerfile or init container script |
| **No GPU** — CPU inference may be too slow for real-time chat | Medium | Profile with production data; consider ollama-based reranker if user experience degrades |
| **Spanish accuracy** — BGE is multilingual but English-trained primarily | Low | Test with Spanish queries during verification; fallback to smaller cross-encoder if needed |

### Ready for Proposal

Yes. The exploration is complete. Recommend proceeding with a proposal for **Option 1 (BGE Reranker via SentenceTransformerRerank)**, with a clear risk section on latency and memory.
