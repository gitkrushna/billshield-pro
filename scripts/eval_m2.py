"""Attempt the real M2 fixture matrix against verified acquired page evidence.

No recorded answer is promoted to legal evidence and no live model call is
made by this entry point. A source gate is a safety result, not a legal pass.
"""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

from billshield.corpus import corpus_from_verified_pages
from billshield.engine import BillFields, CheckContext, Ingredient, ProductFacts
from billshield.pipeline import EnginePipeline

from scripts.ingest_m2 import snapshot_manifest, verify_manifest

ROOT = Path(__file__).resolve().parents[1]
RELABELS = {
    "G2": "Supported",
    "G3": "Rate right, HSN wrong",
    "G4": "Need more info",
    "G5": "Rate right, HSN wrong",
    "C1": "Wrong",
    "C2": "Wrong",
    "C3": "Supported",
    "C4": "Wrong",
    "C5": "Supported",
}
CHAPTERS = {
    "G1": ("19", "21"),
    "G2": ("15",),
    "G3": ("30", "33"),
    "G4": ("30", "33"),
    "G5": ("17", "21"),
    "C1": ("33",),
    "C2": ("33",),
    "C3": ("25",),
    "C4": ("34",),
    "C5": ("34",),
}


class NoLiveModel:
    requested_model = "deepseek-flash"
    expected_version = "DeepSeek-V4.1-Flash-1017"

    def __init__(self):
        self.attempts = 0

    async def acomplete(self, messages, *, deadline_monotonic):
        self.attempts += 1
        raise RuntimeError(
            "Legal evidence gate passed; live evaluation is separately required"
        )


def fixtures(path: Path) -> list[dict]:
    research = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for original in research:
        identifier = original["id"]
        facts = ProductFacts(
            name=original["product"],
            composition=(Ingredient(name=original["composition"]),)
            if identifier != "G4"
            else (),
            form=original["form"],
            use=original["use"],
        )
        rows.append(
            {
                "id": identifier,
                "group": "original_10",
                "facts": facts,
                "bill": BillFields(
                    claimed_code=original["bill_hsn"],
                    billed_rate_pct=original["bill_rate_pct"],
                ),
                "chapters": CHAPTERS[identifier],
                "expected_category": RELABELS.get(
                    identifier, "conditional_on_facts_and_authority"
                ),
                "expected_code_research_only": original["expected_hsn"],
                "required_facts": ("composition", "preparation")
                if identifier == "G4"
                else (),
            }
        )
    rows.append(
        {
            "id": "Finish",
            "group": "finish",
            "facts": ProductFacts(
                name="Finish dishwasher salt; label and formulation not supplied",
                form="Salt product; exact formulation unknown",
                use="Dishwasher use",
            ),
            "bill": BillFields(claimed_code="34021190"),
            "chapters": ("25", "34"),
            "expected_category": "Need more info",
            "required_facts": ("composition",),
            "expected_code_research_only": "No national item inferred; legacy-code assertion needs authenticated edition",
        }
    )
    by_id = {row["id"]: row for row in rows}
    transitions = [
        ("CF_cream_to_foam", "C1", "C2"),
        ("CF_foam_to_cream", "C2", "C1"),
        ("CF_plain_to_caramel", "G5", "G5"),
        ("CF_caramel_to_plain", "G5", "G5"),
        ("CF_pure_to_chemical", "C3", "C3"),
        ("CF_chemical_to_pure", "C3", "C3"),
    ]
    for identifier, before, after in transitions:
        row = dict(by_id[before])
        row.update(
            id=identifier,
            group="counterfactual",
            facts=by_id[after]["facts"],
            expected_category="requires_revalidated_facts_and_legal_sources",
            expected_code_research_only=by_id[after]["expected_code_research_only"],
        )
        if identifier == "CF_plain_to_caramel":
            row["counterfactual_from"] = "plain salted popcorn"
        elif identifier == "CF_caramel_to_plain":
            row["facts"] = ProductFacts(
                name="Plain salted popcorn",
                form="Popped corn retail pack",
                composition=(
                    Ingredient(name="Popped corn and salt; no sugar coating"),
                ),
                use="Human snack consumption",
            )
            row["expected_code_research_only"] = (
                "Requires national heading/entry review for the plain variant"
            )
        elif identifier == "CF_pure_to_chemical":
            row["facts"] = ProductFacts(
                name="Salt product with unspecified chemical preparation",
                form="Granules",
                composition=(),
                use="Product use not supplied",
            )
            row["chapters"] = ("25", "34")
            row["required_facts"] = ("composition", "preparation")
            row["expected_code_research_only"] = (
                "Unknown chemical preparation; no code inferred"
            )
        elif identifier == "CF_chemical_to_pure":
            row["counterfactual_from"] = "salt product with chemical preparation"
        rows.append(row)
    rows.append(
        {
            "id": "corpus_gap",
            "group": "corpus_gap",
            "facts": ProductFacts(
                name="Unloaded textile product", form="Woven textile", use="Clothing"
            ),
            "bill": None,
            "chapters": ("62",),
            "expected_category": "Need more info",
            "required_facts": (),
            "expected_code_research_only": "No code inferred",
        }
    )
    return rows


async def evaluate(corpus, rows, as_of):
    results = []
    for row in rows:
        model = NoLiveModel()
        context = CheckContext(as_of=as_of, required_facts=row["required_facts"])
        issued = await EnginePipeline(model).run(
            row["facts"],
            corpus,
            context,
            candidate_chapters=row["chapters"],
            bill=row["bill"],
        )
        result = issued.result
        missing = result.reason in {
            "source_missing",
            "chapter_not_loaded",
            "coverage_incomplete",
            "code_not_verified",
            "rate_not_verified",
            "reasoning_not_verified",
            "code_precision_not_verified",
        }
        if missing:
            status, reason = "blocked", "missing evidence"
        elif (
            result.reason == "facts_missing"
            and row["expected_category"] == "Need more info"
        ):
            status, reason = "pass", "deciding facts correctly requested"
        elif model.attempts:
            status, reason = "blocked", "live model evaluation not run"
        else:
            status, reason = "fail", "unexpected engine gate"
        safety = (
            (
                result.category == "Need more info"
                and result.code is None
                and result.rate_pct is None
                and result.tax_difference is None
                and model.attempts == 0
            )
            if missing
            else None
        )
        results.append(
            {
                "id": row["id"],
                "group": row["group"],
                "status": status,
                "status_reason": reason,
                "expected_category": row["expected_category"],
                "expected_code_research_only": row["expected_code_research_only"],
                "actual_category": result.category,
                "actual_reason": result.reason,
                "actual_code": result.code,
                "actual_rate_pct": str(result.rate_pct)
                if result.rate_pct is not None
                else None,
                "missing_sources": list(result.missing_sources),
                "missing_facts": list(result.missing_facts),
                "source_gate_safety": "pass"
                if safety
                else ("fail" if safety is False else "not_applicable"),
                "model_calls": model.attempts,
                "cost_usd": issued.cost_usd,
                "cost_status": issued.cost_status,
                "scores": {
                    key: status
                    for key in ("code", "rate_entry", "category", "quote_validity")
                },
            }
        )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "reference/manual_sources/browser_sources.json",
    )
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 10, 19))
    parser.add_argument("--output", type=Path, default=ROOT / "reports/eval.json")
    args = parser.parse_args()
    parent = json.loads(
        (ROOT / "data/corpus_manifest.json").read_text(encoding="utf-8")
    )
    verification = verify_manifest(args.manifest)
    _, snapshot_id, sha = snapshot_manifest(
        verification, parent["snapshot_id"], parent["content_sha256"]
    )
    corpus = corpus_from_verified_pages(verification, snapshot_id)
    pair_path = ROOT / "reference/research/data/test_pairs.json"
    results = asyncio.run(evaluate(corpus, fixtures(pair_path), args.as_of))
    counts = dict(Counter(row["status"] for row in results))
    for status in ("pass", "fail", "blocked"):
        counts.setdefault(status, 0)
    safety = dict(Counter(row["source_gate_safety"] for row in results))
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": args.as_of.isoformat(),
        "law_snapshot_id": snapshot_id,
        "snapshot_sha256": sha,
        "fixture_sha256": hashlib.sha256(pair_path.read_bytes()).hexdigest(),
        "fixture_note": "Research inputs and labels are reviewable synthetic cases, not certified legal truth",
        "evaluation_mode": "actual_pipeline_verified_originals_no_live_model",
        "counts": counts,
        "source_gate_safety_counts": safety,
        "activated_reviewed_rules": 0,
        "activated_reviewed_codes": 0,
        "activated_reviewed_rates": 0,
        "sources_acquired": [
            {
                "id": item["id"],
                "url": item["source"]["url"],
                "sha256": item["source"]["content_sha256"],
                "pages": len(item["pages"]),
            }
            for item in verification["accepted"]
        ],
        "sources_rejected": verification["rejected"],
        "sources_blocked": sorted(
            {sid for row in results for sid in row["missing_sources"]}
        ),
        "model_calls": 0,
        "cost_per_completed_check_usd": None,
        "cost_note": "Not measured: no completed legal checks and no live model calls; unknown is not zero cost/check",
        "deferred": [
            "January 2023 replay",
            "74A, interest and penalty evidence",
            "full amendment register",
            "other party-specific rulings",
        ],
        "exposure_label": "excludes interest and penalty",
        "amendment_notice": "amendments after 22 Sep 2025 not verified",
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# M2 evaluation",
        "",
        f"Pass **{counts['pass']}**, fail **{counts['fail']}**, blocked **{counts['blocked']}**.",
        "",
        "Actual EnginePipeline runs against verified browser-acquired originals. Missing or unreviewed legal material remains blocked; source abstention is scored separately as safety.",
        "",
        f"Source gate safety: {safety}. Live model calls: 0. Cost per completed check: **not measured**.",
        "",
        "| Case | Legal status | Engine reason | Source gate safety |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| {row['id']} | {row['status']}: {row['status_reason']} | {row['actual_reason']} | {row['source_gate_safety']} |"
        for row in results
    )
    lines.extend(
        [
            "",
            "Acquired sources: "
            + ", ".join(item["id"] for item in verification["accepted"]),
            "",
            "Required evidence still missing or unreviewed: "
            + ", ".join(report["sources_blocked"]),
            "",
            "Deferred: " + "; ".join(report["deferred"]) + ".",
            "",
            "Exposure excludes interest and penalty. Amendments after 22 Sep 2025 not verified.",
        ]
    )
    args.output.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "counts": counts,
                "source_gate_safety_counts": safety,
                "sources_acquired": len(verification["accepted"]),
                "snapshot_id": snapshot_id,
            }
        )
    )


if __name__ == "__main__":
    main()
