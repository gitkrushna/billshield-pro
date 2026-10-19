"""Read-only reconciliation after two successful make seed runs."""

import json
import os
from datetime import UTC, datetime

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from seed import KEYS, ROOT, build_corpus, digest


def verify():
    load_dotenv(ROOT / ".env.local")
    tables, manifest, snapshot_id, sha = build_corpus()
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "snapshot_id": snapshot_id,
        "content_sha256": sha,
    }
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=15) as connection:
        counts = {
            name: connection.execute(
                sql.SQL("SELECT count(*) FROM billshield.{}").format(
                    sql.Identifier(name)
                )
            ).fetchone()[0]
            for name in tables
        }
        assert counts == manifest["counts"]
        actual_members = dict(
            connection.execute(
                "SELECT kind||'|'||record_id,record_sha256 FROM billshield.law_snapshot_members WHERE snapshot_id=%s",
                (snapshot_id,),
            ).fetchall()
        )
        expected_members = {
            name + "|" + "|".join(row[k] for k in KEYS[name]): digest(row)
            for name, rows in tables.items()
            for row in rows
        }
        assert actual_members == expected_members
        assert (
            connection.execute(
                "SELECT content_sha256 FROM billshield.law_snapshots WHERE id=%s",
                (snapshot_id,),
            ).fetchone()[0]
            == sha
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM billshield.rate_conditions"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM billshield.data_coverage WHERE complete OR verified_through IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM billshield.ruling_embeddings"
            ).fetchone()[0]
            == 0
        )
        runtime = [
            "products",
            "files",
            "checks",
            "reports",
            "audit_events",
            "own_rulings",
            "cached_analyses",
            "report_shares",
            "jobs",
        ]
        # No tenant context: a runtime connection must see none of any org's records.
        for name in runtime:
            assert (
                connection.execute(
                    sql.SQL("SELECT count(*) FROM billshield.{}").format(
                        sql.Identifier(name)
                    )
                ).fetchone()[0]
                == 0
            )
    report.update(
        status="passed",
        counts=counts,
        snapshot_members_verified=len(expected_members),
        conditions_seeded=0,
        coverage_certified=False,
        verified_through=None,
    )
    (ROOT / "reports/seed_integration.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "records_reconciled": len(expected_members),
                "snapshot_id": snapshot_id,
            }
        )
    )


if __name__ == "__main__":
    try:
        verify()
    except Exception as exc:  # noqa: BLE001 - never emit connection diagnostics
        raise SystemExit(
            f"Seed reconciliation failed ({type(exc).__name__}); details suppressed"
        ) from None
