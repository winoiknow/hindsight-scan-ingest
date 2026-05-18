from __future__ import annotations

import logging
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

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

# Extensions that Hindsight handles natively server-side (non-binary text docs)
_TEXT_NATIVE = {".txt", ".md", ".log", ".csv"}
# Extensions that Hindsight handles natively but also have local extractor fallbacks
_BINARY_NATIVE: dict[str, Callable[[Path], Optional[str]]] = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".pptx": extract_pptx,
}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"}


class Ingester:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._http = requests.Session()
        if config.api_key:
            self._http.headers["Authorization"] = f"Bearer {config.api_key}"

    def _base(self) -> str:
        return self.config.server_url.rstrip("/")

    # ------------------------------------------------------------------ #

    def _file_upload(self, path: Path, doc_id: str) -> bool:
        url = f"{self._base()}/v1/default/banks/{self.config.bank_id}/files"
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        params: dict = {
            "document_id": doc_id,
            "context": self.config.source,
            "update_mode": "replace",
            "async": "true",
        }
        if self.config.session:
            params["session"] = self.config.session
        try:
            with open(path, "rb") as fh:
                resp = self._http.post(
                    url,
                    params=params,
                    files={"file": (path.name, fh, mime)},
                    timeout=120,
                )
            resp.raise_for_status()
            return True
        except requests.HTTPError as exc:
            logger.warning("File upload HTTP %s for %s", exc.response.status_code, path.name)
        except Exception as exc:
            logger.warning("File upload failed for %s: %s", path.name, exc)
        return False

    def _text_retain(self, content: str, doc_id: str, source_path: Path) -> bool:
        url = f"{self._base()}/v1/default/banks/{self.config.bank_id}/memories"
        metadata: dict = {"file": str(source_path)}
        if self.config.session:
            metadata["session"] = self.config.session
        body = {
            "content": content,
            "document_id": doc_id,
            "context": self.config.source,
            "metadata": metadata,
            "update_mode": "replace",
            "async": True,
        }
        try:
            resp = self._http.post(url, json=body, timeout=60)
            resp.raise_for_status()
            return True
        except requests.HTTPError as exc:
            logger.error("Text retain HTTP %s for %s", exc.response.status_code, source_path.name)
        except Exception as exc:
            logger.error("Text retain failed for %s: %s", source_path.name, exc)
        return False

    def _retain_maybe_chunked(
        self, text: str, base_doc_id: str, source_path: Path
    ) -> bool:
        cfg = self.config
        if not cfg.local_chunking_enabled:
            return self._text_retain(text, base_doc_id, source_path)
        chunks = chunk_text(text, cfg.chunk_size_tokens, cfg.chunk_overlap_tokens)
        if not chunks:
            return False
        # Each chunk gets a unique doc_id; Hindsight upserts on re-ingestion.
        # Note: if a file shrinks between runs, surplus old chunk docs persist
        # in Hindsight until manually deleted — acceptable MVP trade-off.
        return all(
            self._text_retain(chunk, f"{base_doc_id}_c{i:04d}", source_path)
            for i, chunk in enumerate(chunks)
        )

    # ------------------------------------------------------------------ #

    def ingest(self, path: Path, file_hash: str, manifest: Manifest) -> bool:
        ext = path.suffix.lower()
        doc_id = stable_doc_id(path)
        success = False

        if ext == ".xlsx":
            try:
                text = extract_xlsx(path)
                success = self._retain_maybe_chunked(text, doc_id, path)
            except Exception as exc:
                logger.error("XLSX extraction failed for %s: %s", path.name, exc)

        elif ext in _TEXT_NATIVE:
            success = self._file_upload(path, doc_id)
            if not success:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    success = self._retain_maybe_chunked(text, doc_id, path)
                except Exception as exc:
                    logger.error("Text fallback failed for %s: %s", path.name, exc)

        elif ext in _BINARY_NATIVE:
            success = self._file_upload(path, doc_id)
            if not success:
                extractor = _BINARY_NATIVE[ext]
                text = extractor(path)
                if text:
                    success = self._retain_maybe_chunked(text, doc_id, path)
                else:
                    logger.error("No fallback text extracted for %s", path.name)

        elif ext in _IMAGE_EXTENSIONS:
            success = self._file_upload(path, doc_id)
            if not success:
                logger.info("Native upload failed; trying Tesseract OCR for %s", path.name)
                text = extract_image_with_tesseract(path)
                if text:
                    success = self._retain_maybe_chunked(text, doc_id, path)
                else:
                    logger.warning("Skipping %s — no OCR fallback text available", path.name)

        else:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                success = self._retain_maybe_chunked(text, doc_id, path)
            except Exception as exc:
                logger.error("Cannot read %s: %s", path.name, exc)

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
