# Design: RAG Source Citations

## Technical Approach

Three-layer enrichment: ingestion metadata → typed retrieval → citation-labeled LLM. Chunks get `source_filename` at index time (from SQL `Document.filename`), `retrieve_context()` returns typed `ContextChunk` objects preserving provenance, and `llm.py` prepends `[Source: ...]` labels before the LLM sees the context. A Spanish citation instruction in the system prompt tells the LLM to use those markers inline.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Metadata key name | `source_filename` in Qdrant payload | Plain `filename`, `doc_name` | Spec requires `source_filename`; `source_` prefix avoids collision with any LlamaIndex-internal metadata |
| ContextChunk location | `models/schemas.py` (existing) | New `services/schemas.py` | Project already uses `models/schemas.py` for all Pydantic models; no new file needed |
| Citation labeling | `llm.py` prepends `[Source: ...]\n` per chunk | Labels as a list, separate API field | Inline text is the simplest approach (Approach 1 from exploration); no API contract changes |
| Fallback for missing filename | `source_filename` → `document_id` → `""` (omit label) | Always emit label with "unknown" | Spec demands no fabricated sources; empty `source_document` suppresses the `[Source: ...]` prefix entirely |
| ContextChunk usage in router | `if not context_chunks:` still works | Type check needed | Empty list is falsy regardless of element type — no router changes needed |

## Data Flow

```
Student query
    │
    ▼
rag.retrieve_context(query)
    │
    ├── Qdrant vector search (top-k)
    ├── [CRIT-01] Score threshold filter
    ├── [CRIT-02] BGE reranker (if enabled)
    │
    ▼
Build ContextChunk[] from NodeWithScore[]
    │   source_document = metadata["source_filename"]
    │   fallback: metadata["document_id"]
    │   fallback: ""
    │
    ▼
llm.generate_response(context_chunks, ...)
    │
    ├── Empty? → graceful "no encontré" (early return)
    │
    ├── Build labeled context:
    │   "[Source: doc.pdf]\n{text}\n\n---\n\n[Source: slides.pdf]\n{text}"
    │
    ├── System prompt += citation instruction (Spanish)
    │
    ▼
Ollama LLM → Response with in-text [Source: ...] markers
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `services/backend/models/schemas.py` | Modify | Add `ContextChunk` Pydantic model with `text`, `source_document`, `source_document_id`, `source_page`, `trace_id` |
| `services/backend/services/ingestion.py` | Modify | Inject `source_filename` into each node's metadata from SQL `Document.filename` before Qdrant index |
| `services/backend/services/rag.py` | Modify | Return type `list[str]` → `list[ContextChunk]`; build from `NodeWithScore` metadata with fallback chain |
| `services/backend/services/llm.py` | Modify | Accept `list[ContextChunk]`; build `[Source: ...]` labeled context; append citation instruction to system prompt |
| `services/backend/tests/test_rag.py` | Modify | Update assertions to `list[ContextChunk]`; add tests for metadata preservation and fallback chain |
| `services/backend/tests/test_llm.py` | Modify | Pass `ContextChunk` instances; test labeled context output and citation prompt instruction |

## Interfaces / Contracts

```python
# models/schemas.py — add to existing file
class ContextChunk(BaseModel):
    text: str
    source_document: str
    source_document_id: str
    source_page: str | None = None
    trace_id: str | None = None
```

**Ingestion** — in the metadata assignment block (after chunking, before `VectorStoreIndex`):
```python
async def ingest_document(...):
    # ... chunking produces nodes ...
    for node in nodes:
        node.metadata["document_id"] = document_id
        node.metadata["professor_collection"] = professor_collection
        # NEW:
        node.metadata["source_filename"] = document.filename
```

**Retrieval** — core mapping (inside `retrieve_context` after filtering):
```python
from models.schemas import ContextChunk

return [
    ContextChunk(
        text=node.get_content(),
        source_document=node.metadata.get("source_filename",
                        node.metadata.get("document_id", "")),
        source_document_id=node.metadata.get("document_id", ""),
        source_page=node.metadata.get("page_label", None),
    )
    for node in filtered
]
```

**LLM context assembly** — inside `generate_response`:
```python
# Build labeled context
labeled_chunks = []
for chunk in context_chunks:
    if chunk.source_document:
        labeled_chunks.append(f"[Source: {chunk.source_document}]\n{chunk.text}")
    else:
        labeled_chunks.append(chunk.text)  # no label
context = "\n\n---\n\n".join(labeled_chunks)
```

**System prompt append** — appended to the existing knowledge instruction:
```python
# The new citation instruction in Spanish:
f"Cuando uses información de las fuentes, indica el documento "
f"usando la etiqueta [Source: ...] que aparece antes del texto. "
f"No inventes fuentes para fragmentos sin etiqueta."
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `ContextChunk` model construction | Pure Pydantic validation — all fields, optionals, defaults |
| Unit | Labeled context assembly | Feed `ContextChunk` instances, assert correct `[Source: ...]` string format |
| Unit | System prompt citation instruction | Assert the instruction string is appended to system prompt in the Ollama payload |
| Unit | Fallback chain | Build nodes with missing `source_filename`, then missing `document_id`; assert correct `source_document` |
| Unit | Empty `source_document` omits label | Assert no `[Source: ...]` prefix when `source_document=""` |
| Integration | `retrieve_context` returns `ContextChunk` list | Mock Qdrant pipeline and reranker; assert return type and metadata flow |

## Migration / Rollout

No migration required. The `source_filename` metadata is injected only during new ingestion — existing Qdrant points lack the key, but the fallback chain handles them transparently. Old behavior (no citations) degrades gracefully.

## Open Questions

- [ ] None — all decisions are covered by spec scenarios.
