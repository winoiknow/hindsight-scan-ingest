# hindsight-scan-ingest — Architecture & Implementation Plan

## 1. Purpose

A Python daemon that watches one or more local folders, extracts text from any document type (including OCR for images), and ingests the content into a self-hosted Vectorize Hindsight instance via its Python SDK and REST API. Only changed or new files are re-ingested; a SQLite manifest provides idempotency.

---

## 2. High-Level Architecture

```
 Configured Folders
        │
        ▼
 ┌─────────────┐    file list     ┌──────────────┐
 │   Scanner   │ ───────────────► │   Manifest   │  (SQLite)
 │ (recursive  │ ◄── known hashes─│  (ingestion_ │
 │  walk)      │                  │  manifest.db)│
 └──────┬──────┘                  └──────────────┘
        │ new / changed files
        ▼
 ┌─────────────┐
 │  Extractor  │  per-format text/binary extraction
 │             │  .txt .md .csv → read()
 │             │  .pdf          → PyMuPDF (fitz)
 │             │  .docx         → python-docx
 │             │  .pptx         → python-pptx
 │             │  .xlsx         → openpyxl
 │             │  .png .jpg …   → Tesseract OCR (pytesseract)
 └──────┬──────┘
        │ extracted text  (or raw bytes for native upload)
        ▼
 ┌─────────────┐
 │  Ingester   │  wraps hindsight-client SDK
 │             │  strategy A: native file upload  (PDF, DOCX, images…)
 │             │  strategy B: retain(content=text) for other formats
 └──────┬──────┘
        │ HTTP
        ▼
 Hindsight API  http://localhost:8888  (or configured URL)

        ▲
 APScheduler  (BlockingScheduler, configurable interval)
        │
  main.py / CLI entry point
```

---

## 3. Hindsight API Integration

### SDK initialization
```python
from hindsight_client import Hindsight

client = Hindsight(
    base_url=config.server_url,   # default http://localhost:8888
    api_key=config.api_key or None,  # None = unauthenticated (local Docker default)
    timeout=60.0,
)
```
`api_key` is optional — leave blank for a local Docker instance. Set it when pointing at a cloud-hosted Hindsight endpoint that requires bearer token auth.

### Native file upload (preferred path)
- **Endpoint**: `POST /v1/default/banks/{bank_id}/files`
- Natively handles: PDF, DOCX, PPTX, XLSX, images (built-in OCR), audio, plain text
- Sends raw bytes as multipart form data
- Returns a document_id for manifest tracking

### Text retain (fallback / custom OCR path)
```python
client.retain(
    bank_id=config.bank_id,
    content=extracted_text,
    document_id=stable_document_id,   # SHA-256 of file path → upsert idempotency
    context=config.source,            # shapes Hindsight's fact extraction
    metadata={"session": config.session, "file": relative_path},
    update_mode="replace",            # full re-extract on change
    retain_async=True,
)
```

### Key configuration parameters mapped to Hindsight concepts
| App config knob | Hindsight parameter | Purpose |
|---|---|---|
| `bank_id` | `bank_id` | selects the memory bank the agent reads |
| `source` | `context` | labels the origin (e.g. "project-docs") |
| `session` | `metadata.session` | ties memories to a specific session/agent |
| `server_url` | `base_url` | self-hosted URL |

---

## 4. File Processing Strategy

| Format | Library | Upload strategy |
|---|---|---|
| `.txt` `.md` `.csv` `.log` | built-in | native file upload (primary) |
| `.pdf` | — | native file upload (primary) |
| `.docx` | — | native file upload (primary) |
| `.pptx` | — | native file upload (primary) |
| `.xlsx` | openpyxl | always local extraction → text retain |
| `.png` `.jpg` `.jpeg` `.tiff` `.bmp` `.gif` | Pillow + pytesseract | native file upload (primary); Tesseract fallback on upload error |

**Decision logic**:
1. **Primary path — native Hindsight file upload**: Raw bytes sent to `POST /v1/default/banks/{bank_id}/files`. Hindsight handles parsing and OCR server-side. Simpler, no local binary dependencies for most formats.
2. **Tesseract fallback**: If the native upload returns an error for an image file, the ingester retries by running Tesseract locally and submitting the extracted text via `retain()`. Tesseract must be installed for the fallback to activate; if it is not available, the file is logged as a warning and skipped.
3. **XLSX always local**: Spreadsheet row/column semantics are serialized to tabular text (`sheet: row key=value …`) before ingestion, giving Hindsight meaningful facts rather than binary noise.

---

## 5. Change Detection & Idempotency

- **Manifest DB** (`ingestion_manifest.db`, SQLite) stores:
  ```
  file_path TEXT PRIMARY KEY
  sha256    TEXT
  doc_id    TEXT
  ingested_at TEXT
  ```
- On each scan: walk folders → stat each file → compare SHA-256 → only process if hash changed or file is new.
- `document_id` sent to Hindsight = `sha256(file_path)[:16]` (stable, deterministic per file path).
- Hindsight's `update_mode="replace"` handles re-ingestion cleanly: old memories for that document_id are removed before new ones are extracted.

---

## 6. Project File Structure

```
hindsight-scan-ingest/
├── hindsight_ingest/
│   ├── __init__.py
│   ├── config.py        # Pydantic settings model + YAML loader
│   ├── scanner.py       # folder walk + change detection
│   ├── manifest.py      # SQLite manifest CRUD
│   ├── extractor.py     # per-format text extraction
│   └── ingester.py      # Hindsight SDK wrapper (retain + file upload)
├── tests/
│   ├── fixtures/        # sample .txt .pdf .docx .png etc.
│   ├── test_scanner.py
│   ├── test_extractor.py
│   ├── test_manifest.py
│   └── test_ingester.py # uses responses mock / local Hindsight
├── main.py              # CLI entry point + APScheduler
├── config.yaml          # user-editable configuration (see §7)
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

---

## 7. Configuration (`config.yaml`)

```yaml
# Hindsight connection
server_url: http://localhost:8888
api_key: ""                     # leave blank if Hindsight runs without auth

# Memory routing
bank_id: "default"
source: "document-ingest"       # used as context in Hindsight retain calls
session: ""                     # optional session tag

# Folders to watch (add as many as needed)
folders:
  - /path/to/docs
  # - /path/to/more-docs

# Scan interval in minutes (e.g. 5, 15, 60)
scan_interval_minutes: 15

# Chunking — set to true to split large documents locally before ingestion.
# Default false: Hindsight handles all chunking server-side.
# Enable if you have very large files and want to control chunk boundaries yourself.
local_chunking_enabled: false
chunk_size_tokens: 1000     # only used when local_chunking_enabled: true
chunk_overlap_tokens: 100   # only used when local_chunking_enabled: true

# Supported extensions (extend or restrict as needed)
supported_extensions:
  - .txt
  - .md
  - .pdf
  - .docx
  - .pptx
  - .xlsx
  - .csv
  - .png
  - .jpg
  - .jpeg
  - .tiff
  - .bmp
```

CLI overrides are provided for all critical knobs:

```
python main.py [OPTIONS]
  --config PATH               path to config.yaml (default: ./config.yaml)
  --server-url URL            override server_url
  --bank-id ID                override bank_id
  --source TEXT               override source/context
  --session TEXT              override session
  --folder PATH               add a folder (repeatable)
  --interval MINUTES          override scan_interval_minutes
  --ocr-engine ENGINE         override ocr_engine
  --once                      run a single scan pass then exit
```

---

## 8. Scheduler

- **Library**: `APScheduler` (BlockingScheduler)
- Runs an immediate scan on startup, then repeats every `scan_interval_minutes`.
- `--once` flag skips the scheduler and exits after one pass (suitable for cron jobs).

---

## 9. Dependencies

### Runtime (`requirements.txt`)
```
hindsight-client
apscheduler
pydantic
pyyaml
click
pymupdf          # PDF extraction
python-docx      # .docx
python-pptx      # .pptx
openpyxl         # .xlsx
pytesseract      # Tesseract OCR wrapper
Pillow           # image handling for pytesseract
requests         # file upload (multipart) to Hindsight REST API
```

### Dev (`requirements-dev.txt`)
```
pytest
pytest-cov
responses        # HTTP mocking for ingester tests
pytest-tmp-path  # included in pytest stdlib
```

### System dependency (optional)
- **Tesseract OCR** is only needed as a fallback for image files when the Hindsight native upload fails. If Tesseract is not installed, image upload errors are logged as warnings and the file is skipped rather than crashing.
  - Ubuntu/Debian: `sudo apt install tesseract-ocr`
  - macOS: `brew install tesseract`

---

## 10. Testing Plan

### Unit tests (no network required)

| Test file | What it covers |
|---|---|
| `test_scanner.py` | folder walk finds correct files; change detection returns only new/modified; deleted files are handled |
| `test_extractor.py` | each extractor returns non-empty text from fixture files; XLSX produces tabular text; image OCR produces readable text |
| `test_manifest.py` | insert, lookup, update, and delete of manifest records; SHA-256 comparison logic |
| `test_ingester.py` | `responses` mock intercepts HTTP calls; verifies correct endpoint, bank_id, document_id, context header; tests async flag |

### Integration tests (requires local Hindsight)
- `tests/integration/test_e2e.py` — runs a full scan→ingest cycle against `http://localhost:8888` and verifies document appears via the Documents API.
- Skipped automatically when `HINDSIGHT_INTEGRATION=1` env var is not set.

### Coverage target: ≥ 85% on `hindsight_ingest/`

### Test commands
```bash
# Unit tests only
pytest tests/ -v --ignore=tests/integration

# With coverage
pytest tests/ --ignore=tests/integration --cov=hindsight_ingest --cov-report=term-missing

# Integration (requires running Hindsight)
HINDSIGHT_INTEGRATION=1 pytest tests/integration/ -v
```

---

## 11. README Outline

1. **Overview** — what it does, diagram
2. **Prerequisites** — Python 3.11+, Tesseract, running Hindsight Docker instance
3. **Installation** — `pip install -r requirements.txt`
4. **Configuration** — walk through `config.yaml` knobs
5. **Running** — `python main.py`, `--once`, `--interval`
6. **Supported file types**
7. **Tesseract setup** (platform-specific)
8. **Testing**
9. **GitHub Actions CI** badge

---

## 12. Implementation Phases

| Phase | Deliverable | Est. effort |
|---|---|---|
| 1 | Project scaffold, config model, CLI skeleton | 1–2 hrs |
| 2 | Scanner + manifest (SQLite, SHA-256) | 1–2 hrs |
| 3 | Extractors (all formats + Tesseract) | 2–3 hrs |
| 4 | Ingester (SDK retain + native file upload) | 1–2 hrs |
| 5 | APScheduler integration + `--once` flag | 1 hr |
| 6 | Unit tests + fixtures | 2–3 hrs |
| 7 | README + GitHub repo init + push | 1 hr |
| **Total** | | **~9–14 hrs** |

---

## 13. Resolved Decisions

| # | Question | Decision |
|---|---|---|
| 1 | Repo name | `hindsight-scan-ingest` |
| 2 | API key | Optional (blank = unauthenticated local Docker); field present for cloud deployments |
| 3 | OCR | Hindsight native upload is primary; Tesseract is automatic fallback on image upload failure |
| 4 | XLSX | Always local extraction via openpyxl |
| 5 | Chunking | Knob `local_chunking_enabled` (default: `false`); Hindsight handles chunking by default |
