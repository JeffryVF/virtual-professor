# Delta for rag-reranking

## ADDED Requirements

None.

## MODIFIED Requirements

### Requirement: Reranker Configuration

The system SHALL expose these settings through `core/config.py`:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `reranker_type` | `str` | `"none"` | `"bge"` enables, `"none"` disables |
| `reranker_top_n` | `int` | `6` | Chunks to keep after reranking |
| `reranker_model` | `str` | `"BAAI/bge-reranker-v2-m3"` | Model override |
| `reranker_device` | `str` | `"cpu"` | Torch device |
| `rag_retrieval_top_k` | `int` | `40` | Chunks to retrieve from Qdrant |

All settings SHALL be read from environment variables at startup.
(Previously: `reranker_top_n` default 5 with description "Chunks to rerank". No `rag_retrieval_top_k` row.)

#### Scenario: Default config disables reranker

- GIVEN no reranker or retrieval env vars set
- WHEN `Settings` initializes
- THEN `reranker_type` SHALL be `"none"`
- AND `reranker_top_n` SHALL be `6`
- AND `rag_retrieval_top_k` SHALL be `40`

#### Scenario: Explicit bge config is accepted

- GIVEN `RERANKER_TYPE=bge` in environment
- WHEN `Settings` initializes
- THEN `reranker_type` SHALL be `"bge"`

### Requirement: Pipeline Integration

`retrieve_context()` SHALL retrieve `rag_retrieval_top_k` chunks from Qdrant. When `reranker_type = "bge"`, the reranker SHALL score ALL retrieved chunks. The pipeline SHALL ALWAYS truncate to the top `reranker_top_n` chunks (regardless of reranker status), then apply the score threshold filter. When `reranker_type = "none"`, the pipeline SHALL skip the reranker step entirely but SHALL still truncate to `reranker_top_n` in original retrieval order.
(Previously: Pipeline retrieved `top_k=5`, reranker only saw top `reranker_top_n` chunks, no post-reranker truncation.)

#### Scenario: Reranker enabled re-orders and truncates before threshold

- GIVEN `reranker_type="bge"`, `rag_retrieval_top_k=40`, and `reranker_top_n=6`
- AND 40 chunks retrieved from Qdrant
- WHEN the pipeline processes a query
- THEN all 40 chunks SHALL be re-ranked by the cross-encoder
- AND the top 6 chunks SHALL be kept after reranking
- AND the score threshold filter SHALL apply to those 6 chunks only

#### Scenario: Post-reranker truncation limits chunks before threshold

- GIVEN `reranker_type="bge"` and `reranker_top_n=3`
- AND 40 chunks retrieved from Qdrant
- WHEN the pipeline processes a query
- THEN at most 3 chunks SHALL reach the score threshold filter

#### Scenario: Reranker disabled truncates in retrieval order

- GIVEN `reranker_type="none"`
- WHEN the pipeline processes a query
- THEN the reranker step SHALL be skipped
- AND top-N truncation to `reranker_top_n` SHALL still apply in original retrieval order
- AND the threshold filter SHALL apply to the truncated list

## REMOVED Requirements

None.
