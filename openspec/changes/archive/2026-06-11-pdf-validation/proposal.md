# Proposal: PDF / Document Validation

## Intent

Zero validations on uploaded documents causes silent failures, Qdrant data corruption (empty chunks from scanned PDFs), and poor UX. This change adds three-layer validation so bad documents reject early with clear errors.

## Scope

### In Scope
- Pre-upload: magic bytes, file size limit (50MB), extension whitelist
- Pre-ingestion: password-protected detection, page count limit (200), text presence check
- Post-parse: non-empty chunks, reject empty results
- Format-specific rules: pdf, docx, pptx, media, url
- Structured error codes per failure mode
- Tests for all 3 layers

### Out of Scope
- OCR for scanned PDFs (separate change)
- Malicious content analysis beyond MIME verification
- Image analysis within PDFs
- Async ingestion queue improvements (separate change)

## Capabilities

### New Capabilities
- `document-validation`: Documents MUST pass pre-upload, pre-ingestion, and post-parse validation with format-specific rules. Failure returns structured error code + clear message.

### Modified Capabilities
- None — new capability orthogonal to existing specs (rag-relevance-filtering, rag-reranking, rag-source-citations).

## Approach

Three-layer validation:
1. **Pre-upload** (sync, admin router): magic bytes via python-magic, max file size from config, extension whitelist
2. **Pre-ingestion** (ingest_document, before parse): PyMuPDF/fitz for password protection, page count, text scan. zipfile probe for docx/pptx
3. **Post-parse** (after chunking): validate ≥1 chunk with content, reject empty results

Also fix `_FORMAT_READERS` bug mapping docx→PDFReader.

## Key Decisions
- python-magic for MIME detection (libmagic1 already in Dockerfile)
- PyMuPDF/fitz for PDF inspection (already a transitive llama-index dep)
- Max file size: configurable env var, default 50MB
- Max pages: configurable, default 200
- Error responses: structured codes per failure mode
- Reject early with clear message instead of silent failure

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `routers/admin.py` | Modified | Pre-upload validation in upload endpoint |
| `services/ingestion.py` | Modified | Pre-ingestion + post-parse validation |
| `core/config.py` | Modified | max_file_size_mb, max_pages settings |
| `requirements.txt` | Modified | Add python-magic |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Backward compat with existing pending/error docs | Low | Validation only on new uploads |
| PyMuPDF version conflict with llama-index | Low | Already transitive dep; pin version |
| python-magic availability | Low | libmagic1 in Dockerfile; pip dep added |

## Rollback Plan

Revert changes to admin.py, ingestion.py, config.py. Remove python-magic from requirements.txt. Existing validated uploads remain valid.

## Dependencies

- python-magic pip package (system dep libmagic1 already in Dockerfile)
- Config settings: max_file_size_mb, max_pages

## Success Criteria

- [ ] Non-PDF as .pdf → 4xx + structured error
- [ ] Password-protected PDF → rejected with clear error
- [ ] Scanned-image PDF (no text) → rejected
- [ ] Valid PDF → accepted and ingested normally
- [ ] Size-limit exceeded → rejected 4xx
- [ ] Page-limit exceeded → rejected
- [ ] Empty docx → rejected
- [ ] All 3-layer tests pass
