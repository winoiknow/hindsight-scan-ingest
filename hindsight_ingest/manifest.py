from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ManifestEntry:
    file_path: str
    sha256: str
    doc_id: str
    ingested_at: str


class Manifest:
    def __init__(self, db_path: Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                file_path   TEXT PRIMARY KEY,
                sha256      TEXT NOT NULL,
                doc_id      TEXT NOT NULL,
                ingested_at TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def get(self, file_path: str) -> Optional[ManifestEntry]:
        row = self._conn.execute(
            "SELECT file_path, sha256, doc_id, ingested_at FROM files WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        return ManifestEntry(*row) if row else None

    def upsert(self, entry: ManifestEntry) -> None:
        self._conn.execute(
            """
            INSERT INTO files (file_path, sha256, doc_id, ingested_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                sha256      = excluded.sha256,
                doc_id      = excluded.doc_id,
                ingested_at = excluded.ingested_at
            """,
            (entry.file_path, entry.sha256, entry.doc_id, entry.ingested_at),
        )
        self._conn.commit()

    def delete(self, file_path: str) -> None:
        self._conn.execute("DELETE FROM files WHERE file_path = ?", (file_path,))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
