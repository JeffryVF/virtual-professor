"""Async HTTP client for Cloudflare AI Search (managed RAG)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from core.config import settings

log = logging.getLogger(__name__)

API_BASE = "https://api.cloudflare.com/client/v4"
MAX_FILE_BYTES = 4 * 1024 * 1024
_SEARCH_MAX_RESULTS = 50


class CloudflareAISearchError(RuntimeError):
    """Raised when the Cloudflare AI Search API rejects a request."""


def is_configured() -> bool:
    return bool(
        settings.cloudflare_account_id
        and settings.cloudflare_api_token
        and settings.cloudflare_ai_search_instance
    )


def item_key(collection: str, document_id: str, filename: str) -> str:
    """Object key used as the folder prefix for per-professor retrieval."""
    safe_name = filename.replace("\\", "/").split("/")[-1] or "document"
    return f"{collection}/{document_id}/{safe_name}"


def parse_item_key(key: str) -> tuple[str, str, str]:
    """Return (collection, document_id, filename) from an item key."""
    parts = key.split("/")
    if len(parts) >= 3:
        return parts[0], parts[1], parts[-1]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return "", "", key


def folder_starts_with_filter(prefix: str) -> dict[str, Any]:
    """Vectorize-style 'starts with' filter for a folder prefix."""
    if not prefix.endswith("/"):
        prefix = f"{prefix}/"
    return {"folder": {"$gte": prefix, "$lt": f"{prefix[:-1]}0"}}


def _instance_url(path: str = "") -> str:
    base = (
        f"{API_BASE}/accounts/{settings.cloudflare_account_id}"
        f"/ai-search/instances/{settings.cloudflare_ai_search_instance}"
    )
    return f"{base}/{path.lstrip('/')}" if path else base


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.cloudflare_api_token}"}


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "result" in payload:
        if payload.get("success") is False:
            errors = payload.get("errors") or payload.get("error") or payload
            raise CloudflareAISearchError(f"Cloudflare AI Search error: {errors}")
        return payload["result"]
    return payload


def _require_configured() -> None:
    if not is_configured():
        raise CloudflareAISearchError(
            "Cloudflare AI Search is not configured. Set CLOUDFLARE_ACCOUNT_ID, "
            "CLOUDFLARE_API_TOKEN, and CLOUDFLARE_AI_SEARCH_INSTANCE."
        )


async def get_instance() -> dict[str, Any]:
    """Fetch the configured AI Search instance (used as a health probe)."""
    _require_configured()
    async with httpx.AsyncClient(timeout=settings.cloudflare_timeout_seconds) as client:
        response = await client.get(_instance_url(), headers=_auth_headers())
        response.raise_for_status()
        result = _unwrap(response.json())
    if not isinstance(result, dict):
        return {"id": settings.cloudflare_ai_search_instance}
    return result


async def upload_item(
    key: str,
    content: bytes,
    content_type: str,
    *,
    wait_for_completion: bool = True,
) -> dict[str, Any]:
    """Upload a file into the instance's built-in storage and index it."""
    _require_configured()
    if len(content) > MAX_FILE_BYTES:
        raise CloudflareAISearchError(
            f"FILE_TOO_LARGE: Cloudflare AI Search rejects files over 4 MB "
            f"({len(content)} bytes)"
        )
    data = {"wait_for_completion": "true" if wait_for_completion else "false"}
    files = {"file": (key, content, content_type)}
    async with httpx.AsyncClient(timeout=settings.cloudflare_timeout_seconds) as client:
        response = await client.post(
            _instance_url("items"),
            headers=_auth_headers(),
            data=data,
            files=files,
        )
        response.raise_for_status()
        result = _unwrap(response.json())
    if not isinstance(result, dict):
        return {"key": key, "status": "queued"}
    return result


async def get_item_by_key(key: str) -> dict[str, Any] | None:
    _require_configured()
    async with httpx.AsyncClient(timeout=settings.cloudflare_timeout_seconds) as client:
        response = await client.get(
            _instance_url("items"),
            headers=_auth_headers(),
            params={"key": key, "source": "builtin"},
        )
        response.raise_for_status()
        result = _unwrap(response.json())
    items = _as_item_list(result)
    for item in items:
        if item.get("key") == key:
            return item
    return items[0] if items else None


async def list_items() -> list[dict[str, Any]]:
    _require_configured()
    items: list[dict[str, Any]] = []
    page = 1
    async with httpx.AsyncClient(timeout=settings.cloudflare_timeout_seconds) as client:
        while True:
            response = await client.get(
                _instance_url("items"),
                headers=_auth_headers(),
                params={"page": page, "per_page": 100, "source": "builtin"},
            )
            response.raise_for_status()
            payload = response.json() if response.content else {}
            result = _unwrap(payload)
            batch = _as_item_list(result)
            items.extend(batch)
            info = payload.get("result_info") if isinstance(payload, dict) else None
            total = (info or {}).get("total_count") if isinstance(info, dict) else None
            if not batch or (total is not None and len(items) >= int(total)):
                break
            if len(batch) < 100:
                break
            page += 1
    return items


async def delete_item(item_id: str) -> None:
    _require_configured()
    encoded = quote(item_id, safe="")
    async with httpx.AsyncClient(timeout=settings.cloudflare_timeout_seconds) as client:
        response = await client.delete(
            _instance_url(f"items/{encoded}"),
            headers=_auth_headers(),
        )
        response.raise_for_status()


async def search(
    query: str,
    *,
    folder_prefix: str | None = None,
    max_num_results: int | None = None,
) -> list[dict[str, Any]]:
    """Semantic search. Returns raw chunk dicts from the API."""
    _require_configured()
    limit = max(1, min(max_num_results or settings.rag_retrieval_top_k, _SEARCH_MAX_RESULTS))
    body: dict[str, Any] = {
        "query": query or " ",
        "ai_search_options": {
            "retrieval": {
                "max_num_results": limit,
            }
        },
    }
    if folder_prefix:
        body["ai_search_options"]["retrieval"]["filters"] = folder_starts_with_filter(
            folder_prefix
        )
    async with httpx.AsyncClient(timeout=settings.cloudflare_timeout_seconds) as client:
        response = await client.post(
            _instance_url("search"),
            headers={**_auth_headers(), "Content-Type": "application/json"},
            json=body,
        )
        response.raise_for_status()
        result = _unwrap(response.json())
    if isinstance(result, dict):
        chunks = result.get("chunks") or result.get("data") or []
        return list(chunks)
    if isinstance(result, list):
        return result
    return []


def _as_item_list(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        for key in ("items", "data", "objects"):
            nested = result.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        if "id" in result or "key" in result:
            return [result]
    return []
