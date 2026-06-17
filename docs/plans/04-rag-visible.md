# 4. RAG Source Visibility and Indexing Admin

## Objective

Make RAG pipeline outputs visible in the admin dashboard and frontend chat: expose indexed chunks for inspection, show indexing status, display source citations in chat bubbles, and provide re-indexing controls.

## Prerequisites

- Phase 2 (backend auth) complete — admin endpoints secured with JWT
- Phase 3 (frontend auth) complete — login flows and role separation working
- RAG pipeline verified working (retrieval + citation tags in LLM prompts)

## Detailed Steps

### Step 1: Backend — GET /admin/documents/{id}/chunks
- **Action:** Add endpoint to retrieve all Qdrant chunks for a specific document.
- **Files:** `services/backend/routers/admin.py`
- **Details:**
  - Endpoint: `GET /admin/documents/{document_id}/chunks`
  - Requires admin auth (`require_admin` dependency).
  - Look up the `Document` record to get the professor's `collection` name and the document's own metadata.
  - Use `AsyncQdrantClient` to scroll all points in the professor's collection where `payload.document_id == document_id`.
  - Return: `list[ChunkResponse]` with fields:
    - `chunk_index`: int (position within document)
    - `text`: str (first 500 chars truncated for list view, full text optionally via `?full=true`)
    - `score`: float (current relevance score, nullable — only meaningful for query-time)
    - `page_number`: str | None
    - `created_at`: datetime
  - Pagination: support `?offset=0&limit=50` for large documents.
  - Error handling: return 404 if document not found, 400 if document has no chunks (status != "ready").
  - Qdrant scroll query:

    ```python
    from qdrant_client import AsyncQdrantClient
    
    async def get_document_chunks(collection: str, document_id: str, offset: int = 0, limit: int = 50):
        client = AsyncQdrantClient(url=settings.qdrant_url)
        result = await client.scroll(
            collection_name=collection,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=document_id),
                    )
                ]
            ),
            limit=limit,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        return result
    ```

### Step 2: Backend — GET /admin/indexing/status
- **Action:** Add endpoint returning per-collection indexing statistics.
- **Files:** `services/backend/routers/admin.py`
- **Details:**
  - Endpoint: `GET /admin/indexing/status`
  - Requires admin auth.
  - Query all professors, and for each professor:
    - Count documents (grouped by status: pending, processing, ready, error).
    - Sum of `chunk_count` across all documents.
    - For each collection, get point count from Qdrant.
    - Last indexed date: max `uploaded_at` for documents with status=ready.
    - Most recent error: find any document with status=error and include its `error_message` and `filename`.
  - Return JSON:

    ```json
    {
      "collections": [
        {
          "professor_id": "uuid",
          "professor_name": "Prof. García",
          "collection": "prof_garcia_calculus",
          "total_documents": 5,
          "documents_by_status": { "pending": 0, "processing": 1, "ready": 4, "error": 0 },
          "total_chunks": 847,
          "qdrant_points": 847,
          "last_indexed_at": "2026-06-15T10:30:00Z",
          "last_error": null
        }
      ],
      "summary": {
        "total_collections": 3,
        "total_documents": 12,
        "total_chunks": 2341,
        "collections_with_errors": 1
      }
    }
    ```

  - Handle edge case: professor with no documents returns zeros.
  - Handle edge case: Qdrant collection doesn't exist yet (show 0 points).

### Step 3: Backend — POST /admin/documents/{id}/reindex
- **Action:** Add endpoint to re-index a specific document.
- **Files:** `services/backend/routers/admin.py`, `services/backend/services/ingestion.py`
- **Details:**
  - Endpoint: `POST /admin/documents/{document_id}/reindex`
  - Requires admin auth.
  - Look up the document, verify it exists and is in "ready" or "error" status.
  - If document is "pending" or "processing", return 409 "Document is already being processed".
  - Reset document status to "pending", clear `error_message`, set `chunk_count = 0`.
  - Delete existing chunks for this document from Qdrant (reuse the existing `delete_document_chunks` function).
  - Re-run the ingestion pipeline on the original file (file path is stored in `data/uploads/`).
  - Run this as a background task: `BackgroundTasks.add_task(reingest_document, document_id)`.
  - Return 202 Accepted with `{"status": "reindexing", "document_id": "..."}`.
  - The reingestion function should call the same `ingest_document` pipeline used for initial upload.
  - Add a rate limit: no more than 1 reindex per document per 60 seconds (track via Redis or in-memory dict).

### Step 4: Backend — Return source metadata in session response
- **Action:** Include source citations in the `/sessions/{id}/speak` response.
- **Files:** `services/backend/routers/sessions.py`, `services/backend/services/rag.py`, `services/backend/models/schemas.py`
- **Details:**
  - Currently the `/speak` endpoint returns audio bytes. Add a JSON metadata header or a structured response format.
  - Option A: Return a JSON object with `audio_url` and `sources` array. This is cleaner but requires chaning the response format.
  - Option B: Return custom headers: `X-Sources: [{"doc":"...","score":0.95}]`. Less intrusive but limited.
  - Option C: Since the endpoint currently returns `Response(content=audio_bytes, media_type="audio/wav")`, switch to a multipart response or a two-part response (JSON metadata first, then binary). **Recommendation:** Create a new endpoint `POST /sessions/{id}/speak-v2` that returns JSON with a `sources` array, or modify the existing endpoint to accept an `Accept: application/json` header that changes the response format.

  - The `sources` array per assistant message:

    ```json
    {
      "sources": [
        {
          "document_id": "uuid",
          "document_name": "Calculus_Notes_Chapter_3.pdf",
          "relevance_score": 0.92,
          "snippet": "The derivative of x² is 2x...",
          "page_number": "5"
        }
      ]
    }
    ```

  - Modify the `Message` model or create a parallel response structure to store source references per message. Add a `sources` JSON column to the Message table, or create a separate `message_sources` table.
  - **Edge case — sources from deleted documents:** When a document is deleted, its chunks are removed from Qdrant but any historical messages that cited it remain. Show "(source deleted)" in the document_name field if the source document no longer exists in the database.
  - **Edge case — empty index:** When RAG returns zero chunks, the sources array is empty. Add a fallback `"no_sources": true` flag.

### Step 5: Frontend — SourceCitation component
- **Action:** Create a reusable React component to display source citations in chat bubbles.
- **Files:** `services/frontend/src/components/rag/SourceCitation.tsx` (new)
- **Details:**
  - Props: `sources: Array<{document_name: string; relevance_score: number; snippet: string; page_number?: string}>`, `compact?: boolean`
  - Display modes:
    - **Compact mode (default in chat):** Shows a small "📄 N fuentes" badge below the message. Clicking expands the full list.
    - **Expanded mode:** Shows each source as a card with document name (truncated to 60 chars), relevance score (as a progress bar or percentage), and a truncated snippet (2 lines).
  - Collapsible behavior:
    - Start collapsed. Show a subtle "Ver fuentes (N)" link.
    - On click, expand to show the full list with smooth animation.
    - Use `useState` for open/closed state.
  - When no sources: show a small gray "Sin fuentes específicas" indicator.
  - **Edge case — long document names:** Truncate with ellipsis and show full name on hover (title attribute).
  - **Edge case — high scores:** Relevance score > 0.95 shown in green, > 0.75 in yellow, < 0.75 in gray.
  - **Edge case — deleted sources:** If `document_name` is empty or starts with "Deleted:", show a muted "(Fuente eliminada)" badge.

### Step 6: Frontend — Integrate sources into ChatBubble
- **Action:** Add source display to assistant chat messages.
- **Files:** `services/frontend/src/app/session/ChatBubble.tsx`
- **Details:**
  - The `ChatBubble` component (or equivalent) currently displays assistant messages as text + audio.
  - After the assistant message text, add the `<SourceCitation>` component.
  - The message data model needs a `sources` field. Update the TypeScript interface.
  - Parse citation markers in the LLM response text (`[1]`, `[2]`) and make them clickable links that scroll to or highlight the corresponding source in the citation panel.
  - Use `dangerouslySetInnerHTML` or a lightweight markdown renderer to render the text with citation markers. Add a small superscript style for `[N]` markers.
  - Styling:
    - Citation badge: inline with the text, small, rounded, blue background on hover.
    - Sources section below the message: separated by a thin divider, slightly smaller font, muted text color.
    - Responsive: on mobile, sources collapse by default.

### Step 7: Frontend — Admin indexing dashboard
- **Action:** Build admin pages for document indexing status and management.
- **Files:**
  - `services/frontend/src/app/admin/documents/page.tsx` (new)
  - `services/frontend/src/app/admin/documents/[id]/page.tsx` (new)
- **Details:**

  **Documents list page (`/admin/documents`):**
  - Fetch `/admin/indexing/status` on load.
  - Display a summary stats bar: total documents, total chunks, collections with errors.
  - List all professors with their indexing status in a table:
    - Columns: Professor name, total docs, by status (colored badges), total chunks, last indexed, actions.
    - "Actions" column: "View Details" link → `/admin/documents/{professor_id}`.
  - If a collection has errors, show a red "X errors" badge with tooltip showing the error message.
  - Loading state: skeleton table rows while fetching.
  - Error state: "Failed to load indexing status" with retry button.
  - Auto-refresh: optional toggle to poll every 30 seconds.

  **Document detail page (`/admin/documents/[id]`):**
  - `[id]` is the professor ID (not document ID).
  - Show professor info header: name, topic, collection name.
  - List all documents for this professor in a table:
    - Columns: Filename, format, status (badge), chunk count, uploaded at, actions.
    - Actions: "View Chunks" (opens a modal or inline expand), "Reindex" button, "Delete" button.
  - "View Chunks" opens a modal or side panel showing the first 50 chunks with pagination.
    - Each chunk shows: index number, text preview (first 200 chars), page number if available.
    - Full text expands on click.
  - "Reindex" button: confirm dialog, then POST to `/admin/documents/{id}/reindex`.
    - Show loading spinner on the button while reindexing.
    - After completion, refresh the document list.
    - If reindex fails, show error toast.
  - "Delete" button: confirm dialog, then DELETE. Remove from list after success.
  - **Edge case — document with 0 chunks:** Show "No chunks indexed" with a reindex prompt.
  - **Edge case — professor with no documents:** Show empty state illustration with "Upload documents to get started" message.

### Step 8: API integration in frontend
- **Action:** Add new API functions for the indexing and chunk endpoints.
- **Files:** `services/frontend/src/lib/api.ts`
- **Details:**
  - Add functions:
    - `getIndexingStatus(): Promise<IndexingStatusResponse>`
    - `getDocumentChunks(documentId: string, offset?: number, limit?: number): Promise<ChunkResponse[]>`
    - `reindexDocument(documentId: string): Promise<{status: string, document_id: string}>`
  - Add TypeScript interfaces for the new response types.
  - Update the existing `request()` function to use the new JWT auth-aware version from Phase 3.

## Acceptance Criteria

- [ ] `GET /admin/documents/{id}/chunks` returns paginated chunks for any indexed document.
- [ ] `GET /admin/indexing/status` returns per-collection stats with document counts and errors.
- [ ] `POST /admin/documents/{id}/reindex` triggers re-indexing and returns 202.
- [ ] Session `/speak` response includes source metadata (document name, score, snippet).
- [ ] Chat bubbles show collapsible "Sources" section below assistant messages.
- [ ] Sources section shows document name, relevance score bar, and text snippet.
- [ ] When LLM answers without sources, "Sin fuentes específicas" indicator appears.
- [ ] `/admin/documents` page shows indexing dashboard with summary stats.
- [ ] `/admin/documents/[id]` page shows document list with chunk viewer, reindex, and delete.
- [ ] Loading states shown during API calls (skeleton, spinner).
- [ ] All edge cases handled: deleted sources, empty index, in-progress indexing, errors.
- [ ] `npm run build` succeeds.

## Risks & Notes

- **Performance:** The `/admin/indexing/status` endpoint queries multiple professors and their Qdrant collections. For large deployments (50+ professors), this could be slow. Add caching with a 30-second TTL in Redis for the status response.
- **Qdrant scroll with filter:** Ensure the scroll API is efficient with filter by `document_id`. The `document_id` field must be indexed in Qdrant's payload schema. Verify during implementation.
- **Reindex race condition:** If an admin clicks "Reindex" multiple times quickly, the background task could run concurrently. Use a Redis lock or a `processing` status check to prevent this. The previous check (status != "ready" and != "error") handles retries of already-processing documents.
- **Large chunk payloads:** For documents with thousands of chunks, the chunks endpoint needs pagination. Set a reasonable default limit (50) and max limit (200).
- **Frontend state after auth migration:** The admin pages depend on the auth system from Phase 3. Ensure the `AdminRoute` guard is in place before building admin document pages.

## Dependencies

- Phase 2 (auth backend) — admin auth dependencies
- Phase 3 (auth frontend) — admin route guards, auth-aware API client
- Qdrant scroll API — `qdrant-client` already in requirements.txt
- No new npm packages required for frontend (uses existing tailwind + shadcn patterns)
