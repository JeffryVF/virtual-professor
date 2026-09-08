"""Qdrant Cloud (or local) client factory.

Free-tier Cloud clusters authenticate with an API key over HTTPS.
A local Docker cluster can omit the key and use http://qdrant:6333.
"""

from __future__ import annotations

from qdrant_client import AsyncQdrantClient, QdrantClient

from core.config import settings


def qdrant_client_kwargs() -> dict:
    """Keyword arguments shared by the sync and async Qdrant clients."""
    kwargs: dict = {
        "url": settings.qdrant_url,
        "timeout": 30,
        "prefer_grpc": False,
        "check_compatibility": False,
    }
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key
    return kwargs


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(**qdrant_client_kwargs())


def get_async_qdrant_client() -> AsyncQdrantClient:
    return AsyncQdrantClient(**qdrant_client_kwargs())
