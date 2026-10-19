"""Deterministic, unreviewed research import. Never seeds customer/test fixtures."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "reference/research"
VERSION = "m1-research-import-v1"
KEYS = {
    "source_documents": ("source_key",),
    "hsn_codes": ("id",),
    "rate_entries": ("id",),
    "rate_scopes": ("rate_entry_id", "scope_type", "scope_code"),
    "classification_rules": ("id",),
    "rulings": ("id",),
    "data_coverage": ("scope_code", "corpus_type", "jurisdiction", "checked_on"),
}
SECTION_MAP = {
    "15": "III",
    "17": "IV",
    "19": "IV",
    "21": "IV",
    "25": "V",
    "30": "VI",
    "33": "VI",
    "34": "VI",
}


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def rows(name, research=RESEARCH):
    with (research / "data" / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def deduplicate(records, keys=("id",)):
    found = {}
    for row in records:
        key = tuple(row[k] for k in keys)
        if key in found and found[key] != row:
            raise ValueError(f"Conflicting duplicate record: {key}")
        found[key] = row
    return [found[k] for k in sorted(found)]


def derive_scope(row):
    """Only a complete grammar of codes and separators; exceptions stay raw."""
    raw = row["hsn_selector_raw"].strip()
    if raw.lower() == "any chapter":
        return [
            {
                "rate_entry_id": row["id"],
                "scope_type": "global",
                "scope_code": "*",
                "selector_status": "derived_unreviewed_conditions_still_apply",
            }
        ]
    code = r"(?:\d{8}|\d{6}|\d{4}(?:\s+\d{2}){0,2}|\d{2})"
    if not re.fullmatch(code + r"(?:\s*(?:,|or)\s*" + code + r")*", raw):
        return [
            {
                "rate_entry_id": row["id"],
                "scope_type": "raw",
                "scope_code": raw,
                "selector_status": "unparsed_requires_review",
            }
        ]
    result = []
    for token in re.split(r"\s*(?:,|or)\s*", raw):
        number = re.sub(r"\s", "", token)
        result.append(
            {
                "rate_entry_id": row["id"],
                "scope_type": {2: "chapter", 4: "heading", 6: "subheading", 8: "item"}[
                    len(number)
                ],
                "scope_code": number,
                "selector_status": "derived_unreviewed_conditions_still_apply",
            }
        )
    return result


def build_corpus(research=RESEARCH):
    original_hashes = json.loads(
        (research / "SHA256SUMS.json").read_text(encoding="utf-8")
    )
    for name, expected_sha in original_hashes.items():
        path = research / name
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha
        ):
            raise ValueError(f"Research checksum mismatch: {name}")
    base = rows("rate_entries.csv", research)
    extra = rows("turn2_rate_evidence.csv", research)
    rates = deduplicate(base + extra)
    sources = deduplicate(rows("source_documents.csv", research), ("source_key",))
    by_source = {r["source_key"]: r for r in sources}
    for source in sources:
        if source["local_file"]:
            path = research / "sources" / source["local_file"]
            if (
                not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest()
                != source["content_sha256"]
            ):
                raise ValueError(f"Source checksum mismatch: {source['source_key']}")
    for r in rates:
        if r["human_reviewed"].lower() != "false":
            raise ValueError("Research rate review state must remain false")
        r["jurisdiction"] = {"CGST": "IN", "SGST": "IN-GA"}[r["component"]]
    scopes = rows("rate_scopes.csv", research)
    covered = {r["rate_entry_id"] for r in scopes}
    for rate in rates:
        if rate["id"] not in covered:
            scopes.extend(derive_scope(rate))
    rules = deduplicate(
        rows("classification_rules.csv", research) + rows("gri_rules.csv", research)
    )
    for rule in rules:
        rule["effective_from"] = None
        rule["effective_to"] = None
        rule["publication_date"] = by_source[rule["source_key"]]["issued_on"] or None
    coverage = rows("data_coverage.csv", research)
    if any(r["complete"].lower() != "false" or r["verified_through"] for r in coverage):
        raise ValueError(
            "Uncertified coverage must remain false with no verified-through date"
        )
    tables = {
        "source_documents": sources,
        "hsn_codes": rows("hsn_codes.csv", research),
        "rate_entries": rates,
        "rate_scopes": scopes,
        "classification_rules": rules,
        "rulings": rows("rulings.csv", research),
        "data_coverage": coverage,
    }
    for table, records in tables.items():
        tables[table] = deduplicate(records, KEYS[table])
    expected = {
        "source_documents": 40,
        "hsn_codes": 308,
        "rate_entries": 292,
        "classification_rules": 49,
        "rulings": 1,
        "data_coverage": 12,
    }
    if any(len(tables[k]) != n for k, n in expected.items()):
        raise ValueError(
            "Corpus input counts changed: inspect and version importer before accepting"
        )
    input_files = [
        "source_documents.csv",
        "hsn_codes.csv",
        "rate_entries.csv",
        "turn2_rate_evidence.csv",
        "rate_scopes.csv",
        "classification_rules.csv",
        "gri_rules.csv",
        "rulings.csv",
        "data_coverage.csv",
    ]
    manifest = {
        "importer_version": VERSION,
        "inputs": {
            name: hashlib.sha256((research / "data" / name).read_bytes()).hexdigest()
            for name in input_files
        },
        "counts": {k: len(v) for k, v in tables.items()},
        "table_sha256": {k: digest(v) for k, v in tables.items()},
        "section_mapping": SECTION_MAP,
        "coverage_status": "incomplete_unverified_currentness",
        "fixtures_seeded": False,
        "rate_conditions_seeded": 0,
    }
    sha = digest(manifest)
    return tables, manifest, "m1-research-" + sha[:20], sha


def write_manifest(manifest, snapshot_id, sha):
    target = ROOT / "data/corpus_manifest.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(
        json.dumps(
            {"snapshot_id": snapshot_id, "content_sha256": sha, "manifest": manifest},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def seed(connection, tables, manifest, snapshot_id, sha):
    from psycopg import sql
    from psycopg.types.json import Jsonb

    def value(v):
        if v == "":
            return None
        if v == "False":
            return False
        if v == "True":
            return True
        return v

    with connection.transaction():
        # Concurrent seeds serialize; changed existing source bytes/records fail closed.
        connection.execute("SELECT pg_advisory_xact_lock(1940181019)")
        for chapter, section in sorted(SECTION_MAP.items()):
            connection.execute(
                "INSERT INTO billshield.section_chapters(chapter,section) VALUES (%s,%s) ON CONFLICT (chapter) DO NOTHING",
                (chapter, section),
            )
        for table, records in tables.items():
            columns = list(records[0])
            keys = KEYS[table]
            stage = sql.Identifier("m1_seed_" + table)
            target = sql.Identifier("billshield", table)
            column_sql = sql.SQL(",").join(map(sql.Identifier, columns))
            connection.execute(
                sql.SQL(
                    "CREATE TEMP TABLE {} (LIKE {} INCLUDING DEFAULTS) ON COMMIT DROP"
                ).format(stage, target)
            )
            with (
                connection.cursor() as cursor,
                cursor.copy(
                    sql.SQL("COPY {} ({}) FROM STDIN").format(stage, column_sql)
                ) as copy,
            ):
                for row in records:
                    copy.write_row(tuple(value(row[c]) for c in columns))
            join = sql.SQL(" AND ").join(
                sql.SQL("t.{} = s.{}").format(sql.Identifier(k), sql.Identifier(k))
                for k in keys
            )
            different = sql.SQL(" OR ").join(
                sql.SQL("t.{} IS DISTINCT FROM s.{}").format(
                    sql.Identifier(c), sql.Identifier(c)
                )
                for c in columns
            )
            if connection.execute(
                sql.SQL(
                    "SELECT EXISTS(SELECT 1 FROM {} t JOIN {} s ON {} WHERE {})"
                ).format(target, stage, join, different)
            ).fetchone()[0]:
                raise ValueError(
                    f"Existing {table} record conflicts with immutable research input"
                )
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} ({}) SELECT {} FROM {} ON CONFLICT ({}) DO NOTHING"
                ).format(
                    target,
                    column_sql,
                    column_sql,
                    stage,
                    sql.SQL(",").join(map(sql.Identifier, keys)),
                )
            )
        existing_snapshot = connection.execute(
            "SELECT content_sha256,manifest_json FROM billshield.law_snapshots WHERE id=%s",
            (snapshot_id,),
        ).fetchone()
        if existing_snapshot and (
            existing_snapshot[0] != sha or existing_snapshot[1] != manifest
        ):
            raise ValueError(
                "Existing law snapshot conflicts with deterministic content identity"
            )
        connection.execute(
            "INSERT INTO billshield.law_snapshots(id,source_keys,coverage_status,notes,content_sha256,manifest_json) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (
                snapshot_id,
                sorted(r["source_key"] for r in tables["source_documents"]),
                "incomplete_unverified_currentness",
                "Research import only; verification not established. No test/customer fixtures or condition predicates.",
                sha,
                Jsonb(manifest),
            ),
        )
        with connection.pipeline():
            for table, records in tables.items():
                for row in records:
                    record_id = "|".join(row[k] for k in KEYS[table])
                    connection.execute(
                        "INSERT INTO billshield.law_snapshot_members(snapshot_id,kind,record_id,record_sha256) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (snapshot_id, table, record_id, digest(row)),
                    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect-only", action="store_true")
    args = parser.parse_args()
    tables, manifest, snapshot_id, sha = build_corpus()
    write_manifest(manifest, snapshot_id, sha)
    if not args.inspect_only:
        import psycopg
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env.local", override=False)
        url = os.environ.get("MIGRATION_DATABASE_URL")
        if not url:
            raise SystemExit(
                "Missing migration DB configuration; no seed was attempted"
            )
        try:
            with psycopg.connect(url, connect_timeout=20) as connection:
                seed(connection, tables, manifest, snapshot_id, sha)
        except Exception as exc:  # noqa: BLE001 - connection exceptions must never expose DSNs
            # Never print driver connection errors, which may expose DSN credentials.
            raise SystemExit(
                f"Seed failed ({type(exc).__name__}); inspect securely"
            ) from None
    print(
        json.dumps(
            {
                "mode": "inspected" if args.inspect_only else "seeded",
                "snapshot_id": snapshot_id,
                "counts": manifest["counts"],
            }
        )
    )


if __name__ == "__main__":
    main()
