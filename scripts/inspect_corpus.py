"""Verify immutable research file hashes and actual source formats; emit no source text."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from pypdf import PdfReader
from seed import RESEARCH, ROOT, build_corpus


def inspect_pdf(path):
    data = path.read_bytes()
    result = {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "magic_hex": data[:8].hex(),
    }
    if not data.startswith(b"%PDF-"):
        return {**result, "status": "quarantined_not_pdf", "pages": None}
    try:
        reader = PdfReader(path, strict=True)
        pages = len(reader.pages)
        # Read all page objects, not just the trailer's claimed count.
        for page in reader.pages:
            _ = page.mediabox
        return {**result, "status": "validated_pdf", "pages": pages}
    except Exception as exc:  # noqa: BLE001 - any parser failure quarantines untrusted input
        return {
            **result,
            "status": "quarantined_invalid_pdf",
            "pages": None,
            "error_type": type(exc).__name__,
        }


def inspect():
    expected = json.loads((RESEARCH / "SHA256SUMS.json").read_text(encoding="utf-8"))
    checks = []
    for name, sha in sorted(expected.items()):
        path = RESEARCH / name
        actual = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
        checks.append(
            {
                "path": name,
                "expected_sha256": sha,
                "actual_sha256": actual,
                "match": actual == sha,
            }
        )
    inventory = []
    for path in sorted(RESEARCH.rglob("*")):
        if path.is_file():
            inventory.append(
                {
                    "path": path.relative_to(RESEARCH).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    pdfs = [
        {"path": path.relative_to(RESEARCH).as_posix(), **inspect_pdf(path)}
        for path in sorted((RESEARCH / "sources").rglob("*.pdf"))
    ]
    tables, manifest, snapshot, sha = build_corpus()
    sources = []
    for source in tables["source_documents"]:
        if not source["local_file"]:
            continue
        path = RESEARCH / "sources" / source["local_file"]
        actual = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
        sources.append(
            {
                "source_key": source["source_key"],
                "path": source["local_file"],
                "matches_recorded_hash": actual == source["content_sha256"],
                "actual_sha256": actual,
            }
        )
    pairs = json.loads((RESEARCH / "data/test_pairs.json").read_text(encoding="utf-8"))
    return {
        "snapshot_id": snapshot,
        "content_sha256": sha,
        "hash_checks": checks,
        "all_manifest_hashes_match": all(c["match"] for c in checks),
        "inventory": inventory,
        "pdfs": pdfs,
        "pdf_status_counts": dict(Counter(p["status"] for p in pdfs)),
        "source_hash_checks": sources,
        "all_source_hashes_match": all(c["matches_recorded_hash"] for c in sources),
        "counts": manifest["counts"],
        "test_pair_count": len(pairs),
        "test_pairs_seeded": False,
        "legal_evals": "blocked: missing evidence; M2 not started",
        "quarantine_policy": "Original bytes preserved in private reference; quarantined PDFs never legal evidence or parsed as PDF.",
        "known_gaps": [
            "Complete Indian tariff notes/items 15/17/19/21/30/33",
            "Indian section notes",
            "2023 historical CGST/Goa SGST reconciliation",
            "Current Goa section 74A",
            "McNROE local PDF",
            "October 2026 currentness verification",
        ],
    }


if __name__ == "__main__":
    report = inspect()
    directory = ROOT / "reports"
    directory.mkdir(exist_ok=True)
    (directory / "corpus_inspection.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in [
                    "snapshot_id",
                    "all_manifest_hashes_match",
                    "all_source_hashes_match",
                    "pdf_status_counts",
                    "counts",
                ]
            }
        )
    )
    if not report["all_manifest_hashes_match"] or not report["all_source_hashes_match"]:
        raise SystemExit(1)
