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
    session_memory_max_tokens: int = 4096
    session_timeout_minutes: int = 30

    # RAG
    rag_min_relevance_score: float

    # Reranker
    reranker_type: str = "none"  # "bge" enables, "none" disables
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_top_n: int = 5  # chunks passed to cross-encoder
    reranker_device: str = "cpu"

    # Upload validation
    upload_max_size_mb: int = 50
    upload_max_pages: int = 200
    upload_allowed_formats: str = "pdf,docx,pptx,mp3,mp4,wav,ogg,m4a,url"

    # CORS — comma-separated origins, or "*" for development
    cors_origins: str = "*"

    model_config = {"env_file": ".env"}


settings = Settings()
