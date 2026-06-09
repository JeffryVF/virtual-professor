import logging

from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse

from core.config import settings

log = logging.getLogger(__name__)

TOP_K = 5


async def retrieve_context(query: str, professor_collection: str, top_k: int = TOP_K) -> list[str]:
    """Retrieve the top-k relevant chunks from the professor's Qdrant collection."""
    aclient = AsyncQdrantClient(
        url=settings.qdrant_url,
        timeout=30,
    )
    try:
        try:
            collections = await aclient.get_collections()
        except Exception as exc:
            log.warning("Qdrant connection failed: %s", exc)
            return []

        existing = {collection.name for collection in collections.collections}
        if professor_collection not in existing:
            log.info("Collection %s not found in Qdrant, returning empty context", professor_collection)
            return []

        embed_model = OllamaEmbedding(
            model_name=settings.ollama_embed_model,
            base_url=settings.ollama_url,
        )
        vector_store = QdrantVectorStore(
            collection_name=professor_collection,
            aclient=aclient,
        )
        index = VectorStoreIndex.from_vector_store(vector_store, embed_model=embed_model)
        retriever = index.as_retriever(similarity_top_k=top_k)
        nodes = await retriever.aretrieve(query)
        return [node.get_content() for node in nodes]
    except UnexpectedResponse as exc:
        if getattr(exc, "status_code", None) == 404:
            return []
        log.warning("Qdrant unexpected response: %s", exc)
        return []
    except Exception as exc:
        log.warning("RAG retrieval error: %s", exc)
        return []
    finally:
        try:
            await aclient.close()
        except Exception:
            pass
