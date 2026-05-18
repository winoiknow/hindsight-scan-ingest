# hindsight-scan-ingest

[![CI](https://github.com/ealborn/hindsight-scan-ingest/actions/workflows/ci.yml/badge.svg)](https://github.com/ealborn/hindsight-scan-ingest/actions/workflows/ci.yml)

A Python daemon that watches one or more local folders and continuously ingests documents into a [Vectorize Hindsight](https://hindsight.vectorize.io) instance. Supports every common document format, Tesseract OCR fallback for images, and a configurable scan interval.

```
Watched Folders → Scanner → Extractor → Hindsight API
                     ↑
               Manifest DB (SQLite)   ← change detection / idempotency
                     ↑
               APScheduler            ← configurable interval
```

---

## Supported file types

| Extension | Primary path | Fallback |
|---|---|---|
| `.txt` `.md` `.log` `.csv` | Hindsight native upload | Plain text read |
| `.pdf` | Hindsight native upload | PyMuPDF text extraction |
| `.docx` | Hindsight native upload | python-docx extraction |
| `.pptx` | Hindsight native upload | python-pptx extraction |
| `.xlsx` | Local openpyxl extraction | — |
| `.png` `.jpg` `.jpeg` `.tiff` `.bmp` `.gif` | Hindsight native upload (server OCR) | Tesseract OCR |

---

## Prerequisites

- Python 3.11+
- A running Vectorize Hindsight instance (Docker or cloud)
- **Tesseract OCR** *(optional — only needed as image fallback)*

### Start Hindsight with Docker

```bash
docker run -d -p 8888:8888 -p 9999:9999 vectorize/hindsight:latest
```

Control plane UI: http://localhost:9999

---

## Installation

```bash
git clone https://github.com/ealborn/hindsight-scan-ingest.git
cd hindsight-scan-ingest
pip install -r requirements.txt
```

### Tesseract (optional)

```bash
# Ubuntu / Debian
sudo apt install tesseract-ocr

# macOS
brew install tesseract
```

---

## Configuration

Copy and edit `config.yaml`:

```yaml
# Hindsight server
server_url: http://localhost:8888
api_key: ""                       # blank = unauthenticated (local Docker)
                                  # set for cloud deployments

# Memory routing — must match what the target agent reads
bank_id: "default"
source: "document-ingest"         # context label; shapes Hindsight fact extraction
session: ""                       # optional session tag stored in memory metadata

# Folders to watch
folders:
  - /path/to/your/docs
  # - /another/folder

# Scan interval (minutes)
scan_interval_minutes: 15

# Local chunking — off by default (Hindsight chunks server-side)
local_chunking_enabled: false
chunk_size_tokens: 1000
chunk_overlap_tokens: 100

# Supported extensions (edit to restrict or extend)
supported_extensions:
  - .txt
  - .md
  - .pdf
  - .docx
  - .xlsx
  # … etc.
```

---

## Running

```bash
# Continuous scan at the configured interval
python main.py

# Override the interval from the command line
python main.py --interval 5

# Single pass then exit (good for cron)
python main.py --once

# Add folders without editing config.yaml
python main.py --folder /docs/a --folder /docs/b

# Point at a cloud instance with an API key
python main.py --server-url https://api.hindsight.example.com --api-key sk-...

# Full help
python main.py --help
```

### CLI reference

| Flag | Default | Description |
|---|---|---|
| `--config PATH` | `config.yaml` | Path to config file |
| `--server-url URL` | from config | Hindsight server URL |
| `--api-key KEY` | from config | Bearer token for cloud auth |
| `--bank-id ID` | from config | Memory bank to write to |
| `--source TEXT` | from config | Context / source label |
| `--session TEXT` | from config | Session tag for metadata |
| `--folder PATH` | from config | Add a watched folder (repeatable) |
| `--interval MINUTES` | from config | Scan interval override |
| `--once` | off | Single pass then exit |
| `--db PATH` | `ingestion_manifest.db` | SQLite manifest path |

---

## How it works

1. **Scan** — walks each configured folder recursively, computes SHA-256 per file, compares against the SQLite manifest. Only new or changed files proceed.
2. **Ingest** — sends each file to Hindsight. Primary path is a native file upload (`POST /v1/default/banks/{bank_id}/files`). On failure, format-specific extractors pull text locally and submit via the memories API.
3. **Record** — on success, the file path + hash + doc ID are written to the manifest. Re-running the same file is a no-op until its content changes.
4. **Schedule** — APScheduler repeats the scan every `scan_interval_minutes`. Run with `--once` to use your own cron instead.

---

## Testing

```bash
pip install -r requirements-dev.txt

# Unit tests (no network required)
pytest tests/ -v

# With coverage
pytest tests/ --cov=hindsight_ingest --cov-report=term-missing

# Integration tests (requires running Hindsight at localhost:8888)
HINDSIGHT_INTEGRATION=1 pytest tests/integration/ -v
```

---

## Development

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements-dev.txt
pytest tests/ -v
```
