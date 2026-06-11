# RAG Reranking Specification

## Purpose

Cosine-similarity retrieval ranks by embedding proximity, not semantic usefulness. This spec adds a pluggable cross-encoder reranker that scores query-chunk pairs directly, so the LLM receives the most useful context first.

## Requirements

### Requirement: RerankerAdapter Interface

The system MUST define an abstract `RerankerAdapter` class with a method `rerank(query: str, chunks: Sequence[NodeWithScore]) -> list[int]` that returns chunk indices in re-ranked order. The interface SHALL be importable from a dedicated module under `services/backend/services/`.

#### Scenario: Interface contract with valid inputs

- GIVEN a `RerankerAdapter` subclass
- WHEN `rerank("query", [node_a, node_b, node_c])` is called
- THEN the return SHALL be a `list[int]` of the same length as `chunks`
- AND each integer SHALL be a valid index into the original `chunks` list

#### Scenario: Interface contract with empty chunks

- GIVEN a `RerankerAdapter` subclass
- WHEN `rerank("query", [])` is called
- THEN the return SHALL be an empty list `[]`

### Requirement: BGELocalReranker Implementation

The system MUST provide `BGELocalReranker` implementing `RerankerAdapter` via `BAAI/bge-reranker-v2-m3` cross-encoder. It SHALL lazy-load the model and return indices sorted by score descending.

#### Scenario: Reranker re-orders chunks by relevance

- GIVEN a `BGELocalReranker` with a mocked cross-encoder that returns scores `[0.2, 0.9, 0.5]` for three chunks
- WHEN `rerank("query", chunks)` is called
- THEN the returned indices SHALL be `[1, 2, 0]` (highest score first)

#### Scenario: Single chunk returns identity ordering

- GIVEN a `BGELocalReranker` with exactly one chunk
- WHEN `rerank("query", [chunk])` is called
- THEN the returned indices SHALL be `[0]`

### Requirement: Reranker Configuration

The system SHALL expose these settings through `core/config.py`:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `reranker_type` | `str` | `"none"` | `"bge"` enables, `"none"` disables |
| `reranker_top_n` | `int` | `5` | Chunks to rerank |
| `reranker_model` | `str` | `"BAAI/bge-reranker-v2-m3"` | Model override |
| `reranker_device` | `str` | `"cpu"` | Torch device |

All settings SHALL be read from environment variables at startup.

#### Scenario: Default config disables reranker

- GIVEN no reranker env vars set
- WHEN `Settings` initializes
- THEN `reranker_type` SHALL be `"none"`
- AND `reranker_top_n` SHALL be `5`

#### Scenario: Explicit bge config is accepted

- GIVEN `RERANKER_TYPE=bge` in environment
- WHEN `Settings` initializes
- THEN `reranker_type` SHALL be `"bge"`

### Requirement: Pipeline Integration

`retrieve_context()` SHALL insert reranking between retrieval and score threshold filtering. When `reranker_type = "none"`, the pipeline SHALL behave identically to before. The reranker SHALL only see the top `reranker_top_n` chunks.

#### Scenario: Reranker enabled re-orders before threshold

- GIVEN `reranker_type="bge"` and `reranker_top_n=5`
- AND 5 chunks retrieved from Qdrant
- WHEN the pipeline processes a query
- THEN chunks SHALL be re-ranked by the cross-encoder BEFORE the score threshold filter

#### Scenario: Reranker disabled preserves original behavior

- GIVEN `reranker_type="none"`
- WHEN the pipeline processes a query
- THEN the reranker step SHALL be skipped
- AND chunk order SHALL be the original retrieval order
- AND the threshold filter SHALL apply as before

### Requirement: Graceful Fallback on Error

If the reranker model fails to load or raises an exception during inference, the system SHALL log a WARNING with the error details and SHALL fall back to the original chunk order. The pipeline SHALL NOT crash and SHALL continue to the threshold filter.

#### Scenario: Model load failure falls back gracefully

- GIVEN `reranker_type="bge"`
- AND the cross-encoder model raises `OSError` on load
- WHEN the pipeline processes a query
- THEN a WARNING SHALL be logged with the error message
- AND chunks SHALL remain in original retrieval order
- AND the threshold filter SHALL execute normally

#### Scenario: Inference error falls back gracefully

- GIVEN `reranker_type="bge"`
- AND the reranker raises `RuntimeError` during scoring
- WHEN the pipeline processes a query
- THEN a WARNING SHALL be logged
- AND chunks SHALL remain in original order
- AND the pipeline SHALL NOT crash
