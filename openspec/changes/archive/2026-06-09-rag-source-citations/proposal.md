# Proposal: RAG Source Citations

## Intent

The LLM generates answers without citing which document provided the information. Students can't verify claims, professors can't debug bad responses, and academic compliance fails. This change adds lightweight inline source markers so every claim is traceable to its source document.

## Scope

### In Scope
- `ContextChunk` Pydantic model with `text`, `source_document`, `source_document_id`, `source_page`
- Enriched Qdrant payloads — inject `filename` from SQL `Document` during ingestion
- `retrieve_context()` return type change: `list[str]` → `list[ContextChunk]`
- Source-labeled context assembly in `llm.py` with `[Source: filename]` markers
- System prompt updated with citation instruction
- Fallback to `document_id` when `filename` missing in Qdrant payload
- Tests for all changes

### Out of Scope
- Re-ingestion admin endpoint (deferred)
- Frontend citation parsing / tooltips (inline text only)
- Structured citations array in API response

## Capabilities

### New Capabilities
- `rag-source-citations`: source document traceability through the RAG pipeline — ingestion metadata, typed context chunks, and LLM citation prompting

### Modified Capabilities
- None

## Approach

Ingestion (`ingestion.py`) reads `Document.filename` from SQL and injects it into each node's Qdrant payload. `rag.py` introduces a `ContextChunk` model and returns `list[ContextChunk]` instead of `list[str]`, preserving metadata from `NodeWithScore`. `llm.py` labels chunks with `[Source: filename]` in the context string and adds a citation instruction to the system prompt. If `filename` is absent in a payload, `document_id` serves as the fallback label.

This is Approach 1 from exploration — lightweight inline text markers. No API contract changes, no re-indexing for new documents.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `services/ingestion.py` | Modified | Inject `filename` into node metadata before Qdrant index |
| `services/rag.py` | Modified | Return `list[ContextChunk]`, preserve metadata from nodes |
| `services/llm.py` | Modified | Accept `ContextChunk`, build source-labeled context, update system prompt |
| `tests/test_rag.py` | Modified | New tests for typed return + metadata preservation |
| `tests/test_llm.py` | Modified | Tests for citation prompt and source labels |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Existing Qdrant points lack `filename` | High | Fallback to `document_id`; re-ingestion endpoint deferred |
| LLM inconsistently cites despite instruction | Med | Iterate on prompt; add few-shot examples if needed |
| Token increase from source markers | Low | Each label ~15 tokens — negligible |

## Rollback Plan

Revert `rag.py` return type to `list[str]`, restore `node.get_content()` extraction, and revert `llm.py` context assembly and system prompt. Ingestion metadata change is additive — old chunks won't have `filename` but fallback handles it.

## Dependencies

- None. All changes are self-contained in the backend services.

## Success Criteria

- [ ] Every chunk in LLM context has a `[Source: filename]` label
- [ ] LLM response includes source citations for at least 80% of factual claims (baseline: 0%)
- [ ] `retrieve_context()` returns `list[ContextChunk]` with valid metadata for every chunk
- [ ] All existing tests pass + new tests cover citation flow
- [ ] Missing `filename` in payload gracefully falls back to `document_id`
