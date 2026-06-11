# Document Validation Specification

## Purpose

Three-layer validation that rejects bad documents before they reach ingestion, preventing silent failures and Qdrant data corruption. Pre-upload checks run synchronously before writing to disk; pre-ingestion checks catch PDF-specific issues before parsing; post-parse checks ensure chunking produced usable content.

## Requirements

### Pre-upload Validation (admin router, synchronous)

| ID | Requirement | HTTP Status |
|---|---|---|
| REQ-PDF-VAL-001 | The system MUST validate MIME type via magic bytes before saving any uploaded file. Extension checks alone SHALL NOT be sufficient. | 400 |
| REQ-PDF-VAL-002 | The system MUST reject files whose size exceeds `UPLOAD_MAX_SIZE_MB`. | 413 |
| REQ-PDF-VAL-003 | The system MUST reject files whose extension is not in `UPLOAD_ALLOWED_FORMATS`. | 400 |
| REQ-PDF-VAL-004 | Each pre-upload failure MUST return a structured JSON body with `error_code` and `message` fields. | 4xx |

### Pre-ingestion Validation (background task, before parse)

| ID | Requirement |
|---|---|
| REQ-PDF-VAL-005 | The system MUST detect and reject password-protected PDFs by attempting to open with PyMuPDF before parsing. |
| REQ-PDF-VAL-006 | The system MUST reject PDFs whose page count exceeds `UPLOAD_MAX_PAGES`. |
| REQ-PDF-VAL-007 | The system MUST extract text from each PDF page and reject PDFs where no page yields extractable text (scanned/image-only). |
| REQ-PDF-VAL-008 | The system MUST use `DocxReader` for .docx files (fix existing bug mapping docx→PDFReader). |

### Post-parse Validation (after chunking)

| ID | Requirement |
|---|---|
| REQ-PDF-VAL-009 | The `SentenceSplitter` MUST produce at least one non-empty node. |
| REQ-PDF-VAL-010 | If chunking yields zero or empty-only nodes, the system MUST raise a clear exception before attempting to index. |

### Error Handling

| ID | Requirement |
|---|---|
| REQ-PDF-VAL-011 | Every pre-ingestion and post-parse failure MUST set `Document.status = error` with a specific `error_message` containing the error code. |
| REQ-PDF-VAL-012 | The `DocumentResponse` schema MUST include the structured error code in the `error_message` field for all error states. |

## Scenarios

### Happy path — valid PDF
- GIVEN a valid PDF (<50MB, under 200 pages, with text content)
- WHEN uploaded and ingested
- THEN status=ready, chunk_count>0, no error_message

### Non-PDF disguised as .pdf
- GIVEN a `.exe` renamed to `.pdf`
- WHEN MIME validation runs in the upload endpoint
- THEN 400 returned with error_code=INVALID_FILE_TYPE

### Oversized file
- GIVEN a 100MB file uploaded as `.pdf`
- WHEN size check runs in the upload endpoint
- THEN 413 returned with error_code=FILE_TOO_LARGE

### Disallowed extension
- GIVEN a `.zip` file uploaded
- WHEN extension check runs in the upload endpoint
- THEN 400 returned with error_code=EXTENSION_NOT_ALLOWED

### Password-protected PDF
- GIVEN a password-protected PDF
- WHEN `ingest_document` tries PyMuPDF open
- THEN Document.status=error, error_message contains PDF_PASSWORD_PROTECTED

### 500-page PDF
- GIVEN a 500-page PDF (exceeds UPLOAD_MAX_PAGES=200)
- WHEN page count check runs before parsing
- THEN Document.status=error, error_message contains PDF_TOO_MANY_PAGES

### Scanned image-only PDF
- GIVEN a scanned PDF with no selectable text (all pages image-only)
- WHEN text extraction check runs
- THEN Document.status=error, error_message contains PDF_NO_EXTRACTABLE_TEXT

### Corrupt PDF
- GIVEN a truncated/broken PDF file
- WHEN PyMuPDF fails to open
- THEN Document.status=error, error_message contains PDF_CORRUPT

### Empty PDF (0 pages)
- GIVEN a valid PDF with zero pages
- WHEN page count check runs
- THEN Document.status=error, error_message contains PDF_NO_EXTRACTABLE_TEXT

### Valid docx (regression for bug fix)
- GIVEN a valid `.docx` file
- WHEN the pipeline runs
- THEN `DocxReader` is used (not PDFReader) and ingestion succeeds

### Valid pptx (existing behavior preserved)
- GIVEN a valid `.pptx` file
- WHEN the pipeline runs
- THEN `PptxReader` is used and ingestion succeeds

### Media format regression
- GIVEN an `.mp3` file
- WHEN the pipeline runs
- THEN Whisper transcription handles it and ingestion succeeds normally

### URL format regression
- GIVEN a URL file
- WHEN the pipeline runs
- THEN `SimpleWebPageReader` handles it and ingestion succeeds normally

## Config Settings

| Variable | Type | Default | Description |
|---|---|---|---|
| `UPLOAD_MAX_SIZE_MB` | `int` | 50 | Maximum uploaded file size in megabytes |
| `UPLOAD_MAX_PAGES` | `int` | 200 | Maximum number of pages for PDF documents |
| `UPLOAD_ALLOWED_FORMATS` | `str` | "pdf,docx,pptx,mp3,mp4,wav,ogg,m4a,url" | Comma-separated list of allowed file extensions |

## Error Codes

| Code | Layer | HTTP | Description |
|---|---|---|---|
| `INVALID_FILE_TYPE` | Pre-upload | 400 | MIME magic bytes do not match the declared extension |
| `FILE_TOO_LARGE` | Pre-upload | 413 | File size exceeds UPLOAD_MAX_SIZE_MB |
| `EXTENSION_NOT_ALLOWED` | Pre-upload | 400 | File extension not in UPLOAD_ALLOWED_FORMATS |
| `PDF_PASSWORD_PROTECTED` | Pre-ingestion | — | PDF requires a password to open |
| `PDF_TOO_MANY_PAGES` | Pre-ingestion | — | Page count exceeds UPLOAD_MAX_PAGES |
| `PDF_NO_EXTRACTABLE_TEXT` | Pre-ingestion | — | PDF contains no extractable text (scanned/image-only) |
| `PDF_CORRUPT` | Pre-ingestion | — | PDF file is corrupted or truncated |
| `EMPTY_CHUNKS` | Post-parse | — | Chunking produced zero or empty-only nodes |
| `PARSE_FAILED` | Post-parse | — | Reader failed to parse the file format |
