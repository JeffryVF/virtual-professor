import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import engine
from models.db import Base
from routers import admin, professors, sessions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="Virtual Professor API",
    description="AI-powered virtual professor with RAG and LiveAvatar integration",
    version="0.1.0",
    lifespan=lifespan,
    root_path="/api",
)

origins = [o.strip() for o in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins != ["*"] else ["*"],
    allow_credentials=False if origins == ["*"] else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(professors.router, prefix="/professors", tags=["professors"])
app.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
