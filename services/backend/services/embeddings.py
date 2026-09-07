"""Z.AI OpenAI-compatible embeddings used by RAG ingestion and retrieval."""

from llama_index.embeddings.openai import OpenAIEmbedding

from core.config import settings


def get_embed_model() -> OpenAIEmbedding:
    """Return a LlamaIndex embedding client pointed at the Z.AI API.

    Uses the same API key as chat completions so Render/Vercel do not need
    a local Ollama process for vector search.
    """
    return OpenAIEmbedding(
        model=settings.zai_embed_model,
        api_key=settings.zai_api_key,
        api_base=settings.zai_base_url.rstrip("/") + "/",
        dimensions=settings.embed_dim,
    )
