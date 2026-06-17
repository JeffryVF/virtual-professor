# 6. Observability and Error Handling

## Objective

Build a comprehensive observability layer: health check endpoint with per-service status, structured logging, frontend error boundaries, graceful fallbacks for every pipeline step, and an admin status dashboard.

## Prerequisites

- Phase 5 (config/security) complete — logging review done, `DEBUG` env var available
- All services running in Docker Compose
- Langfuse configured (even if disabled)

## Detailed Steps

### Step 1: Backend — Enhanced health check endpoint
- **Action:** Rewrite `GET /health` to probe every dependent service and return detailed status.
- **Files:** `services/backend/routers/health.py` (new), `services/backend/main.py`
- **Details:**

  **`health.py`:**
  ```python
  import asyncio
  import logging
  from datetime import datetime
  from typing import Any
  
  import httpx
  from fastapi import APIRouter, HTTPException
  from redis.asyncio import Redis
  from sqlalchemy import text
  from qdrant_client import AsyncQdrantClient
  
  from core.config import settings
  from core.database import AsyncSessionLocal
  
  router = APIRouter(tags=["health"])
  log = logging.getLogger(__name__)
  
  class ServiceStatus:
      def __init__(self, name: str):
          self.name = name
          self.status = "unknown"
          self.latency_ms: float | None = None
          self.error: str | None = None
          self.checked_at: str | None = None
  
  async def check_postgres() -> dict[str, Any]:
      start = asyncio.get_event_loop().time()
      try:
          async with AsyncSessionLocal() as session:
              await session.execute(text("SELECT 1"))
          latency = (asyncio.get_event_loop().time() - start) * 1000
          return {"status": "healthy", "latency_ms": round(latency, 2)}
      except Exception as e:
          return {"status": "unhealthy", "error": str(e)}
  
  async def check_redis() -> dict[str, Any]:
      start = asyncio.get_event_loop().time()
      try:
          r = Redis.from_url(settings.redis_url)
          await r.ping()
          await r.aclose()
          latency = (asyncio.get_event_loop().time() - start) * 1000
          return {"status": "healthy", "latency_ms": round(latency, 2)}
      except Exception as e:
          return {"status": "unhealthy", "error": str(e)}
  
  async def check_qdrant() -> dict[str, Any]:
      start = asyncio.get_event_loop().time()
      try:
          client = AsyncQdrantClient(url=settings.qdrant_url)
          await client.get_collections()
          latency = (asyncio.get_event_loop().time() - start) * 1000
          return {"status": "healthy", "latency_ms": round(latency, 2)}
      except Exception as e:
          return {"status": "unhealthy", "error": str(e)}
  
  async def check_ollama() -> dict[str, Any]:
      start = asyncio.get_event_loop().time()
      try:
          async with httpx.AsyncClient(timeout=5.0) as client:
              resp = await client.get(f"{settings.ollama_url}/api/tags")
              resp.raise_for_status()
          latency = (asyncio.get_event_loop().time() - start) * 1000
          return {"status": "healthy", "latency_ms": round(latency, 2)}
      except Exception as e:
          return {"status": "unhealthy", "error": str(e)}
  
  async def check_kokoro() -> dict[str, Any]:
      start = asyncio.get_event_loop().time()
      try:
          async with httpx.AsyncClient(timeout=5.0) as client:
              resp = await client.get(f"{settings.kokoro_url}/health")
              resp.raise_for_status()
          latency = (asyncio.get_event_loop().time() - start) * 1000
          return {"status": "healthy", "latency_ms": round(latency, 2)}
      except Exception as e:
          return {"status": "unhealthy", "error": str(e)}
  
  @router.get("/health")
  async def health():
      checks = {
          "postgres": check_postgres(),
          "redis": check_redis(),
          "qdrant": check_qdrant(),
          "ollama": check_ollama(),
          "kokoro": check_kokoro(),
      }
      results = {}
      overall = "healthy"
      for name, coro in checks.items():
          try:
              results[name] = await coro
              if results[name]["status"] != "healthy":
                  overall = "degraded"
          except Exception as e:
              results[name] = {"status": "unhealthy", "error": str(e)}
              overall = "degraded"
      
      return {
          "status": overall,
          "timestamp": datetime.utcnow().isoformat(),
          "services": results,
          "version": settings.langfuse_release or "0.1.0",
      }
  ```

  - All probes have a 5-second timeout. If a service is unreachable, it returns "unhealthy" rather than crashing the health endpoint.
  - The health endpoint does NOT require auth (it's used by Docker healthchecks and load balancers).
  - In `main.py`: replace the existing `@app.get("/health")` with `app.include_router(health.router)`.
  - Remove the old inline `health()` function.

### Step 2: Frontend — ErrorBoundary component
- **Action:** Create a React error boundary for route-level error handling.
- **Files:** `services/frontend/src/components/ErrorBoundary.tsx` (new)
- **Details:**
  - Class component implementing `componentDidCatch`.
  - Props: `fallback?: ReactNode`, `onError?: (error: Error, info: React.ErrorInfo) => void`
  - Default fallback UI:
    - Centered card with an error icon (from `lucide-react`: `AlertTriangle`).
    - Title: "Algo salió mal"
    - Description: "Ocurrió un error inesperado. Por favor intenta de nuevo."
    - "Reintentar" button that calls `this.setState({ hasError: false })` to retry rendering.
    - If in development mode (`process.env.NODE_ENV === 'development'`), show the error stack trace in a collapsible `<details>` block.
  - Log errors to console in development, and to an analytics endpoint in production (future).
  - Wrap each route page with `<ErrorBoundary>` in the layout or page components.
  - For the admin section, wrap with `ErrorBoundary` in the admin layout.

### Step 3: Frontend — Global error handler for API calls
- **Action:** Create a centralized error handler that parses API errors and shows user-friendly messages.
- **Files:** `services/frontend/src/lib/error-handler.ts` (new), `services/frontend/src/lib/api.ts`
- **Details:**

  **`error-handler.ts`:**
  ```typescript
  import { toast } from 'sonner';
  
  export interface ApiError {
    status: number;
    detail: string;
    error_code?: string;
    retry_after?: number;
  }
  
  export function parseApiError(error: unknown): ApiError {
    if (error instanceof Response) {
      // Handle Response object directly
      return {
        status: error.status,
        detail: `Error del servidor (${error.status})`,
      };
    }
    
    if (error instanceof TypeError && error.message === 'Failed to fetch') {
      return {
        status: 0,
        detail: 'No se pudo conectar con el servidor. Verifica tu conexión.',
        error_code: 'NETWORK_ERROR',
      };
    }
    
    if (error instanceof Error) {
      // Try to parse JSON error bodies
      try {
        const parsed = JSON.parse(error.message);
        if (parsed.detail) {
          return {
            status: parsed.status_code || 500,
            detail: parsed.detail,
            error_code: parsed.error_code,
            retry_after: parsed.retry_after_seconds,
          };
        }
      } catch {
        // Not JSON — use the raw message
      }
      
      // Map HTTP status codes to user-friendly messages
      const statusCode = parseInt(error.message.substring(0, 3));
      const statusMessages: Record<number, string> = {
        400: 'Solicitud inválida. Revisa los datos ingresados.',
        401: 'Tu sesión ha expirado. Inicia sesión de nuevo.',
        403: 'No tienes permiso para realizar esta acción.',
        404: 'El recurso solicitado no fue encontrado.',
        409: 'Ya existe un registro con esos datos.',
        413: 'El archivo es demasiado grande.',
        422: 'Datos inválidos. Revisa los campos marcados.',
        429: 'Demasiadas solicitudes. Intenta de nuevo en un momento.',
        500: 'Error interno del servidor. Intenta de nuevo más tarde.',
        502: 'El servidor no está disponible momentáneamente.',
        503: 'El servicio está temporalmente fuera de línea.',
      };
      
      return {
        status: isNaN(statusCode) ? 500 : statusCode,
        detail: statusMessages[statusCode] || error.message || 'Error desconocido',
      };
    }
    
    return {
      status: 500,
      detail: 'Error inesperado. Intenta de nuevo.',
    };
  }
  
  export function handleApiError(error: unknown, options?: { silent?: boolean }): ApiError {
    const parsed = parseApiError(error);
    
    if (!options?.silent) {
      // Don't show toast for 401 — handled by auth redirect
      if (parsed.status !== 401) {
        toast.error(parsed.detail);
      }
    }
    
    return parsed;
  }
  ```

  - Update `api.ts` to use `handleApiError` in the existing `request()` function and the new auth-aware client.
  - Remove the old `throw new Error(\`${res.status} ${text}\`)` pattern and replace with structured error handling.

### Step 4: Backend — Structured logging
- **Action:** Replace basic logging with structured JSON logging for better log aggregation.
- **Files:** `services/backend/main.py`, `services/backend/core/config.py`
- **Details:**
  - Implement a structured logging middleware:

    ```python
    import json
    import logging
    import time
    from starlette.middleware.base import BaseHTTPMiddleware
    
    class StructuredLoggingMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            start = time.time()
            response = await call_next(request)
            duration_ms = (time.time() - start) * 1000
            
            log_data = {
                "timestamp": datetime.utcnow().isoformat(),
                "service": "backend",
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
                "content_length": response.headers.get("content-length"),
            }
            
            # Add user_id if authenticated (extracted from request state)
            if hasattr(request.state, "user_id"):
                log_data["user_id"] = request.state.user_id
            
            # Determine log level by status code
            if response.status_code >= 500:
                logging.error(json.dumps(log_data))
            elif response.status_code >= 400:
                logging.warning(json.dumps(log_data))
            else:
                logging.info(json.dumps(log_data))
            
            return response
    ```

  - Update `basicConfig` in `main.py` to output JSON format when `DEBUG=false`:

    ```python
    if not settings.debug:
        logging.basicConfig(
            level=logging.INFO,
            format='{"timestamp":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","message":"%(message)s"}',
            datefmt='%Y-%m-%dT%H:%M:%S',
        )
    ```

  - Set `user_id` on `request.state` in the `get_current_user` auth dependency.
  - Add request ID: generate a `uuid4` per request and include it in logs and response headers (`X-Request-ID`). Use a middleware or a `request_id` dependency.

### Step 5: Admin status dashboard
- **Action:** Build a frontend admin page that displays the health check results in a live dashboard.
- **Files:** `services/frontend/src/app/admin/status/page.tsx` (new)
- **Details:**
  - Route: `/admin/status` (protected by AdminRoute from Phase 3 admin layout).
  - On mount, fetch `GET /health`.
  - Display:
    - Overall status: large green "Sistema Saludable" badge or red "Sistema Degradado" badge.
    - Last checked timestamp.
    - Card grid, one per service, each showing:
      - Service name (e.g., "PostgreSQL")
      - Status indicator: green dot ("Healthy"), red dot ("Unhealthy"), yellow dot ("Degraded").
      - Latency in ms (green < 100ms, yellow < 500ms, red > 500ms).
      - Error message (if unhealthy) in red italic text.
    - Auto-refresh toggle: checkbox "Auto-refresh (30s)". When enabled, polls every 30 seconds.
    - Manual refresh button.
  - Loading state: skeleton cards while fetching.
  - Error state: "No se pudo obtener el estado de los servicios" with retry button.
  - Add a link to this page in the admin navigation sidebar.

### Step 6: Verify Langfuse pipeline tracking
- **Action:** Audit the existing Langfuse integration to ensure every pipeline step is tracked.
- **Files:** `services/backend/services/langfuse.py`, `services/backend/routers/sessions.py`, `services/backend/services/rag.py`, `services/backend/services/llm.py`, `services/backend/services/stt.py`, `services/backend/services/tts.py`
- **Details:**
  - Review the current Langfuse trace in the `/speak` endpoint (`sessions.py`). The pipeline steps in order:
    1. STT (Whisper) — transcription
    2. Scope check (LLM)
    3. RAG (Qdrant retrieval)
    4. LLM response generation
    5. TTS (Kokoro)
    6. LiveAvatar session
  - Verify each step creates a Langfuse span with:
    - `name`: descriptive (e.g., `stt_transcribe`, `scope_check`, `rag_retrieve`, `llm_generate`, `tts_synthesize`, `avatar_send`)
    - `input`: the data going into the step (transcript text, query, context, LLM response text)
    - `output`: the data coming out (transcript, chunks, response text, audio duration)
    - `duration`: execution time
    - `status`: success/failure with error details
  - If a step is missing, add it. The goal is to be able to see in the Langfuse dashboard the full end-to-end trace of every student interaction.
  - Ensure the trace includes `session_id`, `student_id`, `professor_id`, and `professor_name` as tags or metadata for filtering.
  - Add a `metadata` field to each span with environment info (`langfuse_release`) for version tracking.

### Step 7: Graceful fallbacks for every pipeline step
- **Action:** Ensure the `/speak` pipeline handles failures gracefully at every stage.
- **Files:** `services/backend/routers/sessions.py`
- **Details:**
  - Define fallback behavior per step:
    - **STT failure** (Whisper timeout/unavailable):
      - Log error.
      - Return 503 with `{"detail": "No se pudo capturar el audio. Intenta de nuevo.", "step": "stt"}`.
      - Langfuse: mark STT span as failed.
    - **Scope check failure** (LLM timeout):
      - Default to "in scope" — assume the question is valid rather than blocking the student.
      - Log warning.
      - Langfuse: mark scope span as warning.
    - **RAG failure** (Qdrant timeout/unavailable):
      - Log error.
      - Fallback to LLM-only response (no context). Add a prefix to the LLM prompt: "Note: the knowledge base is currently unavailable. Answer based on your general knowledge."
      - Include `"rag_available": false` in the response metadata.
      - Langfuse: mark RAG span as failed, note that fallback was used.
    - **LLM timeout** (Ollama unresponsive):
      - Return a static response: "El profesor está pensando... Por favor, intenta de nuevo en unos segundos."
      - Return 503 with `{"detail": "El profesor está pensando...", "step": "llm"}`.
      - Langfuse: mark LLM span as failed.
    - **TTS failure** (Kokoro unresponsive):
      - Fallback to text-only response. Return JSON with `{"text": response_text, "audio": null}`.
      - The LiveAvatar SDK can display text as subtitles without audio.
      - Log warning.
      - Langfuse: mark TTS span as failed, note that text-only fallback was used.
    - **Avatar failure** (LiveAvatar connection lost):
      - This happens client-side (WebRTC). The backend is not involved beyond providing the connection token.
      - Frontend: if LiveAvatar Web SDK fails to connect, show a fallback UI with text-only interaction (type your question, read the response).
      - Note: this fallback is a significant UX change and may be deferred to a later phase.
  - Wrap each pipeline step in try/except and route to the appropriate fallback.
  - The langfuse trace should capture which fallback was used for observability.

## Acceptance Criteria

- [ ] `GET /health` returns detailed JSON with per-service status, latency, and overall health state.
- [ ] Health endpoint does NOT require authentication.
- [ ] `ErrorBoundary` component catches React errors and shows friendly UI with retry button.
- [ ] API error handler shows user-friendly toast messages (never raw "500 Internal Server Error").
- [ ] Structured logging middleware logs every request in JSON format with method, path, status, duration, and user_id.
- [ ] `/admin/status` page displays health check results with auto-refresh option.
- [ ] Langfuse traces include all pipeline steps (STT, scope, RAG, LLM, TTS, avatar) with proper span names and metadata.
- [ ] Each pipeline step has a graceful fallback defined and tested:
  - STT failure → "No se pudo capturar audio"
  - RAG failure → LLM-only fallback
  - LLM timeout → "El profesor está pensando..."
  - TTS failure → text-only response
- [ ] `cd services/backend && pytest` passes.
- [ ] `npm run build` succeeds.

## Risks & Notes

- **Health endpoint timeout:** With 5 services to check and a 5-second timeout each, the health endpoint could take up to 25 seconds. Run all checks concurrently with `asyncio.gather(return_exceptions=True)`. The implementation above does this.
- **Redis connection leak:** The health check opens and closes a Redis connection each time. Use a connection pool or the existing Redis client singleton if available.
- **Cascade failures:** If one service is down (e.g., Whisper), the entire `/speak` pipeline fails. The fallbacks ensure partial functionality. However, the student experience degrades significantly. Monitor fallback rates in Langfuse to detect chronic issues.
- **ErrorBoundary in production:** Error boundaries don't catch errors in event handlers, async code (setTimeout), or server-side rendering. For SSR errors, Next.js provides `error.tsx` and `global-error.tsx` conventions. Use these as well.
- **Logging performance:** JSON logging adds minimal overhead. The real cost is the middleware running on every request. Keep middleware logic lean (no DB calls, no heavy serialization).

## Dependencies

- `redis[asyncio]` — already in requirements.txt for async Redis client
- `httpx` — already in requirements.txt for async HTTP calls
- Langfuse SDK — already in requirements.txt
- No new npm packages (lucide-react already in package.json for icons)
- Phase 5 (config) — `DEBUG` env var to toggle between human-readable and JSON logging
