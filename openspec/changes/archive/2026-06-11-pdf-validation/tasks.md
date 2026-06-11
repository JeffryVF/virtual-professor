# Tasks: PDF / Document Validation

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~380-420 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | size-exception |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Config + deps + pre-upload validation | PR 1 | foundation layer, backward-compatible |
| 2 | Pre-ingestion + post-parse + bug fix | PR 2 | depends on PR 1; core validation logic |
| 3 | Error responses + integration tests | PR 3 | depends on PR 2; wires everything |

## Phase 1: Config + Dependencies

- [ ] 1.1 Add `upload_max_size_mb: int = 50`, `upload_max_pages: int = 200`, `upload_allowed_formats: str = "pdf,docx,pptx,mp3,mp4,wav,ogg,m4a,url"` to `Settings` in `core/config.py`
- [ ] 1.2 Add `python-magic>=0.4.27` to `requirements.txt`

## Phase 2: Pre-upload Validation (router layer)

- [ ] 2.1 **RED**: Write `tests/test_validation.py` with test class for `validate_upload_file()` — valid PDF MIME, non-PDF disguised as .pdf, oversized file, disallowed extension
- [ ] 2.2 **GREEN**: Implement `validate_upload_file()` in `routers/admin.py` using `python-magic` (extension check → MIME check → size check), seek file back to 0 after reading
- [ ] 2.3 Wire `validate_upload_file()` into `POST /professors/{id}/documents` before file save, raise `HTTPException` with 400/413 + `{"error": {"code": ..., "message": ...}}`

## Phase 3: Pre-ingestion Validation (background task layer)

- [ ] 3.1 **RED**: Write tests for `_validate_document()` — password-protected PDF, too-many-pages PDF, no-text PDF, corrupt PDF, valid PDF passes
- [ ] 3.2 **GREEN**: Implement `_validate_document()` in `services/ingestion.py` using PyMuPDF (fitz): check encrypted → page count ≤ `max_pages` → at least one page with extractable text
- [ ] 3.3 Call `_validate_document()` at start of `ingest_document()`, set `doc.status=error` + `doc.error_message="ERROR_CODE: description"` on failure, return early (skip parse/index)

## Phase 4: Post-parse Validation

- [ ] 4.1 **RED**: Write test for post-parse check — `SentenceSplitter` yields zero nodes → rejected; yields empty-text node → rejected
- [ ] 4.2 **GREEN**: Add post-parse check in `ingest_document()` after chunking: if `len(nodes) == 0` or all nodes have empty `get_content()`, raise `ValueError("EMPTY_CHUNKS: ...")`

## Phase 5: Bug Fix — docx Reader

- [ ] 5.1 **RED**: Write test confirming docx uses `DocxReader` (not `PDFReader`) — mock `_FORMAT_READERS` and assert `DocxReader` instantiated
- [ ] 5.2 **GREEN**: Fix `_FORMAT_READERS` dict in `services/ingestion.py`: change `"docx": PDFReader` to `"docx": DocxReader`

## Phase 6: Error Code Responses

- [ ] 6.1 Define structured error code constants/mapping in `routers/admin.py` (or a shared module) — cover `INVALID_FILE_TYPE`, `FILE_TOO_LARGE`, `EXTENSION_NOT_ALLOWED`
- [ ] 6.2 Verify all validation paths return correct `error_code` + `message`: pre-upload via `HTTPException`, pre-ingestion/post-parse via `Document.error_message`

## Phase 7: Integration Tests

- [ ] 7.1 Write full integration test for upload endpoint: valid PDF upload → 201 + `Document(status=pending)`
- [ ] 7.2 Write integration tests for each failure mode: non-PDF disguised → 400, oversized → 413, bad extension → 400, all verify `error.code` in body
