# 7. Comprehensive Test Suite

## Objective

Build a thorough test suite covering all backend modules (auth, RAG, sessions, admin, health) and set up frontend testing with vitest and testing-library for core flows.

## Prerequisites

- Phases 1-6 complete — all features exist and are functional
- Phase 2 (auth backend) — auth endpoints and dependencies available
- Phase 4 (RAG visible) — indexing and chunk endpoints available
- Phase 6 (observability) — health endpoint updated

## Detailed Steps

### Step 1: Review and refactor existing test infrastructure
- **Action:** Audit the current `conftest.py` and test files for gaps.
- **Files:** `services/backend/tests/conftest.py`, `services/backend/tests/`
- **Details:**
  - Current `conftest.py` sets env vars and provides `async_app`, `async_client`, `db_session` fixtures.
  - **Gaps to fix:**
    - Missing fixture for an authenticated user token (`auth_token`).
    - Missing fixture for an admin user token (`admin_token`).
    - Missing fixture for creating a professor (`test_professor`).
    - Missing fixture for creating a document (`test_document`).
    - The `db_session` fixture is per-test but the `setup_database` fixture is session-scoped — this is correct.
    - Add `pytest.fixture(autouse=True)` for clearing Redis between tests if Redis mocking is added.
  - Add these fixtures to `conftest.py`:

    ```python
    @pytest_asyncio.fixture
    async def auth_headers(async_client):
        """Register a student user and return authorization headers."""
        res = await async_client.post("/auth/register", json={
            "email": "student@test.com",
            "password": "testpassword123",
            "name": "Test Student",
            "role": "student",
        })
        assert res.status_code == 201
        login_res = await async_client.post("/auth/login", json={
            "email": "student@test.com",
            "password": "testpassword123",
        })
        token = login_res.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    @pytest_asyncio.fixture
    async def admin_headers(async_client):
        """Register an admin user and return authorization headers."""
        res = await async_client.post("/auth/register", json={
            "email": "admin@test.com",
            "password": "adminpassword123",
            "name": "Test Admin",
            "role": "admin",
        })
        assert res.status_code == 201
        login_res = await async_client.post("/auth/login", json={
            "email": "admin@test.com",
            "password": "adminpassword123",
        })
        token = login_res.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    @pytest_asyncio.fixture
    async def test_professor(async_client, admin_headers):
        """Create a test professor and return the response."""
        res = await async_client.post(
            "/admin/professors",
            json={
                "name": "Test Prof",
                "topic": "Testing",
                "language": "es",
                "avatar_id": "00000000-0000-0000-0000-000000000000",
                "system_prompt": "You are a test professor.",
            },
            headers=admin_headers,
        )
        assert res.status_code == 200
        return res.json()
    ```

### Step 2: Backend — test_auth.py (comprehensive auth tests)
- **Action:** Write exhaustive auth tests.
- **Files:** `services/backend/tests/test_auth.py`
- **Details:**
  - Test register flow:
    - Register with valid data → 201, response has id, email, name, role, no password.
    - Register with missing fields → 422.
    - Register with weak password (3 chars) → 422.
    - Register with invalid email → 422.
    - Register duplicate email → 409 "Email already registered".
  - Test login flow:
    - Login with correct credentials → 200, response has access_token, refresh_token, token_type="bearer", user object.
    - Login with wrong password → 401.
    - Login with non-existent email → 401.
    - Login with inactive user (set `is_active=False` via DB fixture) → 403.
  - Test token validation:
    - Access protected route without token → 401.
    - Access protected route with invalid token → 401.
    - Access protected route with expired token → 401 with detail containing "expired".
    - Access protected route with malformed token → 401.
  - Test refresh:
    - Refresh with valid token → 200, new access and refresh tokens.
    - Refresh with invalid token → 401.
    - Refresh with revoked token (reuse) → 401, and all user tokens are revoked.
    - Refresh with expired token → 401.
  - Test role enforcement:
    - Student accessing admin endpoint → 403.
    - Admin accessing admin endpoint → 200.
    - Admin accessing student-only endpoint → depends on endpoint, should work unless student-specific checks are in place.
  - Test `/auth/me`:
    - Returns current user data when authenticated.
    - Returns 401 when not authenticated.
  - Test edge cases:
    - Very long password (>128 chars) → 422 or 413.
    - Email with unicode characters → test with valid unicode email.
    - Race condition: two simultaneous register requests for same email — second should get 409 (not a DB constraint violation crash).

### Step 3: Backend — test_rag.py (RAG pipeline tests)
- **Action:** Write tests for the RAG retrieval and indexing pipeline.
- **Files:** `services/backend/tests/test_rag.py`
- **Details:**
  - Mock external services:
    - Mock `AsyncQdrantClient` to return controlled results.
    - Mock `OllamaEmbedding` to return fixed embeddings.
    - Mock `BGELocalReranker` to return identity reranking (no reordering).
  - Test `retrieve_context`:
    - With valid query and existing collection → returns list of `ContextChunk` with text, source_document, score.
    - With query that has no relevant chunks → returns empty list (threshold filter).
    - With query when collection doesn't exist → returns empty list, no crash.
    - With empty query string → returns empty list or raises ValueError.
  - Test `filter_nodes_by_score`:
    - Nodes with score >= threshold pass through.
    - Nodes with score < threshold are filtered out.
    - Empty input → empty output.
    - Mixed scores → only above-threshold returned.
  - Test document indexing (mocked):
    - `ingest_document` processes a text file → chunks upserted to Qdrant, document status becomes "ready".
    - `ingest_document` with unsupported format → status becomes "error" with error_message.
    - `ingest_document` with empty file → status becomes "error" or "ready" with 0 chunks.
    - `delete_document_chunks` removes points from Qdrant and updates document status.
  - Test reindex:
    - Reindex a ready document → status changes to "pending", then "ready" after completion.
    - Reindex a pending document → 409 conflict.
    - Reindex a non-existent document → 404.
  - Test scope check (if implemented as a separate function):
    - In-scope query → returns True.
    - Out-of-scope query → returns False.
    - Borderline query → returns based on threshold.

### Step 4: Backend — test_sessions.py (session and speak tests)
- **Action:** Write tests for session lifecycle and the speak endpoint.
- **Files:** `services/backend/tests/test_sessions.py`
- **Details:**
  - Mock all external services (STT, LLM, RAG, TTS, LiveAvatar, Redis, Langfuse).
  - Test create session:
    - Create with valid student_id and professor_id → 201, session with started_at.
    - Create with non-existent professor → 404.
    - Create with non-existent student → 404.
    - Create with null/empty UUIDs → 422.
  - Test get session history:
    - Get history for existing session → 200, list of messages.
    - Get history for non-existent session → 404.
    - Get history for session with no messages → 200, empty list.
  - Test speak endpoint:
    - Valid audio file → 200, returns audio bytes (or JSON with sources in v2).
    - Missing audio file → 422.
    - Empty audio file → 400 or handled gracefully.
    - Session that has ended → 400 "Session already ended".
    - Non-existent session → 404.
    - Large audio file (>10MB) → 413.
    - Audio in WAV format (supported) → works.
    - Audio in MP3 format (should be supported by Whisper) → works.
  - Test session end:
    - End active session → 200, session.ended_at is set.
    - End already-ended session → 400 or idempotent 200.
    - End non-existent session → 404.
  - Test mock pipeline:
    - Mock STT → returns "test transcript".
    - Mock RAG → returns `[ContextChunk(text="test chunk", source_document="test.pdf", ...)]`.
    - Mock LLM → returns "test response text".
    - Mock TTS → returns b"fake_audio_bytes".
    - Verify the full pipeline executes through all mocked steps.
    - Verify Langfuse is called for each step (or not if disabled).

### Step 5: Backend — test_admin.py (admin CRUD tests)
- **Action:** Write tests for all admin CRUD endpoints with auth.
- **Files:** `services/backend/tests/test_admin.py`
- **Details:**
  - Test professor CRUD:
    - Create professor (admin) → 200, professor with all fields.
    - Create professor without auth → 401.
    - Create professor as student → 403.
    - List professors (admin) → 200, paginated list.
    - List professors without auth → 401.
    - Get professor by ID → 200.
    - Get non-existent professor → 404.
    - Update professor → 200, fields updated.
    - Update non-existent professor → 404.
    - Delete professor → 200, professor no longer listed.
    - Delete non-existent professor → 404.
  - Test document management:
    - Upload document (admin) → 200, document with status "pending".
    - Upload document without auth → 401.
    - Upload document to non-existent professor → 404.
    - Upload document with invalid format (e.g., `.exe`) → 400.
    - Upload document exceeding size limit → 413.
    - List documents for professor → 200.
    - List documents for non-existent professor → 404.
    - Get document chunks → 200 (if ready) or 400 (if not ready).
    - Delete document → 200, document removed.
  - Test indexing status:
    - Get indexing status → 200, with summary and per-collection stats.
    - Get indexing status with no professors → 200, empty collections list.
  - Test admin sessions:
    - List all sessions → 200.
    - Get session details → 200.
    - List sessions with date filter → 200.

### Step 6: Backend — test_health.py (enhanced health tests)
- **Action:** Update existing health tests and add new ones.
- **Files:** `services/backend/tests/test_health.py`
- **Details:**
  - Keep existing tests (basic health, response time).
  - Add tests:
    - Health endpoint returns all service statuses (mocked).
    - Health endpoint when all services are healthy → overall status "healthy".
    - Health endpoint when one service is down (mocked) → overall status "degraded", that service shows "unhealthy" with error.
    - Health endpoint does NOT require auth (verify with no token).
    - Health endpoint returns within 5 seconds even when services are down (use timeouts).
  - Mock the health check functions:

    ```python
    @pytest.mark.asyncio
    async def test_health_one_service_down(async_client, monkeypatch):
        async def mock_check_postgres():
            return {"status": "unhealthy", "error": "connection refused"}
        
        monkeypatch.setattr("routers.health.check_postgres", mock_check_postgres)
        
        response = await async_client.get("/health")
        assert response.status_code == 200  # Health endpoint itself doesn't fail
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["postgres"]["status"] == "unhealthy"
    ```

### Step 7: Set up frontend testing infrastructure
- **Action:** Configure vitest with testing-library and write initial tests.
- **Files:** `services/frontend/vitest.config.ts` (new), `services/frontend/src/__tests__/` (new directory)
- **Details:**

  **`vitest.config.ts`:**
  ```typescript
  import { defineConfig } from 'vitest/config';
  import react from '@vitejs/plugin-react';
  import path from 'path';
  
  export default defineConfig({
    plugins: [react()],
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/__tests__/setup.ts'],
      globals: true,
      coverage: {
        provider: 'v8',
        reporter: ['text', 'json', 'html'],
        exclude: ['node_modules/', '.next/', 'src/__tests__/'],
      },
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
  });
  ```

  **`src/__tests__/setup.ts`:**
  ```typescript
  import '@testing-library/jest-dom';
  ```

  Update `package.json` scripts:
  ```json
  {
    "scripts": {
      "dev": "next dev",
      "build": "next build",
      "start": "next start",
      "test": "vitest run",
      "test:watch": "vitest"
    }
  }
  ```

  Add dependencies to `package.json`:
  ```json
  {
    "devDependencies": {
      "vitest": "^2.0.0",
      "@vitejs/plugin-react": "^4.0.0",
      "@testing-library/react": "^16.0.0",
      "@testing-library/jest-dom": "^6.0.0",
      "@testing-library/user-event": "^14.0.0",
      "jsdom": "^24.0.0"
    }
  }
  ```

### Step 8: Frontend — Write auth and routing tests
- **Action:** Write tests for the auth context, login form, and protected routes.
- **Files:** `services/frontend/src/__tests__/auth.test.tsx`, `services/frontend/src/__tests__/login.test.tsx`, `services/frontend/src/__tests__/ProtectedRoute.test.tsx`
- **Details:**

  **Auth Context tests (`auth.test.tsx`):**
  - Mock `fetch` globally.
  - Test: `AuthProvider` provides default unauthenticated state.
  - Test: `login()` function correctly stores tokens and updates user state.
  - Test: `logout()` clears tokens and resets user state to null.
  - Test: On mount, if token exists in localStorage, calls `/auth/me` and populates user.
  - Test: On mount, if token exists but `/auth/me` returns 401, tries refresh.
  - Test: On mount, if refresh fails, user stays null.

  **Login Form tests (`login.test.tsx`):**
  - Test: Form renders email input, password input, submit button.
  - Test: Submit with empty fields shows validation errors.
  - Test: Submit with invalid email format shows validation error.
  - Test: Submit with valid data calls `login()` API and redirects on success.
  - Test: Submit with wrong credentials shows error message "Email o contraseña incorrectos".
  - Test: Loading state on submit (button disabled, shows spinner).

  **Protected Route tests (`ProtectedRoute.test.tsx`):**
  - Test: When not authenticated, redirects to `/login?redirect=...`.
  - Test: When authenticated but wrong role (student accessing admin), shows 403 page.
  - Test: When authenticated with correct role, renders children.
  - Test: When loading, shows spinner/skeleton, does NOT render children or redirect.

### Step 9: Frontend — Test admin and UI components
- **Action:** Write tests for the admin dashboard and RAG source citation component.
- **Files:** `services/frontend/src/__tests__/admin.test.tsx`, `services/frontend/src/__tests__/SourceCitation.test.tsx`
- **Details:**

  **Admin tests (`admin.test.tsx`):**
  - Test: Admin page renders loading state initially.
  - Test: Admin page shows error state when API fails.
  - Test: Admin page shows professor list when data loads.
  - Test: Create professor form submits correctly.
  - Test: Delete professor shows confirmation dialog.

  **SourceCitation tests (`SourceCitation.test.tsx`):**
  - Test: Renders source names correctly.
  - Test: Clicking "Ver fuentes" expands the list.
  - Test: Shows "Sin fuentes específicas" when sources array is empty.
  - Test: Shows relevance score as a progress bar.
  - Test: Truncates long document names.
  - Test: Shows "(Fuente eliminada)" for deleted sources.

### Step 10: Backend — Test coverage target and CI configuration
- **Action:** Add coverage reporting and verify all tests pass.
- **Files:** `services/backend/pyproject.toml`, `services/backend/.coveragerc` (optional)
- **Details:**
  - Add pytest coverage config to `pyproject.toml`:

    ```toml
    [tool.pytest.ini_options]
    testpaths = ["tests"]
    asyncio_mode = "auto"
    markers = ["asyncio: async test"]

    [tool.coverage.run]
    source = ["services/backend"]
    omit = ["tests/*", "core/database.py"]

    [tool.coverage.report]
    fail_under = 80
    show_missing = true
    ```

  - Add `pytest-cov` to `requirements.txt`.
  - Run: `cd services/backend && pytest --cov=. --cov-report=term-missing`
  - Target: >80% code coverage.
  - Identify any modules below 80% and add missing tests or mark as intentionally uncovered (e.g., `main.py` lifespan is hard to test — can be excluded).

## Acceptance Criteria

- [ ] `cd services/backend && pytest` passes with all tests green.
- [ ] Backend test coverage is >80% (measured by `pytest-cov`).
- [ ] `test_auth.py` covers: register (success, duplicate, weak password), login (success, wrong password, inactive user), protected routes (no token, invalid token, expired token), refresh (success, reuse detection), role enforcement (admin vs student).
- [ ] `test_rag.py` covers: retrieve with context, retrieve without context, out-of-scope query, threshold filtering, document indexing, reindex.
- [ ] `test_sessions.py` covers: create session, speak (valid, invalid, edge cases), get history, end session, mocked pipeline.
- [ ] `test_admin.py` covers: CRUD professors (auth'd and unauth'd), document upload with validation, indexing status, document chunks.
- [ ] `test_health.py` covers: all healthy, one degraded, no auth required.
- [ ] Frontend `vitest` runs with `npm test` and passes.
- [ ] Frontend tests cover: AuthContext, login form validation, ProtectedRoute redirect, SourceCitation component, admin dashboard states.
- [ ] `npm run build` still succeeds.
- [ ] Mock fixtures are clean and don't leak between tests.

## Risks & Notes

- **SQLite vs PostgreSQL:** The test suite uses SQLite (via `aiosqlite`) for speed, but this means PostgreSQL-specific features (enums, array columns, full-text search) are not tested. Add a CI job with a real PostgreSQL test database for comprehensive testing.
- **Mock complexity:** RAG tests require mocking Qdrant, Ollama, and the reranker. Use `unittest.mock` or `monkeypatch` extensively. Consider creating a `mocks.py` module with reusable mock factories.
- **Test isolation:** The `setup_database` fixture drops and recreates all tables between tests. This is slow but safe. For performance, consider switching to transaction rollback isolation (each test runs in its own transaction, rolled back at the end).
- **Frontend testing challenges:** Next.js App Router makes testing tricky because pages rely on server components. Test client components in isolation. Use `vi.mock()` to mock `next/navigation` (useRouter, usePathname, redirect).
- **Async test warnings:** Pytest-asyncio may produce warnings about unclosed event loops. Ensure all async fixtures and tests properly clean up connections.
- **Redis in tests:** If tests interact with Redis, mock it or use `fakeredis` library for a fake Redis implementation.

## Dependencies

- `pytest-asyncio` — already used (async test support)
- `pytest-cov` — coverage reporting (add to requirements.txt)
- `aiosqlite` — for test database
- `httpx` — already used (async test client)
- `unittest.mock` / `monkeypatch` — for mocking external services
- Frontend:
  - `vitest` — test runner
  - `@vitejs/plugin-react` — Vite plugin for React
  - `@testing-library/react` — React component testing
  - `@testing-library/jest-dom` — custom DOM matchers
  - `@testing-library/user-event` — user event simulation
  - `jsdom` — DOM environment for Node.js
