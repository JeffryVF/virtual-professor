# Design: PDF / Document Validation

## Technical Approach

Three-layer defense that rejects bad documents before they corrupt Qdrant. Pre-upload validation (sync, in router) catches obvious issues before any write. Pre-ingestion validation (async, in background task) catches format-specific issues before parsing. Post-parse validation ensures chunking produced usable content.

Maps to proposal: each validation layer matches one of the three approach bullets. Spec requirements REQ-PDF-VAL-001 through REQ-PDF-VAL-012 are distributed across layers as follows: 001-004 → Layer 1, 005-008 → Layer 2, 009-010 → Layer 3, 011-012 → error handling in both Layer 2 and 3.

## Architecture Decisions

### Decision: python-magic for MIME detection

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `python-magic` | System libmagic1 required, but already in Dockerfile | ✅ **Chosen** |
| `mimetypes` stdlib | Extension-only, no magic bytes | Rejected — unreliable |
| `file` CLI subprocess | Slow, fragile | Rejected |

### Decision: PyMuPDF (fitz) for PDF inspection

| Option | Tradeoff | Decision |
|--------|----------|----------|
| PyMuPDF | Already a transitive dep via llama-index-readers-file | ✅ **Chosen** |
| pdfminer.six | Separate dep, no existing use | Rejected |
| pypdf | Separate dep, weaker encryption detection | Rejected |

### Decision: Structured error codes in responses

All errors carry a machine-readable `error_code` (e.g. `FILE_TOO_LARGE`) and a human `message`. Pre-upload failures return `{"error": {"code": "...", "message": "..."}}` via HTTPException. Pre-ingestion/post-parse failures set `Document.error_message = "ERROR_CODE: description"`.

### Decision: Config-driven limits

`UPLOAD_MAX_SIZE_MB`, `UPLOAD_MAX_PAGES`, and `UPLOAD_ALLOWED_FORMATS` live in `Settings` with sensible defaults (50, 200, comma-separated formats). No hardcoding.

## Data Flow

```
Client ──POST /documents──→ upload_document()
                                │
                    ┌───────────┴───────────┐
                    │  validate_upload_file  │ ◄── python-magic, size, ext
                    │  fail → 400/413       │
                    └───────────┬───────────┘
                                │ pass
                                ▼
                    save file, create Document(status=pending)
                    background_tasks.add_task(ingest_document)
                                │
                    ┌───────────┴───────────┐
                    │  _validate_document    │ ◄── PyMuPDF / zipfile
                    │  fail → set error     │
                    └───────────┬───────────┘
                                │ pass
                                ▼
                    reader.load_data() ──→ nodes (chunks)
                                │
                    ┌───────────┴───────────┐
                    │  post-parse check      │ ◄── len(nodes) > 0, has text
                    │  fail → set error     │
                    └───────────┬───────────┘
                                │ pass
                                ▼
                    index to Qdrant
                    Document(status=ready)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `routers/admin.py` | Modify | Add `validate_upload_file()` call in `upload_document` before save |
| `services/ingestion.py` | Modify | Add `_validate_document()`, post-parse check, fix `docx→DocxReader` |
| `core/config.py` | Modify | Add `upload_max_size_mb`, `upload_max_pages`, `upload_allowed_formats` |
| `requirements.txt` | Modify | Add `python-magic>=0.4.27` |
| `tests/test_validation.py` | Create | Tests for all three layers |

## Interfaces / Contracts

### `validate_upload_file`
```python
def validate_upload_file(
    file: UploadFile,
    max_size_mb: int,
    allowed_formats: list[str],
) -> tuple[bool, str | None, str | None]:
    """Returns (is_valid, error_code, error_message)."""
    # Reads bytes for magic, seeks back to 0
    # Checks: extension, MIME, file_size
```

### `_validate_document`
```python
def _validate_document(
    file_path: str,
    file_format: str,
    max_pages: int,
) -> tuple[bool, str]:
    """Returns (is_valid, error_message).
    PDF: PyMuPDF → encrypted? page count ≤ max_pages? text extractable?
    docx/pptx: zipfile.is_zipfile()
    media/url: file existence, size sanity
    """
```

### Error response (pre-upload)
```json
{
    "error": {
        "code": "INVALID_FILE_TYPE",
        "message": "File MIME type 'application/x-msdownload' does not match extension '.pdf'"
    }
}
```

### Setting additions
```python
upload_max_size_mb: int = 50
upload_max_pages: int = 200
upload_allowed_formats: str = "pdf,docx,pptx,mp3,mp4,wav,ogg,m4a,url"
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `validate_upload_file` | Test MIME detection with real file bytes, size limits, extension whitelist |
| Unit | `_validate_document` | Test with mock PyMuPDF (encrypted=True, page_count>max, no text) |
| Unit | Post-parse check | Mock reader returning empty nodes |
| Integration | Full upload → validation flow | Use httpx test client, real file upload, assert 4xx on bad files |
| Integration | `docx` reader fix | Send .docx file, verify `DocxReader` is invoked (via mock) |

## Migration / Rollout

No migration required. Validation applies only to new uploads. Existing documents with `pending` or `error` status are unaffected.

## Open Questions

None.
