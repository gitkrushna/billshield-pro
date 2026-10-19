"""Verify browser-acquired official originals and ingest unreviewed page evidence.

No downloading, OCR, model calls, rate activation or current-law certification.
The importer preserves original files and the parent law snapshot unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import unicodedata
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "reference/manual_sources"
VERSION = "m2-browser-pages-v1"


def canonical(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def official_url(url: str) -> bool:
    """Accept only HTTPS government namespaces, never mirrors or lookalikes."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        return (
            parts.scheme == "https"
            and not parts.username
            and not parts.password
            and parts.port in (None, 443)
            and host.endswith((".gov.in", ".nic.in"))
        )
    except (TypeError, ValueError):
        return False


def page_text(text: str) -> str:
    # Canonical extraction is reproducible and quoted exactly by retrieval.
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def verify_entry(entry: dict, root: Path = SOURCE_ROOT) -> dict:
    if not isinstance(entry, dict):
        raise ValueError("invalid_entry")  # noqa: TRY004 - uniform rejection code contract
    source_id = entry.get("id", "")
    if not isinstance(source_id, str) or not re.fullmatch(
        r"[a-zA-Z0-9_-]{1,100}", source_id
    ):
        raise ValueError("invalid_id")
    if not official_url(entry.get("url", "")):
        raise ValueError("nonofficial_url")
    for field in (
        "title",
        "publisher",
        "document_type",
        "edition",
        "chapter",
        "section",
    ):
        if field in entry and not isinstance(entry[field], str):
            raise ValueError("invalid_metadata")
    if entry.get("issued_on"):
        try:
            date.fromisoformat(entry["issued_on"])
        except (TypeError, ValueError):
            raise ValueError("invalid_issued_date") from None
    try:
        retrieved = datetime.fromisoformat(entry["retrieved_at"])
        if retrieved.tzinfo is None:
            raise ValueError
    except (KeyError, AttributeError, TypeError, ValueError):
        raise ValueError("invalid_retrieval_date") from None
    expected = entry.get("sha256", "")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("invalid_sha256")
    try:
        file = (root / entry["file"]).resolve()
        file.relative_to(root.resolve())
    except (KeyError, TypeError, ValueError):
        raise ValueError("unsafe_file_path") from None
    if not file.is_file():
        raise ValueError("missing_file")
    data = file.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("hash_mismatch")
    if not data.startswith(b"%PDF-"):
        raise ValueError("not_pdf")
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ValueError("encrypted_pdf")
        if not reader.pages:
            raise ValueError("empty_pdf")
        pages = []
        for number, page in enumerate(reader.pages, 1):
            text = page_text(page.extract_text() or "")
            if "\x00" in text:
                raise ValueError("invalid_text")
            pages.append(
                {
                    "source_page": number,
                    "text_original": text,
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                }
            )
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 - malformed parsers fail closed without ingesting bytes
        raise ValueError("invalid_pdf") from None
    source_key = f"m2:{source_id}:{expected[:20]}"
    source = {
        "source_key": source_key,
        "title": entry.get("title", source_id),
        "url": entry["url"],
        "publisher": entry.get("publisher", urlsplit(entry["url"]).hostname),
        "authority_level": "official_original_unreviewed",
        "document_type": entry.get("document_type", "legal_document"),
        "edition": entry.get("edition", "unverified"),
        "issued_on": entry.get("issued_on"),
        "licence": "official_free_access_reuse_unverified",
        "local_file": file.relative_to(root.resolve()).as_posix(),
        "content_sha256": expected,
        "retrieved_at": retrieved.astimezone(UTC).isoformat(),
        "coverage_through": None,
        "retrieval_status": "original_verified_unreviewed",
        "notes": "Browser-acquired original; page text unreviewed. No currentness certification.",
    }
    for page in pages:
        page["source_key"] = source_key
    return {
        "id": source_id,
        "source": source,
        "pages": pages,
        "text_complete": all(p["text_original"].strip() for p in pages),
        "scope": {k: entry[k] for k in ("chapter", "section") if k in entry},
    }


def verify_manifest(path: Path, root: Path = SOURCE_ROOT) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = raw.get("sources") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ValueError("manifest_must_contain_sources_array")  # noqa: TRY004
    accepted, rejected, seen = [], [], set()
    for entry in entries:
        try:
            item = verify_entry(entry, root)
            if item["id"] in seen:
                raise ValueError("duplicate_id")
            seen.add(item["id"])
            accepted.append(item)
        except ValueError as exc:
            rejected.append(
                {
                    "id": entry.get("id") if isinstance(entry, dict) else None,
                    "reason": str(exc),
                }
            )
    return {"importer_version": VERSION, "accepted": accepted, "rejected": rejected}


def snapshot_manifest(
    verification: dict, parent_id: str, parent_sha: str
) -> tuple[dict, str, str]:
    manifest = {
        "importer_version": VERSION,
        "parent_snapshot_id": parent_id,
        "parent_sha256": parent_sha,
        "coverage_status": "incomplete_unverified_currentness",
        "amendment_notice": "amendments after 22 Sep 2025 not verified",
        "activated_rates": 0,
        "currentness_certified": False,
        "sources": [
            {
                "id": x["id"],
                "source": x["source"],
                "scope": x["scope"],
                "text_complete": x["text_complete"],
                "pages": [
                    {k: v for k, v in p.items() if k != "text_original"}
                    for p in x["pages"]
                ],
            }
            for x in sorted(verification["accepted"], key=lambda x: x["id"])
        ],
    }
    sha = digest(manifest)
    return manifest, "m2-browser-" + sha[:20], sha


def ingest(connection, verification: dict, parent_id: str) -> dict:
    from psycopg import sql
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb

    if not verification["accepted"]:
        raise ValueError("no_accepted_sources")

    def one(query, params=()):
        with connection.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(query, params).fetchone()

    def insert_immutable(table, record, keys):
        columns = list(record)
        where = sql.SQL(" AND ").join(
            sql.SQL("{}=%s").format(sql.Identifier(k)) for k in keys
        )
        existing = one(
            sql.SQL("SELECT {} FROM billshield.{} WHERE {}").format(
                sql.SQL(",").join(map(sql.Identifier, columns)),
                sql.Identifier(table),
                where,
            ),
            tuple(record[k] for k in keys),
        )
        if existing is not None:
            # Date/timestamp adapters return Python objects; normalize only these
            # transport types, never alter source text or source hashes.
            normalized = {
                k: v.isoformat() if hasattr(v, "isoformat") else v
                for k, v in existing.items()
            }
            expected = dict(record)
            if table == "source_documents":
                expected["retrieved_at"] = datetime.fromisoformat(
                    expected["retrieved_at"]
                ).isoformat()
            if normalized != expected:
                raise ValueError(f"immutable_record_conflict:{table}")
            return
        connection.execute(
            sql.SQL("INSERT INTO billshield.{} ({}) VALUES ({})").format(
                sql.Identifier(table),
                sql.SQL(",").join(map(sql.Identifier, columns)),
                sql.SQL(",").join(sql.Placeholder() for _ in columns),
            ),
            tuple(record[c] for c in columns),
        )

    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(1940181020)")
        parent = one(
            "SELECT content_sha256,source_keys FROM billshield.law_snapshots WHERE id=%s",
            (parent_id,),
        )
        if not parent:
            raise ValueError("missing_parent_snapshot")
        manifest, snapshot_id, sha = snapshot_manifest(
            verification, parent_id, parent["content_sha256"]
        )
        existing = one(
            "SELECT content_sha256,manifest_json FROM billshield.law_snapshots WHERE id=%s",
            (snapshot_id,),
        )
        if existing and (
            existing["content_sha256"] != sha or existing["manifest_json"] != manifest
        ):
            raise ValueError("immutable_snapshot_conflict")
        for item in verification["accepted"]:
            insert_immutable("source_documents", item["source"], ("source_key",))
            for page in item["pages"]:
                insert_immutable("source_pages", page, ("source_key", "source_page"))
        if not existing:
            connection.execute(
                "INSERT INTO billshield.law_snapshots(id,source_keys,coverage_status,notes,"
                "content_sha256,manifest_json) VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    snapshot_id,
                    sorted(
                        set(parent["source_keys"])
                        | {x["source"]["source_key"] for x in verification["accepted"]}
                    ),
                    "incomplete_unverified_currentness",
                    "Official originals and unreviewed page text; amendments after 22 Sep 2025 not verified",
                    sha,
                    Jsonb(manifest),
                ),
            )
            connection.execute(
                "INSERT INTO billshield.law_snapshot_members(snapshot_id,kind,record_id,record_sha256) "
                "SELECT %s,kind,record_id,record_sha256 FROM billshield.law_snapshot_members "
                "WHERE snapshot_id=%s",
                (snapshot_id, parent_id),
            )
            for item in verification["accepted"]:
                records = [
                    ("source_documents", item["source"]["source_key"], item["source"])
                ]
                records.extend(
                    ("source_pages", f"{p['source_key']}|{p['source_page']}", p)
                    for p in item["pages"]
                )
                for kind, record_id, record in records:
                    connection.execute(
                        "INSERT INTO billshield.law_snapshot_members"
                        "(snapshot_id,kind,record_id,record_sha256) VALUES(%s,%s,%s,%s)",
                        (snapshot_id, kind, record_id, digest(record)),
                    )
    return {"snapshot_id": snapshot_id, "content_sha256": sha, "manifest": manifest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=SOURCE_ROOT / "browser_sources.json"
    )
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--parent-snapshot")
    args = parser.parse_args()
    try:
        verification = verify_manifest(args.manifest)
        result = {
            "mode": "verified",
            "accepted": len(verification["accepted"]),
            "page_count": sum(len(x["pages"]) for x in verification["accepted"]),
            "rejected": verification["rejected"],
            "activated_rates": 0,
        }
        if not args.inspect_only:
            import psycopg
            from dotenv import load_dotenv

            load_dotenv(ROOT / ".env.local", override=False)
            parent = (
                args.parent_snapshot
                or json.loads(
                    (ROOT / "data/corpus_manifest.json").read_text(encoding="utf-8")
                )["snapshot_id"]
            )
            with psycopg.connect(
                os.environ["MIGRATION_DATABASE_URL"], connect_timeout=20
            ) as conn:
                imported = ingest(conn, verification, parent)
            result.update(mode="ingested", snapshot_id=imported["snapshot_id"])
        print(json.dumps(result, indent=2))
    except Exception as exc:  # noqa: BLE001 - suppress credential-bearing driver exceptions
        # Do not echo driver exceptions, connection settings or source text.
        raise SystemExit(
            f"M2 ingestion failed ({type(exc).__name__}); inspect securely"
        ) from None


if __name__ == "__main__":
    main()
