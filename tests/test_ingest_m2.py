"""Verification failures must never become legal evidence or active rates."""

import hashlib
import io
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from scripts.ingest_m2 import (
    ingest,
    official_url,
    page_text,
    snapshot_manifest,
    verify_entry,
    verify_manifest,
)


def pdf_bytes(text="Official fixture evidence", encrypted=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=400)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 20 300 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("fixture password")
    data = io.BytesIO()
    writer.write(data)
    return data.getvalue()


@pytest.fixture
def source(tmp_path):
    original = pdf_bytes()
    (tmp_path / "tariff").mkdir()
    (tmp_path / "tariff/chapter15.pdf").write_bytes(original)
    record = {
        "id": "tariff15",
        "url": "https://www.cbic.gov.in/observed-browser-document.pdf",
        "file": "tariff/chapter15.pdf",
        "retrieved_at": "2026-10-19T12:00:00+05:30",
        "sha256": hashlib.sha256(original).hexdigest(),
        "document_type": "customs_tariff",
        "edition": "30 June 2025",
        "chapter": "15",
        "issued_on": "2025-06-30",
    }
    return tmp_path, record


def test_original_pages_hashed_and_snapshot_remains_unreviewed(source):
    root, record = source
    verified = verify_entry(record, root)
    assert verified["pages"][0]["text_original"] == "Official fixture evidence"
    assert (
        verified["pages"][0]["text_sha256"]
        == hashlib.sha256(b"Official fixture evidence").hexdigest()
    )
    assert verified["source"]["coverage_through"] is None
    assert verified["source"]["retrieval_status"] == "original_verified_unreviewed"
    assert verified["source"]["retrieved_at"] == "2026-10-19T06:30:00+00:00"
    verification = {"accepted": [verified]}
    first = snapshot_manifest(verification, "m1-parent", "a" * 64)
    assert first == snapshot_manifest(verification, "m1-parent", "a" * 64)
    manifest, snapshot_id, sha = first
    assert snapshot_id.startswith("m2-browser-") and len(sha) == 64
    assert manifest["activated_rates"] == 0 and not manifest["currentness_certified"]
    assert manifest["amendment_notice"] == "amendments after 22 Sep 2025 not verified"
    assert first != snapshot_manifest(verification, "another-parent", "b" * 64)


@pytest.mark.parametrize(
    "url",
    [
        "https://cbic.gov.in.third-party.example/document.pdf",
        "https://icai.org/notification.pdf",
        "https://wcoomd.org/tariff.pdf",
        "http://cbic.gov.in/document.pdf",
        "https://user:password@cbic.gov.in/document.pdf",
        "https://cbic.gov.in:8080/document.pdf",
        "file:///tmp/document.pdf",
    ],
)
def test_mirrors_lookalikes_and_insecure_origins_rejected(source, url):
    root, record = source
    assert not official_url(url)
    with pytest.raises(ValueError, match="nonofficial_url"):
        verify_entry({**record, "url": url}, root)


@pytest.mark.parametrize(
    "url",
    [
        "https://taxinformation.cbic.gov.in/observed/document",
        "https://statetax.goa.gov.in/document.pdf?download=1",
        "https://comtax.wb.gov.in/document.pdf",
        "https://www.indiacode.nic.in/observed",
        "https://egazette.gov.in/observed-document.pdf",
    ],
)
def test_government_namespace_urls_accepted(url):
    assert official_url(url)


def test_hash_mismatch_and_html_error_body_rejected(source):
    root, record = source
    file = root / record["file"]
    file.write_bytes(b"<html>temporarily unavailable</html>")
    with pytest.raises(ValueError, match="hash_mismatch"):
        verify_entry(record, root)
    record["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="not_pdf"):
        verify_entry(record, root)


@pytest.mark.parametrize(
    "content,reason",
    [
        (b"%PDF-1.7\nbroken-not-a-document", "invalid_pdf"),
        (pdf_bytes(encrypted=True), "encrypted_pdf"),
    ],
    ids=["malformed_pdf", "encrypted_pdf"],
)
def test_invalid_and_encrypted_pdfs_rejected(source, content, reason):
    root, record = source
    (root / record["file"]).write_bytes(content)
    record["sha256"] = hashlib.sha256(content).hexdigest()
    with pytest.raises(ValueError, match=reason):
        verify_entry(record, root)


def test_root_escape_and_missing_dates_rejected(source):
    root, record = source
    with pytest.raises(ValueError, match="unsafe_file_path"):
        verify_entry({**record, "file": "../outside.pdf"}, root)
    with pytest.raises(ValueError, match="invalid_retrieval_date"):
        verify_entry({**record, "retrieved_at": "2026-10-19"}, root)


def test_manifest_rejections_do_not_discard_valid_original(source):
    root, record = source
    manifest = root / "browser_sources.json"
    manifest.write_text(
        json.dumps(
            {
                "sources": [
                    record,
                    {
                        **record,
                        "id": "bad",
                        "url": "https://third-party.example/document.pdf",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    result = verify_manifest(manifest, root)
    assert len(result["accepted"]) == 1
    assert result["rejected"] == [{"id": "bad", "reason": "nonofficial_url"}]
    assert page_text("Cafe\u0301\r\nsecond") == "Caf\u00e9\nsecond"


def test_scanned_pages_preserved_without_invented_text(source):
    root, record = source
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    data = io.BytesIO()
    writer.write(data)
    (root / record["file"]).write_bytes(data.getvalue())
    record["sha256"] = hashlib.sha256(data.getvalue()).hexdigest()
    verified = verify_entry(record, root)
    assert not verified["text_complete"]
    assert verified["pages"][0]["text_original"] == ""


def test_database_import_idempotency_preserves_parent_and_rejects_rewrite(source):
    """All clearly labelled PDF fixture records and snapshots roll back."""
    import psycopg
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env.local", override=False)
    if os.getenv("RUN_DB_INTEGRATION") != "1":
        pytest.skip("blocked: DB integration not enabled")
    dsn = os.getenv("MIGRATION_DATABASE_URL")
    if not dsn:
        pytest.fail("blocked: migration database configuration missing")
    root, record = source
    record["id"] = "TEST_FIXTURE_" + uuid4().hex
    verification = {"accepted": [verify_entry(record, root)], "rejected": []}
    try:
        conn = psycopg.connect(dsn, connect_timeout=15)
    except psycopg.Error:
        pytest.fail("blocked: database unavailable", pytrace=False)
    with conn, conn.transaction(force_rollback=True):
        if not conn.execute("SELECT to_regclass('billshield.source_pages')").fetchone()[
            0
        ]:
            pytest.fail("blocked: source_pages migration missing")
        parent = conn.execute(
            "SELECT id,content_sha256,manifest_json FROM billshield.law_snapshots "
            "ORDER BY created_at,id LIMIT 1"
        ).fetchone()
        assert parent, "blocked: parent law snapshot missing"
        before_members = conn.execute(
            "SELECT count(*) FROM billshield.law_snapshot_members WHERE snapshot_id=%s",
            (parent[0],),
        ).fetchone()[0]
        first = ingest(conn, verification, parent[0])
        assert first == ingest(conn, verification, parent[0])
        assert (
            conn.execute(
                "SELECT id,content_sha256,manifest_json FROM billshield.law_snapshots WHERE id=%s",
                (parent[0],),
            ).fetchone()
            == parent
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM billshield.law_snapshot_members WHERE snapshot_id=%s",
                (parent[0],),
            ).fetchone()[0]
            == before_members
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM billshield.law_snapshot_members WHERE snapshot_id=%s",
                (first["snapshot_id"],),
            ).fetchone()[0]
            == before_members + 2
        )
        verification["accepted"][0]["pages"][0]["text_original"] = "tampered extraction"
        with pytest.raises(ValueError, match="immutable_record_conflict:source_pages"):
            ingest(conn, verification, parent[0])
