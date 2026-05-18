import json
from pathlib import Path

import pytest
import responses as resp_mock

from hindsight_ingest.config import Config
from hindsight_ingest.ingester import Ingester
from hindsight_ingest.manifest import Manifest

BASE = "http://localhost:8888"
BANK = "testbank"
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


def _last_body() -> dict:
    """Return the JSON body of the most recent mocked request."""
    return json.loads(resp_mock.calls[-1].request.body)


# ── Correct request shape ─────────────────────────────────────────────────────

@resp_mock.activate
def test_request_uses_items_wrapper(tmp_path, ingester, manifest):
    f = tmp_path / "doc.txt"
    f.write_text("Hello world")
    resp_mock.add(resp_mock.POST, MEMORIES_URL, json={"status": "ok"}, status=200)

    ingester.ingest(f, "fakehash", manifest)

    body = _last_body()
    assert "items" in body, "body must have top-level 'items' key"
    assert isinstance(body["items"], list)
    assert len(body["items"]) == 1
    assert "content" in body["items"][0]
    assert body["items"][0]["content"] == "Hello world"


@resp_mock.activate
def test_context_passed_in_item(tmp_path, ingester, manifest):
    f = tmp_path / "doc.txt"
    f.write_text("test")
    resp_mock.add(resp_mock.POST, MEMORIES_URL, json={}, status=200)

    ingester.ingest(f, "hash", manifest)

    item = _last_body()["items"][0]
    assert item.get("context") == "test-src"


@resp_mock.activate
def test_document_id_in_item(tmp_path, ingester, manifest):
    f = tmp_path / "doc.txt"
    f.write_text("test")
    resp_mock.add(resp_mock.POST, MEMORIES_URL, json={}, status=200)

    ingester.ingest(f, "hash", manifest)

    item = _last_body()["items"][0]
    assert "document_id" in item
    assert len(item["document_id"]) == 24  # stable_doc_id length


# ── Success / failure recording ───────────────────────────────────────────────

@resp_mock.activate
def test_success_recorded_in_manifest(tmp_path, ingester, manifest):
    f = tmp_path / "doc.txt"
    f.write_text("content")
    resp_mock.add(resp_mock.POST, MEMORIES_URL, json={}, status=200)

    assert ingester.ingest(f, "fakehash", manifest) is True
    assert manifest.get(str(f)) is not None


@resp_mock.activate
def test_failure_not_recorded_in_manifest(tmp_path, ingester, manifest):
    f = tmp_path / "doc.txt"
    f.write_text("content")
    resp_mock.add(resp_mock.POST, MEMORIES_URL, status=422)

    assert ingester.ingest(f, "fakehash", manifest) is False
    assert manifest.get(str(f)) is None


# ── XLSX (local extraction) ───────────────────────────────────────────────────

@resp_mock.activate
def test_xlsx_extracted_locally(tmp_path, ingester, manifest):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Score"])
    ws.append(["Alice", 99])
    path = tmp_path / "data.xlsx"
    wb.save(str(path))

    resp_mock.add(resp_mock.POST, MEMORIES_URL, json={}, status=200)

    assert ingester.ingest(path, "fakehash", manifest) is True
    content = _last_body()["items"][0]["content"]
    assert "Alice" in content


# ── Image with Tesseract ──────────────────────────────────────────────────────

@resp_mock.activate
def test_image_uses_tesseract(tmp_path, config, manifest, monkeypatch):
    png = tmp_path / "scan.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")

    monkeypatch.setattr(
        "hindsight_ingest.ingester.extract_image_with_tesseract",
        lambda _path: "ocr extracted text",
    )
    resp_mock.add(resp_mock.POST, MEMORIES_URL, json={}, status=200)

    ing = Ingester(config)
    result = ing.ingest(png, "fakehash", manifest)
    ing.close()

    assert result is True
    assert _last_body()["items"][0]["content"] == "ocr extracted text"


@resp_mock.activate
def test_image_no_ocr_text_skipped(tmp_path, config, manifest, monkeypatch):
    png = tmp_path / "blank.png"
    png.write_bytes(b"x")

    monkeypatch.setattr(
        "hindsight_ingest.ingester.extract_image_with_tesseract",
        lambda _path: None,
    )

    ing = Ingester(config)
    result = ing.ingest(png, "fakehash", manifest)
    ing.close()

    assert result is False
    assert manifest.get(str(png)) is None


# ── Chunking sends multiple items in one request ──────────────────────────────

@resp_mock.activate
def test_chunking_sends_items_in_single_request(tmp_path, manifest):
    cfg = Config(
        server_url=BASE,
        bank_id=BANK,
        local_chunking_enabled=True,
        chunk_size_tokens=3,
        chunk_overlap_tokens=1,
    )
    f = tmp_path / "big.txt"
    f.write_text("one two three four five six seven eight nine ten")

    resp_mock.add(resp_mock.POST, MEMORIES_URL, json={}, status=200)

    ing = Ingester(cfg)
    result = ing.ingest(f, "fakehash", manifest)
    ing.close()

    assert result is True
    # All chunks in a single POST, multiple items
    assert len(resp_mock.calls) == 1
    body = _last_body()
    assert len(body["items"]) > 1
    # Chunk doc IDs should be sequential
    doc_ids = [item["document_id"] for item in body["items"]]
    assert doc_ids[0].endswith("_c0000")
    assert doc_ids[1].endswith("_c0001")
