import logging
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
from routers import admin, auth, professors, sessions
from services import langfuse as langfuse_service

log = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Set up logging: DEBUG in dev, WARNING in production."""
    level = logging.DEBUG if settings.debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
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

    # ── Create tables ───────────────────────────────────────────────────────
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
    description="AI-powered virtual professor with RAG and LiveAvatar integration",
    version="0.1.0",
    lifespan=lifespan,
    root_path="/api",
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
app.include_router(professors.router, prefix="/professors", tags=["professors"])
app.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
