# Langfuse Observability Specification

## Purpose

Every `/speak` request runs a multi-step pipeline with zero visibility into latency, cost, or failures. This spec adds Langfuse tracing so each request produces a root trace with child spans for every pipeline step, including token-based cost estimation and professor/student metadata enrichment.

## Requirements

### Requirement: Initialization and Lifecycle

The Langfuse client MUST be initialized during FastAPI startup and flushed on shutdown. When `LANGFUSE_ENABLE=false`, the client MUST NOT be initialized and `get_langfuse()` MUST return `None`.

#### Scenario: Client initialized in lifespan

- GIVEN `LANGFUSE_ENABLE=true` with valid credentials
- WHEN the FastAPI lifespan enters startup
- THEN a `Langfuse` client SHALL be created and returned by `get_langfuse()`

#### Scenario: Flush on shutdown

- GIVEN an initialized Langfuse client
- WHEN the lifespan enters shutdown
- THEN `shutdown_async()` SHALL be called

#### Scenario: No-op when disabled

- GIVEN `LANGFUSE_ENABLE=false`
- WHEN `get_langfuse()` is called
- THEN the return SHALL be `None`

### Requirement: Pipeline Tracing

The `/speak` endpoint MUST create one root trace per request. Each pipeline step — STT, scope check (`is_in_scope`), RAG retrieval, reranker (if enabled), LLM generation (`generate_response`), TTS — MUST create a child span capturing duration. On failure, the span MUST capture the error.

#### Scenario: Root trace per request

- GIVEN `LANGFUSE_ENABLE=true`
- WHEN `POST /sessions/{id}/speak` is called
- THEN a root trace SHALL be created with `name="speak"`

#### Scenario: Child spans for each step

- GIVEN an active root trace
- WHEN the pipeline executes
- THEN each step (STT, scope check, RAG, reranker, LLM, TTS) SHALL produce a child span under the root trace

#### Scenario: Error captured on failure

- GIVEN an active root trace
- WHEN a pipeline step raises an exception
- THEN the corresponding span SHALL capture the error
- AND subsequent steps SHALL NOT execute
- AND the root trace SHALL still end

### Requirement: LLM Token Tracking

LLM spans MUST include estimated token counts via `tiktoken` (`cl100k_base`). The model name MUST be recorded on each LLM span.

#### Scenario: Token usage on LLM span

- GIVEN a completed LLM generation step
- WHEN the span ends
- THEN `usage.input` and `usage.output` SHALL contain estimated token counts
- AND `model` SHALL be set to the Ollama model name

### Requirement: Metadata Enrichment

Every trace MUST include `professor_id`, `professor_name`, `session_id`, and `student_id` as metadata. These MUST be consistent across all spans within the same trace.

#### Scenario: Professor metadata on trace

- GIVEN a `/speak` request for professor "Dr. Smith" (id "prof-1"), session "sess-42", student "stud-7"
- WHEN the root trace is created
- THEN `metadata` SHALL contain `professor_id`, `professor_name`, `session_id`, and `student_id`

### Requirement: RAG Tracing

RAG retrieval MUST be traced via `LangfuseCallbackHandler` on LlamaIndex's `Settings.callback_manager`. Chunk scores from Qdrant and the reranker MUST be captured.

#### Scenario: RAG internals captured

- GIVEN `LangfuseCallbackHandler` registered on `Settings.callback_manager`
- WHEN `retrieve_context()` executes
- THEN retrieved chunks SHALL appear under a RAG span with their similarity scores

### Requirement: Configuration

| Variable | Type | Default | Description |
|---|---|---|---|
| `LANGFUSE_ENABLE` | `bool` | `false` | Master enable switch |
| `LANGFUSE_SECRET_KEY` | `str` | `""` | API secret key |
| `LANGFUSE_PUBLIC_KEY` | `str` | `""` | API public key |
| `LANGFUSE_HOST` | `str` | `https://cloud.langfuse.com` | Server URL |
| `LANGFUSE_RELEASE` | `str` | `"0.1.0"` | Release version tag |

#### Scenario: Defaults without env vars

- GIVEN no Langfuse env vars
- WHEN `Settings` initializes
- THEN `langfuse_enable` SHALL be `false`
- AND `langfuse_host` SHALL be `https://cloud.langfuse.com`

### Requirement: Self-hosted Deployment

`docker-compose.yml` MUST include a `langfuse` service with its own PostgreSQL and Redis. These services MUST NOT be required for local development without explicit opt-in.

#### Scenario: Compose services declared

- GIVEN the project's `docker-compose.yml`
- WHEN inspected
- THEN it SHALL contain `langfuse`, `langfuse-postgres`, and `langfuse-redis` services
