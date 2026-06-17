# 1. Baseline Audit and Docs Remediation

## Objective

Bring the repository's documentation and development baseline to a truthful, buildable, and reviewable state before any feature work begins.

## Prerequisites

- Local Docker Desktop installed and running
- Python 3.11+ with `pytest` available (for local test runs)
- Node.js 20+ with `npm` available (for frontend build checks)
- `.env` file copied from `.env.example` with at minimum `POSTGRES_PASSWORD`, `ADMIN_API_KEY`, and `LIVEAVATAR_API_KEY` set

## Detailed Steps

### Step 1: Audit README.md against actual project state
- **Action:** Compare every section of `README.md` with the actual code, file structure, and behavior.
- **Files:** `README.md`
- **Details:**
  - Verify the architecture diagram matches actual service layout (Langfuse, reranker, and scope check are missing from the diagram).
  - Update the API Endpoints table: the current `README.md` shows endpoints that may not match actual routes (e.g., `POST /sessions/students` is actually `POST /students` in the router prefix, and the path shown in README differs).
  - Tech stack table is missing Langfuse and the Reranker component — add them.
  - The Docker Compose section shows an older `docker-compose.yml` (version 3.9, without healthchecks). Replace with the current `docker-compose.yml` content or remove duplicate inline YAML.
  - The "Getting Started" section references `whisper` image `onerahmet/openai-whisper:latest-gpu` but the actual compose uses `onerahmet/openai-whisper-asr-webservice:latest` — fix this.
  - The "Open Items" table has items 5 (Admin auth) and 6 (Student auth) as "Pending" — this is correct for now, but add a note linking to plans/02-auth-backend.md and plans/03-auth-frontend.md.
  - Add a "Project Status" badge or section indicating which phases are complete (RAG connected, Langfuse wired, reranker configurable).
  - Remove the standalone `virtual_profesor/` directory tree that shows `pages/` directory — the project now uses Next.js App Router with `src/app/`. Replace with accurate tree.
  - Fix all occurrences of the misspelled `virtual_profesor` to `virtual_professor` where appropriate (note: the DB name `virtual_profesor` is intentionally misspelled in some places — the spelling in the README should match actual code).

### Step 2: Audit and fix docs/troubleshooting.md
- **Action:** Verify which CRIT items are resolved vs still broken by examining actual code.
- **Files:** `docs/troubleshooting.md`
- **Details:**
  - **CRIT-01 (Relevance threshold):** Check `services/rag.py` for `MIN_RELEVANCE_SCORE` or `filter_nodes_by_score`. The function exists (`filter_nodes_by_score`) and is used in `retrieve_context()`. The environment variable `RAG_MIN_RELEVANCE_SCORE` exists in `.env.example` and `settings.py`. **Verdict: RESOLVED.** Mark as completed with a note confirming it's in production.
  - **CRIT-02 (Reranker):** Check `services/reranker.py` and `services/rag.py` for `BGELocalReranker`. The reranker class exists and is wired in `_get_reranker()`. The env vars `RERANKER_TYPE`, `RERANKER_MODEL`, `RERANKER_TOP_N`, `RERANKER_DEVICE` are in `.env.example` and `settings.py`. **Verdict: RESOLVED.** Update the doc to reflect current implementation.
  - **CRIT-03 (Citation traceability):** Check whether source metadata flows through the pipeline. The `ContextChunk` schema in `schemas.py` has `source_document`, `source_document_id`, `source_page`. The `retrieve_context()` function returns `ContextChunk` objects. The ingestion pipeline (`ingestion.py`) enriches nodes with `document_id` and `document_name`. However, verify whether the LLM prompt includes the `[Source: ...]` tags. The project context says "The backend already includes `[Source: ...]` tags in LLM prompts from RAG context." **Verdict: RESOLVED in backend, but FRONTEND CITATION DISPLAY IS NOT IMPLEMENTED.** Update CRIT-03 to split into backend (done) and frontend (pending, tracked in plan 04).
  - Add a "Current Status" section at the top of `troubleshooting.md` summarizing that CRIT-01 and CRIT-02 are implemented and CRIT-03 is partially implemented (backend complete, frontend pending).
  - Update the Prioritization Matrix to reflect resolved items.
  - Fix "Código afectado" paths that reference old file structure (e.g., `services/rag.py:23` — verify these paths).
  - The entire document is in Spanish. Confirm whether the team prefers English for technical docs going forward. If the decision is English, add a note.

### Step 3: Run backend test suite and confirm baseline pass
- **Action:** Execute the full pytest suite and document results.
- **Files:** `services/backend/tests/`
- **Details:**
  - Run: `cd services/backend && pip install -r requirements.txt && pip install pytest-asyncio httpx aiosqlite && pytest -v`
  - If tests fail, file a quick-fix PR or create issues for each failure. Do NOT proceed to other steps until tests pass.
  - Record the current test count and pass rate.
  - If `aiosqlite` is not in `requirements.txt`, add it as a test dependency or create a `dev-requirements.txt`.
  - Check that the test database path (`test.db`) is in `.gitignore`.
  - Verify the existing fixtures in `conftest.py` work with the current `main.py` imports.

### Step 4: Run frontend production build and confirm it succeeds
- **Action:** Verify the Next.js app compiles without errors.
- **Files:** `services/frontend/`
- **Details:**
  - Run: `cd services/frontend && npm install && npm run build`
  - The app uses Next.js 15 with App Router. If build fails due to TypeScript errors, list them and fix or create tickets.
  - Check for deprecation warnings and note them.
  - Record build output size and duration.
  - If `npm test` fails because no test framework is installed, note this as a gap (addressed in plan 07).

### Step 5: Verify all services start with docker compose
- **Action:** Start the full stack and verify each service responds.
- **Files:** `docker-compose.yml`, `docker-compose.override.yml`
- **Details:**
  - Run: `docker compose up -d` and wait 60 seconds.
  - Run: `docker compose ps` — confirm all 9 services (nginx, frontend, backend, whisper, qdrant, kokoro, postgres, redis, langfuse) show `Up` or `Healthy`.
  - Run: `docker compose logs backend | tail -20` — confirm no startup errors.
  - Verify endpoints:
    - `curl http://localhost/api/health` → `{"status":"ok"}`
    - `curl http://localhost/api/professors` → `[]`
    - `curl http://localhost:6333/health` → Qdrant responds
    - `curl http://localhost:11434` → Ollama responds
  - If Langfuse container fails to start because of missing `LANGFUSE_POSTGRES_PASSWORD` or `LANGFUSE_ENCRYPTION_KEY`, fix `.env.example` to include these or add a note in the README.
  - After verification, `docker compose down`.

### Step 6: Create RELEASE_CHECKLIST.md
- **Action:** Write a release checklist template at the repo root.
- **Files:** `RELEASE_CHECKLIST.md`
- **Details:**
  - Create with the following sections:
    - **Pre-Release:** Verify CHANGELOG is updated, version bumps in `main.py` and `package.json`, all env vars documented.
    - **Auth & Security:** Admin endpoints use JWT (not `X-Admin-Key`), passwords hashed with bcrypt, CORS origins locked, rate limiting on auth endpoints, CSP headers present.
    - **Tests:** Backend `pytest` passes (coverage ≥80%), frontend `npm test` passes, `npm run build` passes.
    - **Docs:** README reflects current state, `.env.example` has all vars with descriptions, API changes documented.
    - **Deployment:** `docker-compose.prod.yml` validated, healthchecks configured, resource limits set, backup strategy confirmed.
    - **Smoke Test:** Health endpoint returns all services green, admin can create professor, upload document, indexing completes (status=ready), student can start session, speak endpoint returns audio.
    - **Post-Release:** Tag release in git, push to production, verify Langfuse traces appear.

### Step 7: Remove stale files
- **Action:** Scan the repo for orphaned or stale files and remove or archive them.
- **Files:** entire repository
- **Details:**
  - Check for `.coverage` files committed to git (should be in `.gitignore`).
  - Check for `test.db` or `*.db` files committed.
  - Check for `__pycache__` directories committed.
  - Verify `.DS_Store` is in `.gitignore` and not tracked.
  - Check for old migration scripts or alembic placeholder files if they exist but are not wired.
  - Remove or move to `docs/archive/` any files that are clearly outdated.
  - Do NOT remove files that look unfamiliar without verifying with the team.

## Acceptance Criteria

- [ ] `README.md` accurately reflects the current project state (services, architecture, API endpoints, directory tree, env vars, run instructions).
- [ ] `docs/troubleshooting.md` has a status section showing CRIT-01/02 as resolved and CRIT-03 backend as resolved (frontend tracked in plan 04).
- [ ] `cd services/backend && pytest` passes with 100% of existing tests green.
- [ ] `cd services/frontend && npm run build` compiles without errors.
- [ ] `docker compose up -d` starts all 9 services and all respond to health checks.
- [ ] `RELEASE_CHECKLIST.md` exists at the repo root with all required sections.
- [ ] No `__pycache__/`, `.db`, `.coverage`, or `.DS_Store` files are tracked in git.
- [ ] `.gitignore` properly excludes all build artifacts and local state files.

## Risks & Notes

- The test suite uses SQLite via `aiosqlite` for speed but this may hide postgres-specific bugs. Document this limitation.
- The `docker compose up` step may fail if Ollama models (`llama3.2:1b`, `nomic-embed-text`) haven't been pulled. The compose file does NOT auto-pull models. Add a note in README or a startup script.
- Langfuse requires 5 env vars (`LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_NEXTAUTH_SECRET`, `LANGFUSE_SALT`, `LANGFUSE_ENCRYPTION_KEY`). Missing these will cause the Langfuse container to fail. Ensure `.env.example` documents all of them.
- The `NEXT_PUBLIC_ADMIN_KEY` in the frontend is a security leak waiting to happen. Document this in known issues.

## Dependencies

- `aiosqlite` package (for test db) — add to `requirements.txt` or a `dev-requirements.txt`
- Docker Desktop 4.x+
- Python packages: `pytest-asyncio`, `httpx`, `aiosqlite`
- Node.js packages: already defined in `package.json`, run `npm install`
