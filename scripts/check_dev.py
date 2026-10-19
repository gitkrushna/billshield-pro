"""M1 development infrastructure evidence. No credentials or signed URLs are emitted."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import traceback
import zlib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import psycopg
from billshield.db import AuthorizationError, TenantSession
from billshield.storage import InvalidUpload, S3ObjectStorage
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]


def fixture_png(label: str) -> bytes:
    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"tEXt", b"Comment\0M1 TEST FIXTURE: " + label.encode("ascii"))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff"))
        + chunk(b"IEND", b"")
    )


def check(upload: bool):
    load_dotenv(ROOT / ".env.local")
    ref = os.environ["APPROVED_DEV_PROJECT_REF"]
    project = os.environ["SUPABASE_PROJECT_URL"]
    assert urlsplit(project).hostname == f"{ref}.supabase.co", "Unapproved project"
    for key in ("DATABASE_URL", "MIGRATION_DATABASE_URL"):
        uri = urlsplit(os.environ[key])
        assert uri.username.endswith("." + ref) and uri.port == 5432, (
            "Unapproved dev pooler"
        )
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "project": "billshield-dev",
        "checks": [],
    }
    with httpx.Client(timeout=20, follow_redirects=False) as http:
        jwks = http.get(os.environ["AUTH_JWKS_URL"])
        jwks.raise_for_status()
        keys = jwks.json()["keys"]
        assert keys and all(k["kty"] in ("EC", "RSA") and "d" not in k for k in keys)
        report["checks"].append(
            "Public JWKS exposes asymmetric verification keys; no private key retrieved"
        )

        with psycopg.connect(
            os.environ["MIGRATION_DATABASE_URL"], connect_timeout=15
        ) as migration:
            bucket = migration.execute(
                "SELECT public,file_size_limit,allowed_mime_types FROM storage.buckets WHERE id=%s",
                ("billshield-uploads",),
            ).fetchone()
            assert bucket and bucket[0] is False and bucket[1] == 10485760
            assert set(bucket[2]) == {"image/png", "image/jpeg", "application/pdf"}
            coverage = migration.execute(
                "SELECT count(*),bool_or(complete),count(verified_through) FROM billshield.data_coverage"
            ).fetchone()
            assert coverage == (12, False, 0)
            snapshot = migration.execute(
                "SELECT id,content_sha256 FROM billshield.law_snapshots ORDER BY id"
            ).fetchall()
            report["snapshots"] = [{"id": s[0], "sha256": s[1]} for s in snapshot]
        report["checks"].append(
            "Bucket is private, 10 MiB, PDF/PNG/JPEG only; coverage remains uncertified"
        )

        storage = S3ObjectStorage(
            os.environ["S3_ENDPOINT_URL"],
            os.environ["S3_REGION"],
            os.environ["S3_ACCESS_KEY_ID"],
            os.environ["S3_SECRET_ACCESS_KEY"],
        )
        storage.s3.head_bucket(Bucket=storage.bucket)
        report["checks"].append(
            "The one server-only S3 credential pair connects to the approved bucket"
        )
        if upload:
            with psycopg.connect(  # noqa: SIM117 - keep rollback scope explicit
                os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=15
            ) as conn:
                with conn.transaction(force_rollback=True):
                    flags = conn.execute(
                        "SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                    ).fetchone()
                    assert flags == {
                        "name": "billshield_app",
                        "rolsuper": False,
                        "rolbypassrls": False,
                    }
                    scopes = []
                    for label in ("A", "B"):
                        subject = "m1-storage-fixture-" + uuid4().hex
                        user = conn.execute(
                            "SELECT billshield.identity_for_subject(%s,%s,%s) AS id",
                            (
                                "https://fixture.invalid",
                                subject,
                                subject + "@fixture.invalid",
                            ),
                        ).fetchone()["id"]
                        conn.execute(
                            "SELECT set_config('app.user_id',%s,true)", (str(user),)
                        )
                        org = conn.execute(
                            "SELECT billshield.create_org(%s) AS id",
                            ("M1 TEST FIXTURE: storage " + label,),
                        ).fetchone()["id"]
                        scopes.append(TenantSession(conn, user, org, "owner"))

                    def activate(scope):
                        conn.execute(
                            "SELECT set_config('app.user_id',%s,true)",
                            (str(scope.user_id),),
                        )
                        conn.execute(
                            "SELECT set_config('app.org_id',%s,true)",
                            (str(scope.org_id),),
                        )

                    a, b = scopes
                    activate(a)
                    original, replacement = fixture_png("A"), fixture_png("B")
                    assert len(original) == len(replacement)
                    link = storage.create_upload(a, len(original), "image/png")
                    response = http.put(
                        link.url, content=original, headers=link.headers
                    )
                    assert response.status_code in (200, 201), "Presigned PUT failed"
                    digest = storage.finalize(a, link.file_id)
                    assert digest == hashlib.sha256(original).hexdigest()
                    first_download = storage.download_link(a, link.file_id)
                    assert http.get(first_download).content == original
                    response = http.put(
                        link.url, content=replacement, headers=link.headers
                    )
                    assert response.status_code in (200, 201)
                    assert http.get(first_download).content == original, (
                        "Old PUT changed inspected bytes"
                    )
                    key = conn.execute(
                        "SELECT object_key FROM billshield.files WHERE id=%s",
                        (link.file_id,),
                    ).fetchone()["object_key"]
                    unsigned = (
                        os.environ["S3_ENDPOINT_URL"].rstrip("/")
                        + "/"
                        + storage.bucket
                        + "/"
                        + key
                    )
                    assert http.get(unsigned).status_code in (400, 401, 403, 404)
                    activate(b)
                    try:
                        storage.download_link(b, link.file_id)
                    except AuthorizationError:
                        pass
                    else:
                        raise AssertionError("Cross-org access yielded a signed link")
                    activate(a)
                    bad = storage.create_upload(a, len(original), "image/png")
                    response = http.put(
                        bad.url, content=b"X" * len(original), headers=bad.headers
                    )
                    assert response.status_code in (200, 201)
                    try:
                        storage.finalize(a, bad.file_id)
                    except InvalidUpload:
                        pass
                    else:
                        raise AssertionError("Invalid signature accepted")
                    report["checks"].append(
                        "Actual presigned PUT, signature/type/size finalization and signed GET passed"
                    )
                    report["checks"].append(
                        "Unsigned S3 read denied; cross-org file cannot obtain a signed URL"
                    )
                    report["checks"].append(
                        "Original PUT cannot replace frozen inspected bytes; fake PNG signature rejected"
                    )
            report["fixture_policy"] = (
                "All DB fixture identities/orgs/files rolled back; three tiny S3 fixture objects retained privately in quarantine; no deletion performed"
            )
    report["status"] = "passed"
    (ROOT / "reports/dev_infrastructure.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "checks": len(report["checks"]),
                "storage_write_check": upload,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage-write-check", action="store_true")
    args = parser.parse_args()
    try:
        check(args.storage_write_check)
    except Exception as exc:  # noqa: BLE001 - never emit third-party credential diagnostics
        location = traceback.extract_tb(exc.__traceback__)[-1]
        raise SystemExit(
            f"Dev infrastructure check failed ({type(exc).__name__}, {Path(location.filename).name}:{location.lineno}); sensitive diagnostics suppressed"
        ) from None
