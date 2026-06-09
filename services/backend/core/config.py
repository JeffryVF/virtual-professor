from pydantic_settings import BaseSettings


class Settings(BaseSettings):
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

    # Whisper
    whisper_url: str

    # Kokoro TTS
    kokoro_url: str

    # LiveAvatar
    liveavatar_api_key: str
    liveavatar_api_url: str
    liveavatar_sandbox: bool = True

    # Admin
    admin_api_key: str

    # Session settings
    session_memory_messages: int = 10
    session_timeout_minutes: int = 30

    # CORS — comma-separated origins, or "*" for development
    cors_origins: str = "*"

    model_config = {"env_file": ".env"}


settings = Settings()
