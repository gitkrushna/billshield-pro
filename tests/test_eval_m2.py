"""Acceptance accounting cannot promote abstention or expected labels to law."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from billshield.pipeline import EnginePipeline
from test_engine import evidence as evidence  # noqa: PLC0414
from test_pipeline import RecordedModel

from scripts.eval_m2 import (
    BlindAudit,
    ObservedModel,
    aggregate_cost,
    evaluation_costs,
    fixtures,
    ingredients,
    score,
    verified_prices,
)


def test_only_explicit_ingredient_percentages_are_parsed():
    result = ingredients("100% coconut oil; no perfume or additives")
    assert [(part.name, part.proportion_pct) for part in result] == [
        ("coconut oil", Decimal(100))
    ]
    result = ingredients(
        "Arnica Montana, Cantharis, Pilocarpine and Cinchona in an oil medium; percentages unknown"
    )
    assert len(result) == 4
    assert all(part.proportion_pct is None for part in result)


def test_fixture_expectations_and_counterfactual_invoice_are_independent(tmp_path):
    rows = []
    for identifier in ("G1", "G2", "G3", "G4", "G5", "C1", "C2", "C3", "C4", "C5"):
        rows.append(
            {
                "id": identifier,
                "product": "Synthetic input",
                "composition": "Water and oil; proportions unknown",
                "form": "Liquid",
                "use": "Synthetic use",
                "bill_hsn": "33071010",
                "bill_rate_pct": "18" if identifier == "C1" else "5",
                "expected_hsn": "33071010",
                "source_snapshot_total_rate_pct": "5",
            }
        )
    path = tmp_path / "research.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    result = {row["id"]: row for row in fixtures(path)}
    assert len(result) == 18
    assert result["G1"]["expected_category"] == "conditional_on_facts_and_authority"
    assert result["G4"]["facts"].composition == ()
    assert result["CF_cream_to_foam"]["bill"].billed_rate_pct == Decimal(18)
    assert result["CF_cream_to_foam"]["expected_category"] == "Rate right, HSN wrong"
    assert result["CF_foam_to_cream"]["bill"].billed_rate_pct == Decimal(5)
    assert result["CF_foam_to_cream"]["expected_category"] == "Supported"


def test_price_band_uses_utc_and_marks_holiday_upper_bound():
    offpeak = verified_prices(datetime(2026, 10, 19, 12, tzinfo=UTC))
    peak = verified_prices(datetime(2026, 10, 19, 6, tzinfo=UTC))
    weekend = verified_prices(datetime(2026, 10, 18, 6, tzinfo=UTC))
    assert offpeak.cache_miss == weekend.cache_miss == Decimal("0.15")
    assert peak.cache_miss == Decimal("0.30")
    assert peak.estimate and "holiday" in peak.basis


def test_expected_category_does_not_hide_bad_rate_score(evidence):
    facts, corpus, proposals, context = evidence
    observer = ObservedModel(RecordedModel(facts, proposals[0]))
    issued = asyncio.run(
        EnginePipeline(observer).run(facts, corpus, context, candidate_chapters=("33",))
    )
    row = {
        "id": "synthetic",
        "group": "original_10",
        "expected_category": "Supported",
        "expected_code": "33071010",
        "expected_rate": "18",
    }
    result = score(row, issued, corpus, observer, live=True)
    assert result["status"] == "fail"
    assert result["scores"]["category"] == "pass"
    assert result["scores"]["code"] == "pass"
    assert result["scores"]["rate"] == "fail"


def test_structured_output_audit_exposes_proposals_but_never_raw_prompts(evidence):
    facts, corpus, proposals, context = evidence
    observer = ObservedModel(RecordedModel(facts, proposals[0]))
    issued = asyncio.run(
        EnginePipeline(observer).run(facts, corpus, context, candidate_chapters=("33",))
    )
    result = score(
        {
            "id": "synthetic",
            "group": "original_10",
            "expected_category": "Supported",
            "expected_code": "33071010",
            "expected_rate": "5",
        },
        issued,
        corpus,
        observer,
        live=True,
    )
    outputs = result["structured_model_outputs"]
    assert len(outputs) == 3
    assert {item["output"]["code"] for item in outputs} == {"33071010"}
    assert all(item["schema_valid"] and item["purpose"] == "blind" for item in outputs)
    assert all("messages" not in item and "content" not in item for item in outputs)

    invalid = ObservedModel(RecordedModel(facts, proposals[0]))
    invalid.model.numeric_rate = True
    asyncio.run(
        EnginePipeline(invalid).run(facts, corpus, context, candidate_chapters=("33",))
    )
    assert all(item["schema_valid"] is False for item in invalid.structured_outputs)
    assert all("output" not in item for item in invalid.structured_outputs)
    assert all(
        "input" not in error
        for item in invalid.structured_outputs
        for error in item["errors"]
    )


def test_blind_audit_matches_id_only_provider_missing_fact_response():
    response = BlindAudit.model_validate(
        {"code": "", "rule_ids": [], "missing_facts": ["composition"]}
    )
    assert response.model_dump(mode="json") == {
        "code": "",
        "rule_ids": [],
        "rate_entry_ids": [],
        "missing_facts": ["composition"],
    }
    assert "citations" not in BlindAudit.model_fields


def test_missing_evidence_is_blocked_even_when_abstention_expected(evidence):
    facts, corpus, proposals, context = evidence
    corpus = replace(corpus, sources={})
    observer = ObservedModel(RecordedModel(facts, proposals[0]))
    issued = asyncio.run(
        EnginePipeline(observer).run(facts, corpus, context, candidate_chapters=("33",))
    )
    result = score(
        {"id": "gap", "group": "corpus_gap", "expected_category": "Need more info"},
        issued,
        corpus,
        observer,
        live=True,
    )
    assert result["status"] == "blocked"
    assert result["source_gate_safety"] == "pass"
    assert result["model_calls"] == 0


def test_cost_per_completed_check_never_silently_zeros_unknown_cost():
    rows = [
        {"completed_non_abstain": True, "cost_usd": "0.001", "model_calls": 4},
        {"completed_non_abstain": True, "cost_usd": "0.003", "model_calls": 3},
    ]
    assert aggregate_cost(rows)["cost_per_completed_check_usd"] == "0.002"
    rows.append({"completed_non_abstain": True, "cost_usd": None, "model_calls": 1})
    assert aggregate_cost(rows)["cost_per_completed_check_usd"] is None
    assert aggregate_cost(rows)["total_cost_usd"] is None


def test_legal_check_cost_excludes_safety_baseline_and_injection_spend():
    legal = [
        {"completed_non_abstain": True, "cost_usd": "0.01", "model_calls": 3},
        {"completed_non_abstain": True, "cost_usd": "0.03", "model_calls": 4},
    ]
    injection = {
        "results": [
            {"completed_non_abstain": True, "cost_usd": "0.20", "model_calls": 6}
        ],
        "baseline": {"result": {"category": "Wrong"}, "cost_usd": "0.10"},
        "baseline_model_calls": 5,
    }
    costs = evaluation_costs(legal, injection)
    assert costs["cost_per_completed_check_usd"] == "0.02"
    assert costs["completed_checks"] == 2
    assert costs["legal_model_calls"] == 7
    assert costs["safety_evaluation_cost"]["total_cost_usd"] == "0.30"
    assert costs["safety_evaluation_cost"]["model_calls"] == 11
    assert costs["entire_run_cost"]["total_cost_usd"] == "0.34"
    assert costs["entire_run_cost"]["model_calls"] == 18
