## Exploration: CRIT-03 — Source Citations / Trazabilidad de Fuentes

### Current State

The full RAG pipeline today looks like this:

```
ingestion.py          rag.py                      llm.py
  ┌──────────┐         ┌──────────────┐            ┌──────────┐
  │ Parse    │ ───────→│ Retrieve top │ ──────────→│ Prompt   │
  │ Chunk    │  Qdrant │ 5 nodes      │  list[str] │ Builder  │
  │ Embed    │   store │ Rerank       │   (text    │ Ollama   │
  │ Store    │         │ Score filter │    only)   │ Response │
  └──────────┘         └──────────────┘            └──────────┘
                          metadata ↑              metadata ↓
                          EXISTS in              DISCARDED
                          Qdrant payload
```

#### Metadata stored in Qdrant (per chunk)

Looking at `ingestion.py` lines 97-99:

```python
for node in nodes:
    node.metadata["document_id"] = document_id
    node.metadata["professor_collection"] = professor_collection
```

The only custom metadata set on each chunk before indexing is:
- `document_id` — UUID of the document in SQL
- `professor_collection` — the Qdrant collection name

Additionally, LlamaIndex's built-in readers may attach their own metadata to nodes:
- `PDFReader` / `DocxReader` / `PptxReader`: `file_name`, `file_path`, `file_type`, `file_size`
- `SimpleWebPageReader`: usually minimal — `url` may or may not survive
- `SimpleDirectoryReader`: `file_name`, `file_path`

**Critically**: No `filename` (human-readable), no `page_number`, no `section_title`, no `url` is explicitly stored. The `document_id` UUID exists but is not propagated downstream.

#### Data flow from rag.py to llm.py

**`rag.py:retrieve_context()`** (line 102):
```python
return [node.get_content() for node in filtered]
```

This calls `node.get_content()` which returns **only the text content** of each chunk. All metadata attached to the `NodeWithScore` object is discarded at this point — including `document_id`, `professor_collection`, and any reader-added metadata.

The return type is `list[str]` — plain text strings with zero provenance information.

**`llm.py:generate_response()`** receives it as:
```python
context_chunks: list[str]
```

Then assembles (line 28):
```python
context = "\n\n---\n\n".join(context_chunks)
```

The chunks are concatenated with separators but no source labels. The LLM cannot distinguish which chunk came from which document.

#### Current system prompt

`llm.py` lines 41-45:
```python
"system": (
    f"{system_prompt}\n\n"
    f"Use the following knowledge to answer the student's question. "
    f"If the answer is not in the knowledge, say you don't have that information."
)
```

This is a static instruction that:
- Instructs the LLM to use the knowledge
- Tells it to refuse if not in knowledge
- Does NOT ask it to cite sources
- Has no placeholders or markers for source attribution

#### Document model (`models/db.py`)

The `Document` model stores:
```python
class Document(Base):
    id: Mapped[uuid.UUID]
    professor_id: Mapped[uuid.UUID]
    filename: Mapped[str]          # "mi_clase.pdf" — human-readable
    format: Mapped[str]            # "pdf", "docx", "url"
    status: Mapped[DocumentStatus]
    chunk_count: Mapped[int]
    error_message: Mapped[str | None]
    uploaded_at: Mapped[datetime]
```

The `filename` field contains the human-readable document name but is never written into Qdrant payloads. The SQL `Document` table has it, but the Qdrant chunks don't.

### Affected Areas

| File | Why Affected |
|------|-------------|
| `services/ingestion.py` | Must add `filename` (and optionally `page_number`, `section_title`, `url`) to node metadata before indexing |
| `services/rag.py` | Must preserve metadata from `NodeWithScore` objects instead of discarding it with `get_content()` |
| `services/llm.py` | Must accept structured context with source metadata; must update system prompt with citation instruction; must format context with source labels |
| `routers/sessions.py` | Optional: if citations should be returned alongside response text |
| `models/schemas.py` | Optional: new response model for structured citations |
| `tests/test_rag.py` | Updated `retrieve_context` return type requires new tests |
| `tests/test_llm.py` | New tests for citation-aware prompt building |

### Gap Analysis

#### 1. Ingestion — metadata to add

| Field | Source | Priority |
|-------|--------|----------|
| `filename` | `Document.filename` from SQL | **Required** |
| `document_id` | Already stored ✅ | — |
| `page_number` | LlamaIndex PDF reader may add; otherwise extract from node metadata | Nice-to-have |
| `section_title` | Only if document structure is parsed (PDF headings) | Nice-to-have |
| `url` | For URL-based sources | Required for web content |
| `source_label` | Derived from filename (e.g., "Chapter 3 - Mitosis.pdf") | Recommended |

**Approach**: In `ingestion.py`, read `Document.filename` from the DB before chunking, and inject it into every node's metadata alongside `document_id`.

#### 2. Pipeline passage — metadata must survive

**Problem**: `rag.py` line 102 calls `node.get_content()` which strips metadata.

**Solution**: Change `retrieve_context` to return `list[NodeWithScore]` or a new dataclass `ContextChunk(s)`, and let upstream code decide what to extract.

**Option A**: Return `list[NodeWithScore]` — let caller access `.text` and `.metadata` separately. Minimal change.

**Option B**: Introduce a `ContextChunk` dataclass/Pydantic model:
```python
class ContextChunk(BaseModel):
    text: str
    source_document: str       # human-readable filename
    source_document_id: str    # UUID for lookups
    source_page: int | None    # page number if available
    source_url: str | None     # URL for web sources
```

**Recommendation**: Option B. A typed model is cleaner at the boundaries and self-documenting. `rag.py` creates `ContextChunk` objects from `NodeWithScore`, `llm.py` receives them.

#### 3. System prompt — citation instruction

Current system prompt must be updated to:

```
Use the following knowledge to answer the student's question.
If the answer is not in the knowledge, say you don't have that information.
When you use specific information, cite the source document in brackets
like [Source: Filename.pdf] at the end of the relevant sentence.
```

**Key design decision**: Should citation instructions be:
- **(a) Hardcoded in `llm.py`** — simplest, always on
- **(b) Part of `Professor.system_prompt`** — customizable per professor, but requires migration
- **(c) Both** — base instruction in `llm.py` + professor can override

**Recommendation**: **(a)** for now. The base instruction is a core pipeline concern, not professor-specific. Can be elevated later.

#### 4. Context assembly with source labels

Instead of:
```python
context = "\n\n---\n\n".join(context_chunks)
```

Build:
```python
context_parts = []
for i, chunk in enumerate(context_chunks, 1):
    source = chunk.source_document
    label = f"[Document {i}: {source}]"
    context_parts.append(f"{label}\n{chunk.text}")

context = "\n\n".join(context_parts)
```

This way the LLM sees each chunk labeled:
```
[Document 1: Chapter 3 - Mitosis.pdf]
The process of mitosis involves...

[Document 2: cell-biology-notes.docx]
Mitosis occurs in four phases...
```

#### 5. Frontend citation parsing (optional)

Two approaches:

**Option A (Text markers)**: LLM outputs `[Source: filename]` in the response. Frontend can regex-parse these and render them as clickable footnotes or tooltips. Requires no API changes.

**Option B (Structured response)**: API returns `{ "text": "...", "citations": [{"source": "...", "text_snippet": "..."}] }`. Requires response model changes and possibly structured LLM output parsing.

**Recommendation**: Option A for the first pass. It's backwards-compatible (frontend just sees text), tests are simpler, and it doesn't require changing the API contract.

#### 6. Backwards-compatibility considerations

- `rag.retrieve_context()` currently returns `list[str]`. Changing the return type breaks every caller (currently only `sessions.py:speak()`)
- Migration path: introduce a new function (e.g., `retrieve_context_with_sources()`) and migrate callers, OR change the return type and update the single caller in the same change
- **Recommendation**: Change the return type since there's only one caller. The compiler/Pyright will catch it immediately.

### Dependencies and Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| **LLM may not consistently cite** despite instruction | Medium — inconsistent citations reduce trust | Test with multiple queries; iterate on prompt wording; consider few-shot examples in prompt |
| **Existing Qdrant points lack citation metadata** | High — all existing documents need re-ingestion | Re-ingestion migration: add `filename` to ingestion, re-process existing docs, OR add fallback: if `filename` missing in payload, use `document_id` as source label |
| **Re-ingestion overhead** for existing professor documents | Medium | Depends on document count. Write a one-time migration script in admin router that re-processes all documents for a professor |
| **Token usage increase** from inline source labels | Low | Each label is ~10-15 tokens, negligible vs. context window |
| **Frontend needs to parse `[Source: ...]` markers** | Low | If frontend ignores markers, they just appear as text — no breakage |

### Approaches

#### 1. ✅ Lightweight — inline text markers (RECOMMENDED)

Change the minimum to add source awareness:
- Inject `filename` into Qdrant payload during ingestion
- Return `ContextChunk` from `rag.py` instead of `list[str]`
- Build source-labeled context in `llm.py`
- Add citation instruction to system prompt

**Effort**: Low-Medium (~3-5 hours)
**Files changed**: `ingestion.py`, `rag.py`, `llm.py`, tests

#### 2. Full structured citations

Everything in Approach 1, plus:
- New API response model with `citations` array
- Backend parses LLM response for structured citations
- Frontend renders citations as interactive elements

**Effort**: Medium-High (~8-12 hours)
**Files changed**: All of Approach 1 + `schemas.py`, `sessions.py`, frontend

#### 3. Minimal — system prompt only

Only update the system prompt to ask for citations, without changing the pipeline. No metadata changes.

**Effort**: Very Low (~30 min)
**Risk**: LLM will invent source names since chunks have no labels — **hallucination risk**. Not recommended.

### Recommendation

**Approach 1 — Lightweight inline text markers**.

Rationale:
1. Addresses the core problem: responses are traced to source documents
2. Backwards-compatible for the frontend (citations are inline text)
3. Minimal code changes — no new models, no API contract changes, no re-indexing for new documents
4. The `filename` field already exists in the `Document` model — just need to propagate it
5. Can be extended to Approach 2 later if the frontend team requests structured data
6. Consistent with the iterative pattern of CRIT-01 (threshold) → CRIT-02 (reranker) → CRIT-03 (citations)

**Migration for existing documents**: Add a one-time admin endpoint or migration script that re-processes existing `ready` documents through the updated ingestion pipeline. Without this, old chunks won't have `filename` in their payload, and the system would fall back to `document_id` as the source label.

### Change Name Recommendation

**`rag-source-citations`** — follows the `rag-{feature}` convention from CRIT-01 (`rag-relevance-threshold`) and CRIT-02 (`rag-reranker`).

### Ready for Proposal

Yes. Exploration is complete. All gaps identified, approach selected, risks documented.
