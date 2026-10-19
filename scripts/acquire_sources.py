"""Bounded official/free source acquisition; never upgrades legal coverage or seeds text."""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from inspect_corpus import inspect_pdf
from seed import ROOT

WCO = "https://www.wcoomd.org/-/media/wco/public/global/pdf/topics/nomenclature/instruments-and-tools/hs-nomenclature-2022/2022/"
TARGETS = [
    *[
        {
            "id": "wco_2022_" + code,
            "url": WCO + code + "_2022e.pdf?la=en",
            "publisher": "World Customs Organization",
            "scope": scope,
        }
        for code, scope in [
            ("0315", "Chapter 15"),
            ("0417", "Chapter 17"),
            ("0419", "Chapter 19"),
            ("0421", "Chapter 21"),
            ("0630", "Chapter 30"),
            ("0633", "Chapter 33"),
            ("0400", "Section IV"),
            ("0600", "Section VI"),
        ]
    ],
    {
        "id": "cbic_ct1_2017",
        "url": "https://cbic-gst.gov.in/hindi/pdf/central-tax-rate/Notification-for-CGST-rate-Schedule.pdf",
        "publisher": "CBIC / Government of India",
        "scope": "Notification 1/2017-CT(Rate) base schedules",
    },
    {
        "id": "cbic_ct12_2022",
        "url": "https://cbic-gst.gov.in/pdf/central-tax-rate/12_2022-ctr-eng.pdf",
        "publisher": "CBIC / Government of India",
        "scope": "Notification 12/2022-CT(Rate); amendment candidate for 2023 review",
    },
    *[
        {
            "id": "cbic_tariff_2025_ch" + chapter,
            "url": "https://www.cbic.gov.in/resources//htdocs-cbec/customs/cst2025-26/cst"
            + chapter
            + "-2025.pdf",
            "publisher": "CBIC / Government of India",
            "scope": "Indian Chapter "
            + chapter
            + "; candidate endpoint requires authentication of edition",
        }
        for chapter in ["15", "17", "19", "21", "30", "33"]
    ],
]


def fetch(target):
    if urlparse(target["url"]).hostname not in {
        "www.wcoomd.org",
        "cbic-gst.gov.in",
        "www.cbic.gov.in",
    }:
        raise ValueError("Only allowlisted official sources authorized")
    result = {
        **target,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "review_status": "unreviewed_not_seeded",
        "coverage_changed": False,
    }
    data = b""
    try:
        request = Request(
            target["url"], headers={"User-Agent": "BillShield-M1-research/1.0"}
        )
        with urlopen(request, timeout=18) as response:
            result.update(
                {
                    "status_code": response.status,
                    "final_url": response.url,
                    "content_type": response.headers.get("Content-Type"),
                }
            )
            data = response.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024:
            raise ValueError("Acquisition size bound exceeded")
    except HTTPError as exc:
        result["status_code"] = exc.code
        data = exc.read(1024 * 1024)
        result["error_type"] = "HTTPError"
    except Exception as exc:  # noqa: BLE001 - acquisition failures remain blocked evidence
        result.update(
            {"status": "blocked_download_failed", "error_type": type(exc).__name__}
        )
    if data:
        sha = hashlib.sha256(data).hexdigest()
        directory = ROOT / "reference/acquired" / sha
        directory.mkdir(parents=True, exist_ok=True)
        candidate = directory / "original.bin"
        if not candidate.exists():
            candidate.write_bytes(data)
        validation = inspect_pdf(candidate)
        result.update(validation)
        result["local_file"] = candidate.relative_to(ROOT).as_posix()
        if result.get("status_code") != 200:
            result["status"] = "quarantined_http_failure"
        if result["status"] == "validated_pdf":
            from pypdf import PdfReader

            page_index = []
            for number, page in enumerate(PdfReader(candidate).pages, 1):
                text = page.extract_text() or ""
                page_index.append(
                    {
                        "page": number,
                        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "characters": len(text),
                    }
                )
                # Private, exact page extraction; not copied to redistributable data.
                (directory / f"page-{number:03d}.txt").write_text(
                    text, encoding="utf-8"
                )
            result["page_index"] = page_index
        attempt_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        (directory / (target["id"] + "." + attempt_id + ".provenance.json")).write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=min(args.workers, 4)) as pool:
        results = list(pool.map(fetch, TARGETS))
    report = {
        "purpose": "M1 bounded acquisition, originals private; unreviewed and not production legal evidence",
        "sources": results,
        "remaining_gaps": [
            "No standalone section notes in WCO 2022 index for Sections III and V; Indian applicability still needs verification",
            "Complete authenticated Indian tariff chapter PDFs",
            "Complete 2017-2023 amendment chain and historical Goa SGST pairing; candidate documents are not replay certification",
        ],
        "coverage_complete": False,
    }
    (ROOT / "reports").mkdir(exist_ok=True)
    report_path = ROOT / "reports/acquisition.json"
    if report_path.exists():
        prior = json.loads(report_path.read_text(encoding="utf-8"))
        report["previous_attempts"] = (
            prior.get("previous_attempts", []) + prior["sources"]
        )
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "attempted": len(results),
                "validated_pdf": sum(
                    r.get("status") == "validated_pdf" for r in results
                ),
                "not_acquired": [
                    r["id"] for r in results if r.get("status") != "validated_pdf"
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
