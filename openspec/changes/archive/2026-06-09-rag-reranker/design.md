# Design: RAG Reranker

## Technical Approach

Insert a pluggable cross-encoder reranker between vector retrieval and score threshold filtering in `retrieve_context()`. A `RerankerAdapter` abstract interface decouples pipeline logic from model choice. `BGELocalReranker` wraps `SentenceTransformerRerank` (BAAI/bge-reranker-v2-m3, CPU-only). When `reranker_type="none"` the step is entirely skipped — zero overhead in the hot path. Reranker scores replace `node.score` so the existing `filter_nodes_by_score` works unchanged.

## Architecture Decisions

| Decision | Options | Chosen | Rationale |
|----------|---------|--------|-----------|
| Interface return type | `-> list[NodeWithScore]` vs `-> list[int]` (indices) | **`-> list[int]`** | Lean contract; caller controls re-ordering. Easier to test without constructing full nodes. |
| Reranker library | Custom cross-encoder vs `SentenceTransformerRerank` | **`SentenceTransformerRerank`** (llama-index-postprocessor-sbert-rerank) | Already LlamaIndex-native; handles loading, batching, device placement. Avoids re-inventing cross-encoder plumbing. |
| Score handling | Keep original scores vs replace with reranker scores | **Replace `node.score`** | Proposal stipulates "scores now come from the reranker." `filter_nodes_by_score` works unchanged. Threshold may need recalibration. |
| Skip mechanism | Null object vs config check | **Config check (`reranker_type == "none"`)** | Simplest, explicit, zero overhead when disabled. Null object adds indirection for no runtime benefit. |
| Error fallback | Raise vs log+continue | **Log WARNING + original order** | Spec mandates graceful fallback. Pipeline must never 500 from a reranker failure. |
| Model loading | Eager (on init) vs lazy (first call) | **Lazy (first `rerank()` call)** | Spec requires lazy-load. Keeps startup fast; cold start penalty paid only on first query with reranker enabled. |

## Data Flow

```
┌──────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────────┐    ┌──────┐
│  Query   │───→│ Vector       │───→│ Reranker     │───→│ Score Threshold  │───→│ LLM  │
│          │    │ Retrieval    │    │ (top_n only) │    │ Filter           │    │      │
└──────────┘    └──────────────┘    └─────────────┘    └──────────────────┘    └──────┘
                                        │
                                   ┌────┴────┐
                                   │  none?  │──→ skip (pass-through)
                                   └─────────┘
```

### Sequence Diagram (required by config rules)

```
User         retrieve_context()     Qdrant          Reranker       Threshold      LLM
 │                   │                │                │               │           │
 │── query ──────────┤                │                │               │           │
 │                   │── aretrieve ──→│                │               │           │
 │                   │←── nodes[] ────┤                │               │           │
 │                   │                │                │               │           │
 │                   │── rerank ──────┼───────────────→│               │           │
 │                   │  (skip if      │       cross-encoder           │           │
 │                   │   type=none)   │       scores query+chunks     │           │
 │                   │←── indices[] ──┼────────────────┤               │           │
 │                   │                │                │               │           │
 │                   │  re-order &    │                │               │           │
 │                   │  update scores │                │               │           │
 │                   │                │                │               │           │
 │                   │── filter ──────┼────────────────┼──────────────→│           │
 │                   │   (≥ threshold)│                │               │           │
 │                   │←── filtered[] ─┼────────────────┼───────────────┤           │
 │                   │                │                │               │           │
 │                   │── context ─────┼────────────────┼───────────────┼──────────→│
 │←── response ──────┤                │                │               │           │
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `services/backend/services/reranker.py` | Create | `RerankerAdapter` ABC + `BGELocalReranker` impl + lazy model loading |
| `services/backend/services/rag.py` | Modify | Insert reranker step after `aretrieve()`, before `filter_nodes_by_score()` |
| `services/backend/core/config.py` | Modify | Add `reranker_type`, `reranker_model`, `reranker_top_n`, `reranker_device` |
| `services/backend/requirements.txt` | Modify | Add `llama-index-postprocessor-sbert-rerank`, `sentence-transformers`, `torch` |
| `services/backend/Dockerfile` | Modify | CPU-only torch via `--index-url https://download.pytorch.org/whl/cpu`; pre-download model |
| `services/backend/tests/test_reranker.py` | Create | Pure unit tests for adapter contract + BGELocalReranker logic |
| `services/backend/tests/test_rag.py` | Modify | Integration tests with reranker mocked |

## Interfaces

```python
# services/reranker.py
from abc import ABC, abstractmethod
from llama_index.core.schema import NodeWithScore

class RerankerAdapter(ABC):
    @abstractmethod
    def rerank(self, query: str, chunks: list[NodeWithScore]) -> list[int]:
        """Return chunk indices in re-ranked order (descending relevance).
        
        Must return same length as chunks; each int is a valid index.
        Empty input → empty list.
        Single chunk → [0].
        """
```

## Config Changes

```python
# core/config.py — added to Settings
reranker_type: str = "none"        # "bge" enables, "none" disables
reranker_model: str = "BAAI/bge-reranker-v2-m3"
reranker_top_n: int = 5            # chunks passed to cross-encoder
reranker_device: str = "cpu"       # torch device string
```

## Pipeline Integration (key change in `rag.py`)

```python
nodes = await retriever.aretrieve(query)

if settings.reranker_type != "none":
    reranker = _get_reranker(settings)   # cached singleton or per-request
    try:
        indices = reranker.rerank(query, nodes[:settings.reranker_top_n])
        # Re-order; node.score already updated by SentenceTransformerRerank (side-effect)
        nodes = [nodes[i] for i in indices] + nodes[settings.reranker_top_n:]
    except Exception:
        log.warning("Reranker failed, falling back to original order")
        # nodes unchanged — fall through to filter

filtered = filter_nodes_by_score(nodes, settings.rag_min_relevance_score)
return [node.get_content() for node in filtered]
```

## Testing Strategy

| Layer | What | How |
|-------|------|-----|
| Unit | `RerankerAdapter` contract (empty, single, valid indices) | Subclass mock, verify contract invariants |
| Unit | `BGELocalReranker` ordering logic | Mock `SentenceTransformerRerank.postprocess_nodes` to return controlled scores; verify indices |
| Unit | Lazy model loading | Verify model is NOT loaded on `__init__`, IS loaded on first `rerank()` |
| Unit | Error fallback | Mock postprocess_nodes to raise; verify empty indices returned + warning logged |
| Integration | Pipeline with reranker enabled | Mock both retriever and reranker; verify nodes re-ordered before filter |
| Integration | Pipeline with `type=none` | Mock retriever only; verify original order + no reranker calls |

## Migration / Rollout

No migration required. `reranker_type="none"` is the default — existing deployments run identically. To enable: set env var `RERANKER_TYPE=bge` and verify threshold still works. See proposal for full rollback plan.

## Open Questions

- [ ] Does `rag_min_relevance_score` need a separate default for reranker score range (BGE outputs ~0–1 but typically ~0.998–0.999 for relevant content)? Or single threshold fine with recalibration note?
- [ ] Should `_get_reranker()` be a module-level singleton or instantiated per `retrieve_context()` call? Singleton avoids repeated model loads; per-call is simpler for testing.
