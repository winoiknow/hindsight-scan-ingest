from __future__ import annotations

from typing import List


def chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Split text into overlapping word-count chunks."""
    words = text.split()
    if not words:
        return []
    step = max(1, chunk_size - overlap)
    chunks: List[str] = []
    start = 0
    while start < len(words):
        chunks.append(" ".join(words[start : start + chunk_size]))
        start += step
    return chunks
