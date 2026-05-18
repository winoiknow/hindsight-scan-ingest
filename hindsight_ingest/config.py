from __future__ import annotations

from pathlib import Path
from typing import List

import yaml
from pydantic import BaseModel, Field


class Config(BaseModel):
    server_url: str = "http://localhost:8888"
    api_key: str = ""
    bank_id: str = "default"
    source: str = "document-ingest"
    session: str = ""
    folders: List[str] = Field(default_factory=list)
    scan_interval_minutes: float = 15.0
    local_chunking_enabled: bool = False
    chunk_size_tokens: int = 1000
    chunk_overlap_tokens: int = 100
    supported_extensions: List[str] = Field(
        default_factory=lambda: [
            ".txt", ".md", ".log", ".csv",
            ".pdf", ".docx", ".pptx", ".xlsx",
            ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif",
        ]
    )


def load_config(path: Path) -> Config:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Config(**data)
