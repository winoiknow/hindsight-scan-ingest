from pathlib import Path

import pytest

from hindsight_ingest._utils import sha256_file
from hindsight_ingest.config import Config
from hindsight_ingest.manifest import Manifest, ManifestEntry
from hindsight_ingest.scanner import scan_for_changes


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    return d


@pytest.fixture
def manifest(tmp_path):
    m = Manifest(tmp_path / "manifest.db")
    yield m
    m.close()


def make_config(folder, **kwargs):
    return Config(folders=[str(folder)], supported_extensions=[".txt"], **kwargs)


def test_new_file_detected(folder, manifest):
    (folder / "a.txt").write_text("hello")
    config = make_config(folder)
    changed = scan_for_changes(config, manifest)
    assert len(changed) == 1
    assert changed[0][0].name == "a.txt"


def test_unchanged_file_skipped(folder, manifest):
    f = folder / "b.txt"
    f.write_text("content")
    manifest.upsert(ManifestEntry(str(f), sha256_file(f), "doc1", "2024-01-01T00:00:00+00:00"))
    changed = scan_for_changes(config=make_config(folder), manifest=manifest)
    assert changed == []


def test_modified_file_detected(folder, manifest):
    f = folder / "c.txt"
    f.write_text("original")
    manifest.upsert(ManifestEntry(str(f), "stale_hash", "doc1", "2024-01-01T00:00:00+00:00"))
    changed = scan_for_changes(config=make_config(folder), manifest=manifest)
    assert len(changed) == 1
    assert changed[0][0] == f


def test_unsupported_extension_skipped(folder, manifest):
    (folder / "binary.exe").write_bytes(b"\x00\x01\x02")
    changed = scan_for_changes(config=make_config(folder), manifest=manifest)
    assert changed == []


def test_missing_folder_skipped(tmp_path):
    config = Config(folders=[str(tmp_path / "ghost")], supported_extensions=[".txt"])
    manifest = Manifest(tmp_path / "m.db")
    changed = scan_for_changes(config, manifest)
    assert changed == []
    manifest.close()


def test_multiple_folders(tmp_path, manifest):
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir(); d2.mkdir()
    (d1 / "x.txt").write_text("x")
    (d2 / "y.txt").write_text("y")
    config = Config(folders=[str(d1), str(d2)], supported_extensions=[".txt"])
    changed = scan_for_changes(config, manifest)
    names = {p.name for p, _ in changed}
    assert names == {"x.txt", "y.txt"}


def test_hash_returned_matches_file(folder, manifest):
    f = folder / "d.txt"
    f.write_text("data")
    changed = scan_for_changes(config=make_config(folder), manifest=manifest)
    assert changed[0][1] == sha256_file(f)
