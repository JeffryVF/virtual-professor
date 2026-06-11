import fitz
import httpx
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.readers.base import BaseReader
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.readers.file import (
    DocxReader,
    PDFReader,
    PptxReader,
)
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from core.config import settings
from core.database import AsyncSessionLocal

CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
EMBED_DIM = 768  # nomic-embed-text output dimension

_FORMAT_READERS: dict[str, type[BaseReader]] = {
    "pdf": PDFReader,
    "docx": DocxReader,
    "pptx": PptxReader,
}


def _validate_document(file_path: str, file_format: str, max_pages: int) -> tuple[bool, str]:
    """Validate a document before ingestion.

    For PDFs (via PyMuPDF/fitz):
      - Reject if password-protected
      - Reject if page count exceeds max_pages
      - Reject if no page has extractable text (scanned/image-only)
    For other formats (docx, pptx, media, url): no PDF-specific checks.

    Returns (is_valid, error_message). On success, error_message is empty string.
    """
    if file_format == "pdf":
        try:
            doc = fitz.open(file_path)
        except Exception:
            return (False, "PDF_CORRUPT: PDF file is corrupted or cannot be opened")

        with doc:
            if doc.is_encrypted:
                return (False, "PDF_PASSWORD_PROTECTED: PDF is password-protected and cannot be processed")

            if doc.page_count > max_pages:
                return (
                    False,
                    f"PDF_TOO_MANY_PAGES: PDF has {doc.page_count} pages, maximum is {max_pages}",
                )

            for page in doc:
                text = page.get_text().strip()
                if text:
                    return (True, "")

            return (False, "PDF_NO_EXTRACTABLE_TEXT: PDF contains no extractable text (possible scanned document)")

    # Non-PDF formats skip pre-ingestion PDF validation
    return (True, "")

_MEDIA_FORMATS = {"mp3", "mp4", "wav", "ogg", "m4a"}


async def _ensure_collection(client: QdrantClient, collection_name: str) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )


async def _transcribe_media(file_path: str) -> str:
    async with httpx.AsyncClient(timeout=300) as client:
        with open(file_path, "rb") as f:
            response = await client.post(
                f"{settings.whisper_url}/asr",
                files={"audio_file": f},
                params={"task": "transcribe", "output": "txt"},
            )
        response.raise_for_status()
        return response.text.strip()


async def ingest_document(
    document_id: str,
    professor_collection: str,
    file_path: str,
    file_format: str,
) -> None:
    """Background task: parse, chunk, embed and store a document in Qdrant."""
    from sqlalchemy import select

    from models.db import Document, DocumentStatus

    async with AsyncSessionLocal() as db:
        try:
            # Pre-ingestion validation
            is_valid, error_msg = _validate_document(
                file_path,
                file_format,
                max_pages=settings.upload_max_pages,
            )
            if not is_valid:
                result = await db.execute(select(Document).where(Document.id == document_id))
                doc = result.scalar_one()
                doc.status = DocumentStatus.error
                doc.error_message = error_msg
                await db.commit()
                return

            qdrant = QdrantClient(url=settings.qdrant_url)
            await _ensure_collection(qdrant, professor_collection)

            embed_model = OllamaEmbedding(
                model_name=settings.ollama_embed_model,
                base_url=settings.ollama_url,
            )

            # Load and parse document
            if file_format in _MEDIA_FORMATS:
                # Transcribe audio/video with Whisper, then treat as plain text
                from pathlib import Path
                from llama_index.core import Document as LIDocument
                text = await _transcribe_media(file_path)
                documents = [LIDocument(text=text)]
            elif file_format == "url":
                from pathlib import Path
                from llama_index.readers.web import SimpleWebPageReader
                url = Path(file_path).read_text().strip()
                documents = SimpleWebPageReader(html_to_text=True).load_data([url])
            elif file_format in _FORMAT_READERS:
                reader = _FORMAT_READERS[file_format]()
                documents = reader.load_data(file=file_path)
            else:
                # Fallback: read as plain text
                from llama_index.core import SimpleDirectoryReader
                documents = SimpleDirectoryReader(input_files=[file_path]).load_data()

            # Chunk
            splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
            nodes = splitter.get_nodes_from_documents(documents)

            # Post-parse validation: ensure at least one non-empty node
            if not nodes or all(not node.get_content().strip() for node in nodes):
                result = await db.execute(select(Document).where(Document.id == document_id))
                doc = result.scalar_one()
                doc.status = DocumentStatus.error
                doc.error_message = "EMPTY_CHUNKS: Document produced no usable text content after chunking"
                await db.commit()
                return

            # Fetch document for source_filename metadata
            result = await db.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one()

            for node in nodes:
                node.metadata["document_id"] = document_id
                node.metadata["professor_collection"] = professor_collection
                node.metadata["source_filename"] = doc.filename

            # Index into Qdrant
            vector_store = QdrantVectorStore(client=qdrant, collection_name=professor_collection)
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            VectorStoreIndex(nodes, storage_context=storage_context, embed_model=embed_model)

            # Mark document as ready
            doc.status = DocumentStatus.ready
            doc.chunk_count = len(nodes)
            await db.commit()

            qdrant.close()

        except Exception as exc:
            result = await db.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one()
            doc.status = DocumentStatus.error
            doc.error_message = str(exc)
            await db.commit()
            raise


async def delete_qdrant_collection(collection_name: str) -> None:
    """Delete the entire Qdrant collection (used when removing a professor)."""
    client = QdrantClient(url=settings.qdrant_url)
    existing = {c.name for c in client.get_collections().collections}
    if collection_name in existing:
        client.delete_collection(collection_name=collection_name)
    client.close()


async def delete_document_chunks(professor_collection: str, document_id: str) -> None:
    """Remove all Qdrant points that belong to a specific document."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = QdrantClient(url=settings.qdrant_url)
    client.delete(
        collection_name=professor_collection,
        points_selector=Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        ),
    )
    client.close()
