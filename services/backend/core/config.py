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

    # Redis
    redis_url: str

    # Qdrant
    qdrant_url: str

    # Ollama
    ollama_url: str
    ollama_llm_model: str = "llama3.2"
    ollama_embed_model: str = "nomic-embed-text"
    llm_max_tokens: int = 350  # max tokens per LLM response (env: LLM_MAX_TOKENS)

    # Whisper
    whisper_url: str

    # Kokoro TTS
    kokoro_url: str
    tts_chunk_max_chars: int = 700  # max chars per TTS chunk when splitting
    tts_max_total_chars: int = 6000  # max total chars to synthesize — longer text is truncated gracefully

    # Admin
    admin_api_key: str

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # Session settings
    session_memory_messages: int = 10
    session_memory_max_tokens: int = 4096
    session_timeout_minutes: int = 30

    # RAG
    rag_min_relevance_score: float

    # Reranker
    reranker_type: str = "none"  # "bge" enables, "none" disables
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_top_n: int = 6  # chunks to keep after reranking
    reranker_device: str = "cpu"

    # Retrieval
    rag_retrieval_top_k: int = 40  # env: RAG_RETRIEVAL_TOP_K (chunks to retrieve from Qdrant)

    # Upload validation
    upload_max_size_mb: int = 50
    upload_max_pages: int = 200
    upload_allowed_formats: str = "pdf,docx,pptx,mp3,mp4,wav,ogg,m4a,url"

    # Professor document limits
    professor_max_documents: int = 100  # env: PROFESSOR_MAX_DOCUMENTS

    # Langfuse observability
    langfuse_enable: bool = False
    langfuse_secret_key: str = ""
    langfuse_public_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_release: str = "0.1.0"

    # CORS — JSON array, comma-separated, or "*" for development
    cors_origins: list[str] = ["*"]

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
            return value
        if isinstance(value, str):
            stripped = value.strip()
            # JSON array format
            if stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    pass
            # Comma-separated or single value
            parts = [p.strip() for p in stripped.split(",")]
            return parts if parts else ["*"]
        return ["*"]

    model_config = {"env_file": ".env", "extra": "ignore"}

    def validate_production(self) -> list[str]:
        """Check production-critical settings and return a list of warnings/errors."""
        warnings: list[str] = []

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
