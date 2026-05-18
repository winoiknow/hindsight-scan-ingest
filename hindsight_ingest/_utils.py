import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_doc_id(file_path: Path) -> str:
    """Deterministic 24-char ID derived from the resolved file path."""
    return hashlib.sha256(str(file_path.resolve()).encode()).hexdigest()[:24]
