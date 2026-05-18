from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from ._utils import stable_doc_id
from .chunker import chunk_text
from .config import Config
from .extractor import (
    extract_docx,
    extract_image_with_tesseract,
    extract_pdf,
    extract_pptx,
    extract_xlsx,
)
from .manifest import Manifest, ManifestEntry

logger = logging.getLogger(__name__)

_TEXT_EXTENSIONS = {".txt", ".md", ".log", ".csv"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"}


class Ingester:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._http = requests.Session()
        if config.api_key:
            self._http.headers["Authorization"] = f"Bearer {config.api_key}"

    def _base(self) -> str:
        return self.config.server_url.rstrip("/")

    # ── REST call ─────────────────────────────────────────────────────────────

    def _post_memories(self, items: list[dict]) -> bool:
        url = f"{self._base()}/v1/default/banks/{self.config.bank_id}/memories"
        body = {"items": items, "async": True}
        try:
            resp = self._http.post(url, json=body, timeout=60)
            resp.raise_for_status()
            return True
        except requests.HTTPError as exc:
            logger.error(
                "Memories POST HTTP %s: %s",
                exc.response.status_code,
                exc.response.text[:300],
            )
        except Exception as exc:
            logger.error("Memories POST failed: %s", exc)
        return False

    # ── Build item dict ───────────────────────────────────────────────────────

    def _item(self, content: str, doc_id: str) -> dict:
        item: dict = {"content": content, "document_id": doc_id}
        if self.config.source:
            item["context"] = self.config.source
        return item

    # ── Retain text (with optional local chunking) ────────────────────────────

    def _retain(self, text: str, base_doc_id: str) -> bool:
        cfg = self.config
        if cfg.local_chunking_enabled:
            chunks = chunk_text(text, cfg.chunk_size_tokens, cfg.chunk_overlap_tokens)
            if not chunks:
                return False
            items = [
                self._item(chunk, f"{base_doc_id}_c{i:04d}")
                for i, chunk in enumerate(chunks)
            ]
        else:
            items = [self._item(text, base_doc_id)]
        return self._post_memories(items)

    # ── Text extraction (all formats local) ───────────────────────────────────

    def _extract(self, path: Path) -> Optional[str]:
        ext = path.suffix.lower()

        if ext in _TEXT_EXTENSIONS:
            return path.read_text(encoding="utf-8", errors="replace")

        if ext == ".pdf":
            return extract_pdf(path)

        if ext == ".docx":
            return extract_docx(path)

        if ext == ".pptx":
            return extract_pptx(path)

        if ext == ".xlsx":
            return extract_xlsx(path)

        if ext in _IMAGE_EXTENSIONS:
            return extract_image_with_tesseract(path)

        # Unknown extension: try reading as plain text
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.error("Cannot read %s: %s", path.name, exc)
            return None

    # ── Public interface ──────────────────────────────────────────────────────

    def ingest(self, path: Path, file_hash: str, manifest: Manifest) -> bool:
        doc_id = stable_doc_id(path)

        text = self._extract(path)
        if not text or not text.strip():
            logger.warning("No text extracted from %s — skipping", path.name)
            return False

        success = self._retain(text, doc_id)
        if success:
            manifest.upsert(
                ManifestEntry(
                    file_path=str(path),
                    sha256=file_hash,
                    doc_id=doc_id,
                    ingested_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            logger.info("Ingested: %s", path)

        return success

    def close(self) -> None:
        self._http.close()
