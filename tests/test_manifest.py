from pathlib import Path

import pytest

from hindsight_ingest.manifest import Manifest, ManifestEntry


@pytest.fixture
def manifest(tmp_path):
    m = Manifest(tmp_path / "test.db")
    yield m
    m.close()


def test_get_missing_returns_none(manifest):
    assert manifest.get("/nonexistent.txt") is None


def test_upsert_and_get(manifest):
    entry = ManifestEntry("/a.txt", "abc123", "docid1", "2024-01-01T00:00:00+00:00")
    manifest.upsert(entry)
    assert manifest.get("/a.txt") == entry


def test_upsert_updates_existing(manifest):
    manifest.upsert(ManifestEntry("/f.txt", "hash1", "doc1", "2024-01-01T00:00:00+00:00"))
    manifest.upsert(ManifestEntry("/f.txt", "hash2", "doc1", "2024-01-02T00:00:00+00:00"))
    result = manifest.get("/f.txt")
    assert result.sha256 == "hash2"
    assert result.ingested_at == "2024-01-02T00:00:00+00:00"


def test_delete_removes_entry(manifest):
    manifest.upsert(ManifestEntry("/f.txt", "hash1", "doc1", "2024-01-01T00:00:00+00:00"))
    manifest.delete("/f.txt")
    assert manifest.get("/f.txt") is None


def test_delete_nonexistent_is_noop(manifest):
    manifest.delete("/ghost.txt")  # should not raise
