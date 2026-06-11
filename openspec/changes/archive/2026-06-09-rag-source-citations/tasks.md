# Tasks: RAG Source Citations

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~150 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Phase 1: Foundation — ContextChunk Model

- [x] 1.1 RED: Write test for `ContextChunk` Pydantic model (required fields, all fields, defaults)
- [x] 1.2 GREEN: Add `ContextChunk(BaseModel)` to `services/backend/models/schemas.py`
- [x] 1.3 REFACTOR: Run suite, verify zero regressions

## Phase 2: Ingestion — Source Metadata

- [x] 2.1 RED: Write test asserting `source_filename` is injected into node metadata from SQL `Document.filename`
- [x] 2.2 GREEN: Add `node.metadata["source_filename"] = document.filename` in `ingestion.py` before Qdrant index
- [x] 2.3 REFACTOR: Run suite, verify zero regressions

## Phase 3: Retrieval — Typed Chunks + Fallback

- [x] 3.1 RED: Write test asserting `retrieve_context()` returns `list[ContextChunk]` with metadata preserved
- [x] 3.2 GREEN: Update `rag.py` — import `ContextChunk`, map `NodeWithScore` to `ContextChunk`, change return type
- [x] 3.3 RED: Write test for fallback chain: `source_filename` → `document_id` → `""`
- [x] 3.4 GREEN: Implement fallback chain in `ContextChunk` construction in `rag.py`
- [x] 3.5 RED: Write test for empty retrieval returns `[]`
- [x] 3.6 REFACTOR: Run suite, verify zero regressions

## Phase 4: LLM — Labeled Context + Citation Prompt

- [x] 4.1 RED: Write test for `[Source: ...]` labeled context assembly from `list[ContextChunk]`
- [x] 4.2 RED: Write test for citation instruction appended to system prompt in Spanish
- [x] 4.3 GREEN: Update `generate_response` — accept `list[ContextChunk]`, build labeled context string
- [x] 4.4 GREEN: Append citation instruction to system prompt in the Ollama payload
- [x] 4.5 REFACTOR: Run suite, verify zero regressions

## Phase 5: Edge Cases — Unlabeled Chunks

- [x] 5.1 RED: Write test for empty `source_document` omitting `[Source: ...]` prefix
- [x] 5.2 GREEN: Ensure empty `source_document` suppresses the label (should be inherent from 4.3 logic)
- [x] 5.3 REFACTOR: Run full test suite with coverage, verify >=80%
