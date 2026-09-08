"""Tests for the Cloudflare AI Search HTTP client helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.cloudflare import (
    CloudflareAISearchError,
    folder_starts_with_filter,
    item_key,
    parse_item_key,
    search,
    upload_item,
)


def test_item_key_nests_collection_and_document():
    assert item_key("prof_abc", "doc-1", "notes.pdf") == "prof_abc/doc-1/notes.pdf"
    assert item_key("prof_abc", "doc-1", "../secret.pdf") == "prof_abc/doc-1/secret.pdf"


def test_parse_item_key():
    collection, document_id, filename = parse_item_key("prof_abc/doc-1/notes.pdf")
    assert collection == "prof_abc"
    assert document_id == "doc-1"
    assert filename == "notes.pdf"


def test_folder_starts_with_filter():
    filt = folder_starts_with_filter("prof_abc")
    assert filt["folder"]["$gte"] == "prof_abc/"
    assert filt["folder"]["$lt"] == "prof_abc0"


@pytest.mark.asyncio
async def test_search_posts_query_and_folder_filter():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "success": True,
        "result": {
            "chunks": [
                {
                    "text": "hello",
                    "score": 0.9,
                    "item": {"key": "prof_abc/doc-1/a.pdf"},
                }
            ]
        },
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=response)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with (
        patch("core.cloudflare.is_configured", return_value=True),
        patch("core.cloudflare.httpx.AsyncClient", return_value=mock_client),
        patch("core.cloudflare.settings.cloudflare_account_id", "acct"),
        patch("core.cloudflare.settings.cloudflare_api_token", "token"),
        patch("core.cloudflare.settings.cloudflare_ai_search_instance", "virtual-professor"),
        patch("core.cloudflare.settings.rag_retrieval_top_k", 8),
    ):
        chunks = await search("que es RAG", folder_prefix="prof_abc", max_num_results=5)

    assert chunks[0]["text"] == "hello"
    body = mock_client.post.await_args.kwargs["json"]
    assert body["query"] == "que es RAG"
    assert body["ai_search_options"]["retrieval"]["max_num_results"] == 5
    assert body["ai_search_options"]["retrieval"]["filters"]["folder"]["$gte"] == "prof_abc/"


@pytest.mark.asyncio
async def test_upload_rejects_files_over_4mb():
    with patch("core.cloudflare.is_configured", return_value=True):
        with pytest.raises(CloudflareAISearchError, match="FILE_TOO_LARGE"):
            await upload_item("prof/doc/a.pdf", b"x" * (4 * 1024 * 1024 + 1), "application/pdf")
