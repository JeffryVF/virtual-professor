# RAG Source Citations Specification

## Purpose

The RAG pipeline returns raw chunk text without document provenance, so LLM answers cannot be traced to source materials. This spec adds lightweight source document markers throughout the pipeline — ingestion metadata enrichment, typed context chunks, and citation-labeled LLM context — enabling every generated claim to be attributable to its source document.

## Requirements

### Requirement: ContextChunk Data Model

The system MUST define a Pydantic `BaseModel` `ContextChunk` in `services/backend/services/schemas.py` with these fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `text` | `str` | required | Chunk content |
| `source_document` | `str` | required | Human-readable filename |
| `source_document_id` | `str` | required | UUID of the source document |
| `source_page` | `str \| None` | `None` | Page number if available |
| `trace_id` | `str \| None` | `None` | Future Langfuse correlation |

#### Scenario: ContextChunk with required fields only

- GIVEN `text`, `source_document`, and `source_document_id`
- WHEN `ContextChunk(text="...", source_document="lecture.pdf", source_document_id="uuid-123")` is created
- THEN `source_page` SHALL be `None`
- AND `trace_id` SHALL be `None`

#### Scenario: ContextChunk with all fields populated

- GIVEN values for all five fields
- WHEN the model is created
- THEN every field SHALL match its constructor argument

### Requirement: Ingestion Metadata Enrichment

When indexing documents, the ingestion pipeline MUST read `filename` from the SQL `Document` table and inject it into every chunk node's metadata under key `source_filename` before storing in Qdrant.

#### Scenario: Filename propagates to Qdrant payload

- GIVEN a `Document` with `filename = "intro_to_ai.pdf"` and 10 chunks
- WHEN the ingestion pipeline indexes those chunks into Qdrant
- THEN every Qdrant point SHALL have `source_filename = "intro_to_ai.pdf"` in its payload

### Requirement: Typed Retrieval Contract

`retrieve_context()` in `rag.py` MUST return `list[ContextChunk]` instead of `list[str]`. Each chunk SHALL be built from a `NodeWithScore`: `text` from node content, `source_document` from `source_filename` metadata, `source_document_id` from `document_id` metadata, and `source_page` from node metadata when present.

#### Scenario: retrieve_context returns typed chunks

- GIVEN a query matching 3 Qdrant nodes with complete metadata
- WHEN `retrieve_context()` is called
- THEN the return SHALL be `list[ContextChunk]` of length 3
- AND each chunk SHALL have `source_document` matching the node's `source_filename`

#### Scenario: No chunks retrieved returns empty list

- GIVEN a query matching zero Qdrant nodes
- WHEN `retrieve_context()` is called
- THEN the return SHALL be `[]`

### Requirement: Source-Labeled LLM Context

`llm.py` MUST build the context string by prepending `[Source: {source_document}]\n` before each chunk's text. Labeled chunks SHALL be concatenated with `\n\n` separators.

#### Scenario: Single chunk produces labeled context

- GIVEN one `ContextChunk` with `source_document = "lecture.pdf"` and `text = "Neural networks use backpropagation."`
- WHEN the context is assembled for the LLM
- THEN the context string SHALL be `"[Source: lecture.pdf]\nNeural networks use backpropagation."`

#### Scenario: Multiple chunks with distinct source labels

- GIVEN two `ContextChunk`s from `"paper.pdf"` and `"slides.pdf"`
- WHEN the context is assembled
- THEN each chunk SHALL be preceded by its own `[Source: ...]` label
- AND chunks SHALL be separated by `\n\n`

### Requirement: Citation Instruction in System Prompt

The system prompt MUST include an instruction directing the LLM to cite sources using the `[Source: filename]` labels present in the context. The instruction SHALL be in Spanish matching the professor persona.

#### Scenario: System prompt contains citation instruction

- GIVEN a `SystemPrompt` template
- WHEN the prompt is compiled
- THEN it SHALL instruct the LLM to reference `[Source: ...]` labels when citing
- AND the instruction SHALL be in natural Spanish

### Requirement: Fallback for Missing Filename

If a Qdrant payload lacks `source_filename`, the system MUST use the `document_id` UUID as the `source_document` field value.

#### Scenario: Legacy document without filename metadata

- GIVEN a Qdrant node with `document_id` but no `source_filename` in payload
- WHEN `retrieve_context()` builds a `ContextChunk`
- THEN `source_document` SHALL be set to the `document_id` UUID
- AND the LLM context SHALL show `[Source: {uuid}]`

### Requirement: No Citation Hallucination

If neither `source_filename` nor `document_id` exists in the payload, the chunk SHALL be passed to the LLM without a `[Source: ...]` label. The system prompt MUST instruct the LLM not to invent source names for unlabeled chunks.

#### Scenario: Unlabeled chunk passes through without citation marker

- GIVEN a Qdrant node whose payload has neither `source_filename` nor `document_id`
- WHEN `retrieve_context()` builds a `ContextChunk`
- THEN `source_document` SHALL be an empty string `""`
- AND the LLM context for this chunk SHALL omit the `[Source: ...]` prefix entirely
- AND the LLM SHALL NOT fabricate a source name for this chunk
