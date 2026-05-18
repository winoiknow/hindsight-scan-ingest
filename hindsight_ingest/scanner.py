from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

from ._utils import sha256_file
from .config import Config
from .manifest import Manifest

logger = logging.getLogger(__name__)


def scan_for_changes(config: Config, manifest: Manifest) -> List[Tuple[Path, str]]:
    """Return (path, sha256) for every new or changed file across watched folders."""
    extensions = {ext.lower() for ext in config.supported_extensions}
    changed: List[Tuple[Path, str]] = []

    for folder_str in config.folders:
        folder = Path(folder_str)
        if not folder.is_dir():
            logger.warning("Configured folder does not exist, skipping: %s", folder)
            continue
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in extensions:
                continue
            file_hash = sha256_file(path)
            entry = manifest.get(str(path))
            if entry is None or entry.sha256 != file_hash:
                changed.append((path, file_hash))

    return changed
