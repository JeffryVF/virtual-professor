import json
import logging

from pydantic import field_validator
from pydantic_settings import BaseSettings

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Debug
    debug: bool = False

    # Database
    database_url: str

    # FastAPI root path. Use "/api" behind nginx; leave empty on Render.
    root_path: str = ""

    # Uploaded documents (mount a Render disk here in production)
    upload_dir: str = "/app/uploads"

    # Redis
    redis_url: str

    # Z.AI (GLM) — OpenAI-compatible API, no local LLM process
    # Docs: https://docs.z.ai/guides/llm/glm-5
    # Free models: glm-4.7-flash, glm-4.5-flash
    # Paid: glm-5 ($1/$3.2 per 1M tokens)
    zai_api_key: str = ""
    zai_base_url: str = "https://api.z.ai/api/paas/v4"
    zai_llm_model: str = "glm-4.7-flash"
    zai_fallback_llm_model: str = "glm-4.5-flash"
    llm_max_tokens: int = 350  # max tokens per LLM response (env: LLM_MAX_TOKENS)

    # Cloudflare AI Search (managed RAG: chunking, embeddings, retrieval)
    # Docs: https://developers.cloudflare.com/ai-search/
    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    cloudflare_ai_search_instance: str = ""
    cloudflare_timeout_seconds: float = 60.0
    # Re-upload pending documents to Cloudflare on boot.
    embed_resume_on_startup: bool = True

    # Edge-TTS — free neural TTS (Microsoft), no local model/service
    edge_tts_voice_en: str = "en-US-JennyNeural"
    edge_tts_voice_es: str = "es-ES-ElviraNeural"
    edge_tts_rate: str = "+0%"
    tts_max_total_chars: int = 6000  # max total chars to synthesize — longer text is truncated gracefully

    # Admin
    admin_api_key: str

    # Default admin user — seeded on startup if ADMIN_EMAIL/ADMIN_PASSWORD are set
    admin_email: str = ""
    admin_password: str = ""
    admin_name: str = "Administrator"

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # Session settings
    session_memory_messages: int = 10
    session_memory_max_tokens: int = 4096
    session_timeout_minutes: int = 30

    # RAG (Cloudflare AI Search)
    rag_min_relevance_score: float
    rag_retrieval_top_k: int = 8  # env: RAG_RETRIEVAL_TOP_K (max 50)

    # Upload validation — Cloudflare AI Search rejects files over 4 MB
    upload_max_size_mb: int = 4
    upload_max_pages: int = 400
    upload_allowed_formats: str = "pdf,docx,pptx,txt,url"

    # Professor document limits
    professor_max_documents: int = 100  # env: PROFESSOR_MAX_DOCUMENTS

    # Langfuse observability
    langfuse_enable: bool = False
    langfuse_secret_key: str = ""
    langfuse_public_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_release: str = "0.1.0"

    # CORS — JSON array, comma-separated, or "*" for development
    cors_origins: list[str] = [
        "https://virtual-professor-frontend.onrender.com",
        "http://localhost:3000",
        "http://localhost:3001",
    ]

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Render (and Heroku) often emit postgres://; SQLAlchemy wants postgresql://."""
        if isinstance(value, str) and value.startswith("postgres://"):
            return "postgresql://" + value[len("postgres://") :]
        return value

    @field_validator("root_path", mode="before")
    @classmethod
    def _normalize_root_path(cls, value: str | None) -> str:
        if not value:
            return ""
        stripped = str(value).strip().rstrip("/")
        if stripped in ("", "/"):
            return ""
        return stripped if stripped.startswith("/") else f"/{stripped}"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: str | list[str]) -> list[str]:
        """Parse CORS_ORIGINS from env: accepts JSON array, comma-separated, or '*'.

        Examples:
          CORS_ORIGINS=["*"]                  → ["*"]
          CORS_ORIGINS=https://a.com,http://b → ["https://a.com", "http://b"]
          CORS_ORIGINS=["https://a.com"]      → ["https://a.com"]
        """
        if isinstance(value, list):
            cleaned = [str(item).strip().rstrip("/") for item in value if str(item).strip()]
            return cleaned or ["*"]
        if isinstance(value, str):
            stripped = value.strip()
            # JSON array format
            if stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        cleaned = [str(item).strip().rstrip("/") for item in parsed if str(item).strip()]
                        return cleaned or ["*"]
                except json.JSONDecodeError:
                    pass
            # Comma-separated or single value
            parts = [p.strip().rstrip("/") for p in stripped.split(",") if p.strip()]
            return parts if parts else ["*"]
        return ["*"]

    model_config = {"env_file": ".env", "extra": "ignore"}

    def validate_production(self) -> list[str]:
        """Check production-critical settings and return a list of warnings/errors."""
        warnings: list[str] = []

        # ── Z.AI API key ────────────────────────────────────────────────────
        if not self.zai_api_key or self.zai_api_key in (
            "changeme",
            "your-api-key",
            "your-z-ai-api-key",
        ):
            raise RuntimeError(
                "ZAI_API_KEY is empty or set to a placeholder. "
                "Create a key at https://z.ai and set ZAI_API_KEY."
            )

        # ── Cloudflare AI Search ────────────────────────────────────────────
        if not self.cloudflare_account_id or not self.cloudflare_api_token:
            raise RuntimeError(
                "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are required. "
                "Create a token with AI Search:Edit and AI Search:Run."
            )
        if not self.cloudflare_ai_search_instance:
            raise RuntimeError(
                "CLOUDFLARE_AI_SEARCH_INSTANCE is empty. "
                "Create an AI Search instance in the Cloudflare dashboard."
            )

        # ── JWT secret key ──────────────────────────────────────────────────
        if not self.jwt_secret_key or self.jwt_secret_key in ("changeme", ""):
            raise RuntimeError(
                "JWT_SECRET_KEY is empty or set to 'changeme'. "
                "Generate a strong secret with: openssl rand -hex 32"
            )

        # ── Admin API key (warning only — still works with a default) ───────
        if self.admin_api_key in ("changeme", ""):
            warnings.append(
                "ADMIN_API_KEY is set to a default value ('changeme'). "
                "Generate a strong random secret for production."
            )

        # ── Default admin user (warning only — app still boots) ─────────────
        if not self.admin_email or not self.admin_password:
            warnings.append(
                "ADMIN_EMAIL/ADMIN_PASSWORD are not set. "
                "No default admin user will be seeded — set them to log in."
            )

        # ── CORS ────────────────────────────────────────────────────────────
        if self.cors_origins == ["*"]:
            warnings.append(
                "CORS_ORIGINS is set to '*', which allows any origin. "
                "Restrict it to specific origins in production."
            )

        # ── Langfuse ────────────────────────────────────────────────────────
        if not self.langfuse_enable:
            warnings.append(
                "Langfuse observability is disabled (LANGFUSE_ENABLE=false). "
                "Enable it in production for trace monitoring."
            )

        return warnings


settings = Settings()
