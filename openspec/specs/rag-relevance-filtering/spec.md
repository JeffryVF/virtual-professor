# RAG Relevance Filtering Specification

## Purpose

RAG retrieval always returns `top_k` chunks regardless of actual relevance. This spec adds a minimum relevance score filter so the pipeline discards noisy chunks and responds gracefully when no relevant context exists — preventing LLM hallucination from garbage-in input.

## Requirements

### Requirement: Relevance Score Threshold

The retrieval pipeline MUST filter all chunks by a minimum relevance score. Chunks with `score < threshold` SHALL be discarded before reaching the LLM. The threshold value SHALL be read exclusively from the `RAG_MIN_RELEVANCE_SCORE` environment variable — there MUST be no hardcoded default in code.

#### Scenario: Relevant query returns only qualifying chunks

- GIVEN `RAG_MIN_RELEVANCE_SCORE=0.75` in the environment
- AND a query whose top-5 chunks have scores `[0.92, 0.88, 0.81, 0.67, 0.42]`
- WHEN retrieval applies the threshold filter
- THEN only the first three chunks (`score >= 0.75`) SHALL be returned
- AND the remaining two chunks SHALL be discarded

#### Scenario: No chunk meets the threshold

- GIVEN `RAG_MIN_RELEVANCE_SCORE=0.75` in the environment
- AND a query whose highest-scoring chunk is `0.63`
- WHEN the threshold filter runs
- THEN the pipeline SHALL return an empty context list `[]`

#### Scenario: Threshold at 0.0 passes everything

- GIVEN `RAG_MIN_RELEVANCE_SCORE=0.0` in the environment (rollback scenario)
- WHEN the filter runs
- THEN all retrieved chunks SHALL pass regardless of score

### Requirement: Graceful Empty-Context Response

When the context list is empty after threshold filtering, the LLM MUST respond with a pre-defined graceful message instead of fabricating an answer.

#### Scenario: Empty context triggers graceful response

- GIVEN an empty context list `[]`
- WHEN the LLM is called with that context
- THEN the response SHALL be `"No encontré información sobre eso en mis fuentes"`

#### Scenario: Non-empty context does not trigger graceful response

- GIVEN a context list with at least one qualifying chunk
- WHEN the LLM is called
- THEN the response SHALL be generated normally from the provided context
- AND the graceful message SHALL NOT appear

### Requirement: Professor Notification on Threshold Failure

When scope validation passes (i.e., the query is within the professor's knowledge domain) but the threshold filter produces an empty context, the system SHOULD notify the professor. Notification SHALL be fire-and-forget: log a warning AND record an event in the database for dashboard visibility.

#### Scenario: Scope passes, threshold filters all chunks

- GIVEN a query that passes professor scope validation
- AND the threshold filter returns an empty context list
- WHEN the pipeline processes the query
- THEN a WARNING-level log SHALL be emitted with the professor ID and query text
- AND a notification event SHALL be persisted to the database

#### Scenario: Scope fails before threshold check

- GIVEN a query that fails professor scope validation
- WHEN the pipeline processes the query
- THEN the threshold filter SHALL NOT execute
- AND no notification event SHALL be recorded for threshold failure

### Requirement: Required Env Var — No Hardcoded Default

The threshold MUST be configured exclusively through the `RAG_MIN_RELEVANCE_SCORE` environment variable in `core/config.py`. There MUST be no default value in code. If the variable is missing or contains an invalid (non-float) value, the application SHALL fail at startup with a clear configuration error.

#### Scenario: Env var populates threshold correctly

- GIVEN `RAG_MIN_RELEVANCE_SCORE=0.5` in the environment
- WHEN the application initializes `Settings`
- THEN `rag_min_relevance_score` SHALL be `0.5`

#### Scenario: Missing env var fails at startup

- GIVEN `RAG_MIN_RELEVANCE_SCORE` is NOT set in the environment
- WHEN the application initializes `Settings`
- THEN a `ValidationError` SHALL be raised
- AND the application SHALL NOT start

#### Scenario: Invalid env value fails at startup

- GIVEN `RAG_MIN_RELEVANCE_SCORE=banana` in the environment
- WHEN the application initializes `Settings`
- THEN a `ValidationError` SHALL be raised
- AND the application SHALL NOT start
