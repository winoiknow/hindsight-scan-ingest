from pathlib import Path

import pytest
import responses as resp_mock

from hindsight_ingest.config import Config
from hindsight_ingest.ingester import Ingester
from hindsight_ingest.manifest import Manifest

BASE = "http://localhost:8888"
BANK = "testbank"
FILES_URL = f"{BASE}/v1/default/banks/{BANK}/files"
MEMORIES_URL = f"{BASE}/v1/default/banks/{BANK}/memories"


@pytest.fixture
def config():
    return Config(server_url=BASE, bank_id=BANK, source="test-src", session="ses1")


@pytest.fixture
def ingester(config):
    ing = Ingester(config)
    yield ing
    ing.close()


@pytest.fixture
def manifest(tmp_path):
    m = Manifest(tmp_path / "m.db")
    yield m
    m.close()


# ── Text file (native upload succeeds) ───────────────────────────────────────

@resp_mock.activate
def test_txt_native_upload_success(tmp_path, ingester, manifest):
    f = tmp_path / "doc.txt"
    f.write_text("Hello world")
    resp_mock.add(resp_mock.POST, FILES_URL, json={"status": "ok"}, status=200)

    assert ingester.ingest(f, "fakehash", manifest) is True
    assert manifest.get(str(f)) is not None


# ── Text file (native upload fails, falls back to text retain) ────────────────

@resp_mock.activate
def test_txt_fallback_to_text_retain(tmp_path, ingester, manifest):
    f = tmp_path / "doc.txt"
    f.write_text("fallback content")
    resp_mock.add(resp_mock.POST, FILES_URL, status=503)
    resp_mock.add(resp_mock.POST, MEMORIES_URL, json={"status": "ok"}, status=200)

    assert ingester.ingest(f, "fakehash", manifest) is True
    assert manifest.get(str(f)) is not None


# ── Image (native upload fails, Tesseract fallback) ──────────────────────────

@resp_mock.activate
def test_image_tesseract_fallback(tmp_path, config, manifest, monkeypatch):
    png = tmp_path / "scan.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")  # minimal PNG header stand-in

    resp_mock.add(resp_mock.POST, FILES_URL, status=500)
    resp_mock.add(resp_mock.POST, MEMORIES_URL, json={"status": "ok"}, status=200)

    monkeypatch.setattr(
        "hindsight_ingest.ingester.extract_image_with_tesseract",
        lambda _path: "ocr extracted text",
    )
    ing = Ingester(config)
    result = ing.ingest(png, "fakehash", manifest)
    ing.close()
    assert result is True
    assert manifest.get(str(png)) is not None


# ── Image (both paths fail) ───────────────────────────────────────────────────

@resp_mock.activate
def test_image_both_fail_not_recorded(tmp_path, config, manifest, monkeypatch):
    png = tmp_path / "bad.png"
    png.write_bytes(b"x")

    resp_mock.add(resp_mock.POST, FILES_URL, status=500)
    monkeypatch.setattr(
        "hindsight_ingest.ingester.extract_image_with_tesseract",
        lambda _path: None,
    )
    ing = Ingester(config)
    result = ing.ingest(png, "fakehash", manifest)
    ing.close()
    assert result is False
    assert manifest.get(str(png)) is None


# ── XLSX (always local extraction) ────────────────────────────────────────────

@resp_mock.activate
def test_xlsx_local_extraction(tmp_path, ingester, manifest):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Col", "Val"])
    ws.append(["A", 1])
    path = tmp_path / "data.xlsx"
    wb.save(str(path))

    resp_mock.add(resp_mock.POST, MEMORIES_URL, json={"status": "ok"}, status=200)

    assert ingester.ingest(path, "fakehash", manifest) is True


# ── Failed ingest not saved to manifest ───────────────────────────────────────

@resp_mock.activate
def test_failed_ingest_not_recorded(tmp_path, ingester, manifest):
    f = tmp_path / "nope.txt"
    f.write_text("content")
    resp_mock.add(resp_mock.POST, FILES_URL, status=503)
    resp_mock.add(resp_mock.POST, MEMORIES_URL, status=503)

    assert ingester.ingest(f, "fakehash", manifest) is False
    assert manifest.get(str(f)) is None


# ── Chunking enabled ──────────────────────────────────────────────────────────

@resp_mock.activate
def test_chunking_enabled_sends_multiple_retains(tmp_path, manifest):
    cfg = Config(
        server_url=BASE,
        bank_id=BANK,
        local_chunking_enabled=True,
        chunk_size_tokens=3,
        chunk_overlap_tokens=1,
    )
    ing = Ingester(cfg)

    f = tmp_path / "big.txt"
    f.write_text("one two three four five six seven eight nine ten")

    resp_mock.add(resp_mock.POST, FILES_URL, status=500)       # force text path
    for _ in range(5):
        resp_mock.add(resp_mock.POST, MEMORIES_URL, json={}, status=200)

    result = ing.ingest(f, "fakehash", manifest)
    ing.close()

    # Multiple memory POSTs should have been called
    memory_calls = [c for c in resp_mock.calls if "memories" in c.request.url]
    assert len(memory_calls) > 1
    assert result is True
