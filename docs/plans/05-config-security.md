# 5. Configuration Hardening and Security

## Objective

Harden the application configuration and infrastructure: validate all environment variables at startup, remove hardcoded secrets, add CORS and security headers, enforce rate limiting, create proper Docker Compose profiles for dev and prod, and ensure logging never leaks sensitive data.

## Prerequisites

- Phase 2 (backend auth) complete — JWT auth working, `ADMIN_API_KEY` still present for backward compat
- Phase 3 (frontend auth) complete — `NEXT_PUBLIC_ADMIN_KEY` usage deprecated
- All services running and tested with `docker compose`

## Detailed Steps

### Step 1: Review and harden .env.example
- **Action:** Audit every environment variable: ensure it has a description, a non-default placeholder where appropriate, and is actually used.
- **Files:** `.env.example`
- **Details:**
  - Add descriptions for every section, not just section headers.
  - For secrets (`POSTGRES_PASSWORD`, `ADMIN_API_KEY`, `LIVEAVATAR_API_KEY`, `JWT_SECRET_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`): replace defaults with `changeme` or `your_key_here`. Never ship real credentials.
  - Add missing vars discovered during audit:
    - `JWT_SECRET_KEY` (from Phase 2) — with `openssl rand -hex 32` generation hint.
    - `JWT_ALGORITHM`, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `JWT_REFRESH_TOKEN_EXPIRE_DAYS`.
    - `LANGFUSE_POSTGRES_PASSWORD` — currently has a default `changeme` in compose but is not in `.env.example`.
    - `LANGFUSE_NEXTAUTH_SECRET`, `LANGFUSE_SALT`, `LANGFUSE_ENCRYPTION_KEY` — these are used in `docker-compose.yml` with defaults but not documented in `.env.example`.
    - `RAG_RETRIEVAL_TOP_K` — already present, verify correct.
    - `UPLOAD_MAX_SIZE_MB`, `UPLOAD_MAX_PAGES`, `UPLOAD_ALLOWED_FORMATS` — add to `.env.example` (they're in settings.py but not in `.env.example`).
  - Group vars logically with clear section headers. Current grouping is good but add:
    - `# ── Authentication ──` section with JWT vars.
    - `# ── File Upload ──` section with upload limit vars.
    - `# ── Langfuse (Observability) ──` — expand the existing section with all 5+ Langfuse vars.
  - Remove any vars that are no longer used (e.g., if `NEXT_PUBLIC_ADMIN_KEY` is fully removed in this phase).
  - **Critical:** Ensure `CORS_ORIGINS` defaults to `*` in `.env.example` but with a STRONG warning comment that this must be locked down in production.

### Step 2: Add startup validation in settings.py
- **Action:** Make the FastAPI app fail fast at startup if required env vars are missing.
- **Files:** `services/backend/core/config.py`
- **Details:**
  - `pydantic-settings` already validates types and required fields (fields without defaults).
  - Add a `validate_production()` method that checks additional constraints:

    ```python
    def validate_production(self):
        """Check production-critical constraints. Called at startup via lifespan."""
        warnings = []
        if self.jwt_secret_key in ("", "changeme", "your_key_here"):
            warnings.append("JWT_SECRET_KEY is not set to a secure value")
        if self.admin_api_key in ("", "changeme"):
            warnings.append("ADMIN_API_KEY is using the default value")
        if self.cors_origins == "*":
            warnings.append("CORS_ORIGINS is set to '*' — restrict in production")
        if not self.langfuse_enable:
            warnings.append("Langfuse observability is disabled")
        if self.liveavatar_api_key in ("", "your_key_here"):
            raise ValueError("LIVEAVATAR_API_KEY must be set")
        return warnings
    ```

  - Call `validate_production()` in the `lifespan` function and log all warnings at `WARNING` level.
  - For missing critical keys (like `JWT_SECRET_KEY`), raise a `RuntimeError` to prevent startup.
  - Add the new settings fields (JWT-related) to the `Settings` class.

### Step 3: Remove NEXT_PUBLIC_ADMIN_KEY from frontend
- **Action:** Eliminate the hardcoded admin API key from the frontend code and build configuration.
- **Files:** `services/frontend/src/lib/api.ts`, `docker-compose.yml` (frontend environment), `services/frontend/Dockerfile.prod`, `services/frontend/Dockerfile`, `.env.example`
- **Details:**
  - In `api.ts`:
    - Remove `const ADMIN_KEY = process.env.NEXT_PUBLIC_ADMIN_KEY ?? 'changeme'` line.
    - Remove `'X-Admin-Key': ADMIN_KEY` from the default headers in `request()`.
    - The existing `request()` function (used by admin endpoints) must now use JWT Bearer tokens. For any admin call that doesn't have an auth-aware replacement yet, update it.
    - **Fallback:** If the backend still supports `X-Admin-Key` (backward compat from Phase 2), keep the header but make it dynamic (read from a cookie or localStorage). Remove completely in the next cycle.
  - In `docker-compose.yml`: remove `NEXT_PUBLIC_ADMIN_KEY=${ADMIN_API_KEY}` from the frontend service environment.
  - In `Dockerfile.prod` and `Dockerfile` (dev): remove any build args related to `NEXT_PUBLIC_ADMIN_KEY`.
  - In `.env.example`: remove `NEXT_PUBLIC_ADMIN_KEY` if present, or add a note that it's deprecated.
  - In `next.config.ts`: verify no references to `ADMIN_KEY` or `NEXT_PUBLIC_ADMIN_KEY`.

### Step 4: Security headers via Starlette middleware and nginx
- **Action:** Add security headers at both the application level (backend) and the reverse proxy level (nginx) for defense in depth.
- **Files:** `services/backend/main.py`, `config/nginx.conf`
- **Details:**

  **Backend (Starlette middleware):**
  - Add `SecurityHeadersMiddleware` or use `starlette.middleware.base.BaseHTTPMiddleware`:

    ```python
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response: Response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            # Only add CSP in production (dev needs inline styles for hot reload)
            if not settings.debug:
                response.headers["Content-Security-Policy"] = (
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                    "style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data: blob:; "
                    "connect-src 'self' https://api.liveavatar.com wss://*.livekit.cloud; "
                    "media-src 'self' blob:; "
                    "font-src 'self' data:; "
                    "frame-ancestors 'none';"
                )
            return response
    ```

  - Register the middleware after CORS middleware in `main.py`.
  - Add a `debug: bool = False` setting to `Settings` (from env `DEBUG`) to control CSP strictness.

  **nginx:**
  - The existing `config/nginx.conf` has `X-Frame-Options` and `X-Content-Type-Options`. Add:
    - `X-XSS-Protection: 1; mode=block`
    - `Strict-Transport-Security: max-age=63072000; includeSubDomains` (only when HTTPS is terminated)
    - `Permissions-Policy: camera=(self), microphone=(self)`
  - Note: nginx security headers are a backup. The primary should be the backend, since not all traffic goes through nginx in dev.

### Step 5: Add CORS middleware with explicit origins
- **Action:** Replace the current `allow_origins=["*"]` with proper origin validation.
- **Files:** `services/backend/main.py`
- **Details:**
  - Current code: `allow_origins=origins if origins != ["*"] else ["*"]` — this is correct but incomplete.
  - Add validation: if `CORS_ORIGINS` is `*` in production (detected by `DEBUG=false`), log a warning.
  - For production, require explicit origins (comma-separated in env var).
  - Add `allow_credentials=True` when origins are specific (not `*`).
  - Add CORS preflight cache: `Access-Control-Max-Age: 600` (10 minutes).
  - Read `cors_origins` as a list directly from pydantic-settings instead of splitting a string:

    ```python
    # In Settings class:
    cors_origins: list[str] = ["*"]
    ```

### Step 6: Add rate limiting on auth endpoints
- **Action:** Use `slowapi` to limit login attempts and protect against brute force.
- **Files:** `services/backend/routers/auth.py`, `services/backend/main.py`, `services/backend/requirements.txt`
- **Details:**
  - Add `slowapi>=0.1.9` to `requirements.txt`.
  - Configure slowapi in `main.py`:

    ```python
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    ```

  - Apply rate limit to auth router:

    ```python
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    
    limiter = Limiter(key_func=get_remote_address)
    
    @router.post("/login")
    @limiter.limit("5/minute")
    async def login(request: Request, ...):
        ...
    ```

  - Apply a stricter limit on `/auth/refresh`: `3/minute` (refresh abuse is a stronger signal).
  - Apply a moderate limit on `/auth/register`: `2/minute` per IP (prevent mass account creation).
  - In production behind nginx, the rate limiter sees the nginx IP, not the client IP. Configure nginx to forward the real IP via `X-Forwarded-For` header, and configure slowapi to read from that header:

    ```python
    limiter = Limiter(
        key_func=lambda: request.headers.get("X-Forwarded-For", request.client.host)
    )
    ```

  - Return a standardized 429 response:

    ```json
    {
      "detail": "Demasiadas solicitudes. Intenta de nuevo en 60 segundos.",
      "retry_after_seconds": 60
    }
    ```

### Step 7: Enforce file upload limits server-side
- **Action:** Verify and harden upload validation already in place.
- **Files:** `services/backend/routers/admin.py`, `services/backend/core/config.py`
- **Details:**
  - The existing `validate_upload_file` function checks: extension, MIME type magic bytes, and file size. Review it for completeness:
    - Extension check: exists, good.
    - MIME check: exists, but only for pdf/docx/pptx. For other formats (mp3, mp4, url, csv, json, txt), magic bytes may not be reliable. Add a log warning for formats without MIME validation.
    - File size check: exists (max_size_mb from settings).
  - Add a check for total storage per professor: reject upload if the professor's total document count exceeds a limit (e.g., 100 documents per professor). Configurable via `PROFESSOR_MAX_DOCUMENTS` env var.
  - Add a check for concurrent uploads: if a professor already has a document with status "processing", reject new uploads with 429 "Upload already in progress".
  - The nginx `client_max_body_size` is already set to 500M. Ensure the backend limit (`upload_max_size_mb: 50`) is lower than the nginx limit.

### Step 8: Create docker-compose.override.yml (dev)
- **Action:** The file already exists. Review and polish it.
- **Files:** `docker-compose.override.yml`
- **Details:**
  - Current file: exposes ports for all services, mounts code volumes, enables `--reload` for backend.
  - Add: `NEXT_PUBLIC_API_URL=http://localhost:8000` in frontend environment (overrides the compose default `/api` for direct access without nginx in dev).
  - Add: a `profiles:` section for services that are optional in dev (like Langfuse — not everyone needs observability during development).
  - Add: environment variable `DEBUG=true` for backend in dev mode.
  - Add: `stdin_open: true` and `tty: true` for backend for debugging with pdb.
  - Keep the existing `node_modules` named volume for frontend.
  - Document in a comment at the top that this file is auto-applied with `docker compose up` and can be disabled with `--profile` flags.

### Step 9: Create docker-compose.prod.yml template
- **Action:** Write a production Docker Compose file with appropriate settings.
- **Files:** `docker-compose.prod.yml` (new)
- **Details:**
  - Base it on `docker-compose.yml` but with these overrides:
    - **No port exposure** for internal services (whisper, qdrant, kokoro, postgres, redis, langfuse) — they should only be accessible within the Docker network.
    - **Resource limits** for every service:
      ```yaml
      deploy:
        resources:
          limits:
            cpus: '2'
            memory: 4G
          reservations:
            cpus: '0.5'
            memory: 1G
      ```
    - **restart: always** — already present in base compose.
    - **Healthchecks** — already present for backend, postgres, langfuse-postgres. Add healthchecks for all services:
      - `nginx`: `curl -f http://localhost/health`
      - `frontend`: `curl -f http://localhost:3000`
      - `redis`: `redis-cli ping`
      - `qdrant`: `curl -f http://localhost:6333/health`
      - `kokoro`: `curl -f http://localhost:8880/health`
      - `whisper`: `curl -f http://localhost:9000/health`
    - **depends_on** with `condition: service_healthy` for all dependencies (e.g., backend depends on postgres being healthy, not just started).
    - **Logging** configuration:
      ```yaml
      logging:
        driver: "json-file"
        options:
          max-size: "10m"
          max-file: "3"
      ```
    - **Networks:** already separated via `app-network`.
    - **Security options:** `no-new-privileges: true` for all services.
    - **Read-only root filesystem** where possible (not for services that write to disk).
    - **Secrets:** instead of env file, use Docker secrets for sensitive values:
      ```yaml
      secrets:
        jwt_secret:
          file: ./secrets/jwt_secret.txt
        postgres_password:
          file: ./secrets/postgres_password.txt
      ```
      Note: this requires restructuring how the backend reads secrets. For v1, keep using `.env` with restricted permissions but document the Docker secrets approach as a future improvement.

### Step 10: Audit logging for sensitive data
- **Action:** Ensure no logger statement dumps passwords, tokens, or personal data.
- **Files:** All Python files in `services/backend/` and `services/kokoro/`
- **Details:**
  - Search for `logging` or `log.` calls and review each one:
    - Passwords: any `log.info(f"...{password}...")` → redact. Use `"****"` instead.
    - Tokens: any log of raw JWT or refresh tokens → redact or truncate: `f"...{token[:8]}...{token[-4:]}"`.
    - API keys: any log of `ADMIN_API_KEY`, `LIVEAVATAR_API_KEY`, `LANGFUSE_SECRET_KEY` → redact.
    - Personal data (email, name): in dev logs it's acceptable with caution. In production, consider GDPR compliance — log only if necessary, with user consent.
  - Add a helper function:

    ```python
    def mask_sensitive(value: str, visible_chars: int = 4) -> str:
        if not value:
            return ""
        if len(value) <= visible_chars * 2:
            return "****"
        return value[:visible_chars] + "..." + value[-visible_chars:]
    ```

  - Check `langfuse.py` — ensure Langfuse trace names/inputs don't include raw audio data (should only be transcript text).
  - Review `liveavatar.py` — ensure no logging of `LIVEAVATAR_API_KEY`.
  - Review `ingestion.py` — ensure no logging of raw file contents (chunk text is OK, but full file contents are not).
  - In `services/backend/main.py`, the basicConfig sets `level=logging.INFO`. In production, change to `WARNING` or use structured logging.

## Acceptance Criteria

- [ ] `.env.example` has all env vars documented with descriptions, grouped by section, no default secrets.
- [ ] Backend fails at startup with clear error if `JWT_SECRET_KEY`, `LIVEAVATAR_API_KEY`, or `DATABASE_URL` are missing/invalid.
- [ ] `NEXT_PUBLIC_ADMIN_KEY` references completely removed from frontend code, Dockerfiles, and compose.
- [ ] CORS middleware validates origins and rejects unauthorized origins in production mode.
- [ ] Security headers (`X-Content-Type-Options`, `X-Frame-Options`, `CSP`, `HSTS`) present on all responses.
- [ ] Rate limiting: `POST /auth/login` limited to 5 req/min, `/auth/register` to 2 req/min, `/auth/refresh` to 3 req/min.
- [ ] File upload validation is complete: extension, MIME, size, concurrent upload prevention.
- [ ] `docker-compose.override.yml` has proper dev overrides (ports, volumes, reload, debug).
- [ ] `docker-compose.prod.yml` has resource limits, healthchecks, logging config, and no dev ports.
- [ ] No logger in the codebase dumps passwords, tokens, API keys, or raw file contents.
- [ ] `cd services/backend && pytest` passes after all changes.
- [ ] `docker compose up -d` starts successfully.

## Risks & Notes

- **CSP in dev:** Content-Security-Policy breaks Next.js hot-reload (which uses inline scripts and eval). Only add CSP headers in production mode or with a `DEBUG=false` check.
- **Rate limiting behind nginx:** Slowapi by default reads the request's `client.host`, which is always the nginx container IP when behind the proxy. Configure slowapi to read `X-Forwarded-For` header and ensure nginx is configured to set it correctly (already in nginx.conf).
- **Docker secrets migration:** Moving from `.env` to Docker secrets is a significant refactor. For v1, keep `.env` but document the migration path. Add a comment in `docker-compose.prod.yml` about secrets.
- **Upload validation false positives:** The MIME type check for docx/pptx may not catch all edge cases (e.g., LibreOffice files vs Microsoft Office files). Test with real files from different sources. Consider adding a "strict" mode that can be disabled per deployment.
- **Backward compat with X-Admin-Key:** This phase removes the frontend usage of `X-Admin-Key`, but the backend fallback from Phase 2 is still active. The full removal of the backend fallback comes in a later phase.

## Dependencies

- `slowapi>=0.1.9` — rate limiting middleware
- No new npm packages
- Phase 2 (backend auth) — `X-Admin-Key` deprecation path, JWT config vars
- Phase 3 (frontend auth) — `NEXT_PUBLIC_ADMIN_KEY` removal depends on all admin flows using JWT
