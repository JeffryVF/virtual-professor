import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from core.config import settings
from core.database import engine
from core.middleware import SecurityHeadersMiddleware
from core.rate_limit import limiter
from models.db import Base
from routers import admin, auth, health, professors, sessions
from services import langfuse as langfuse_service

log = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Set up logging: DEBUG in dev, WARNING in production."""
    level = logging.DEBUG if settings.debug else logging.WARNING
    if settings.debug:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            force=True,
        )
    else:
        logging.basicConfig(
            level=level,
            format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            force=True,
        )


# ── Logging ────────────────────────────────────────────────────────────────
_configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Production validation ───────────────────────────────────────────────
    if not settings.debug:
        issues = settings.validate_production()
        for w in issues:
            log.warning("PRODUCTION CONFIG: %s", w)
    else:
        log.info("Debug mode — skipping production config validation")

    if os.environ.get("RENDER"):
        log.warning(
            "Render Free is 512MB RAM. Gemini embeddings are API calls; keep "
            "RERANKER_TYPE=none so the BGE cross-encoder is not loaded."
        )

    # ── Create relational tables (vectors live in Qdrant Cloud) ─────────────
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # ── Seed default admin user ─────────────────────────────────────────────
    from core.database import AsyncSessionLocal
    from services.seed import seed_default_admin

    async with AsyncSessionLocal() as session:
        await seed_default_admin(session)

    # Re-embed leftover documents when source files are still on disk.
    # On Render Free this is off: the filesystem is ephemeral.
    if engine.dialect.name != "sqlite" and settings.embed_resume_on_startup:
        from services.ingestion import resume_incomplete_ingestion

        app.state.resume_ingestion_task = asyncio.create_task(resume_incomplete_ingestion())

    # ── Langfuse init ───────────────────────────────────────────────────────
    langfuse_service.init_langfuse()
    if settings.langfuse_enable:
        try:
            from langfuse.callback import LangfuseCallbackHandler
            from llama_index.core import Settings

            callback_handler = LangfuseCallbackHandler()
            Settings.callback_manager.add_handler(callback_handler)
            log.info("LangfuseCallbackHandler wired to LlamaIndex Settings")
        except Exception as exc:
            log.warning("Failed to wire LangfuseCallbackHandler: %s", exc)

    yield

    # ── Langfuse shutdown ───────────────────────────────────────────────────
    if settings.langfuse_enable:
        await langfuse_service.flush_langfuse()


app = FastAPI(
    title="Virtual Professor API",
    description="AI-powered virtual professor with RAG and local 3D avatar",
    version="0.1.0",
    lifespan=lifespan,
    root_path=settings.root_path,
)

# ── Rate limit exception handler ───────────────────────────────────────────
app.state.limiter = limiter


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a 429 with a Spanish error message and retry info."""
    retry_after = getattr(exc, "retry_after", 60)
    return JSONResponse(
        status_code=429,
        content={
            "error": "Demasiadas solicitudes. Intente de nuevo en {} segundos.".format(
                retry_after
            ),
            "retry_after_seconds": retry_after,
        },
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

# ── CORS middleware (outermost) ────────────────────────────────────────────
origins = settings.cors_origins

if origins == ["*"]:
    log.warning(
        "CORS_ORIGINS is set to '*'. All origins are allowed. "
        "Restrict to specific origins in production."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[],
    max_age=600,
)

# ── Security headers middleware ────────────────────────────────────────────
app.add_middleware(SecurityHeadersMiddleware)

# ── Rate limit middleware ──────────────────────────────────────────────────
app.add_middleware(SlowAPIMiddleware)

# ── Routers ────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(professors.router, prefix="/professors", tags=["professors"])
app.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])


# ── Request logging middleware ───────────────────────────────────────────────

_access_log = logging.getLogger("access")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every HTTP request in structured JSON format."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000

    log_data = {
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "duration_ms": round(elapsed, 2),
        "ip": request.client.host if request.client else "",
        "user_agent": request.headers.get("user-agent", ""),
    }

    user_id = getattr(request.state, "user_id", None)
    if user_id:
        log_data["user_id"] = user_id

    if response.status_code >= 500:
        _access_log.error(json.dumps(log_data, ensure_ascii=False))
    elif response.status_code >= 400:
        _access_log.warning(json.dumps(log_data, ensure_ascii=False))
    else:
        _access_log.info(json.dumps(log_data, ensure_ascii=False))

    return response
