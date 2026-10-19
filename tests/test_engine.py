"""Synthetic evidence proves validators, never supplies legal ground truth."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from billshield.engine import (
    AMENDMENT_BANNER,
    BillFields,
    CheckContext,
    Citation,
    CodeEntry,
    Condition,
    Corpus,
    Coverage,
    Defense,
    Ingredient,
    LegalRule,
    ProductFacts,
    Proposal,
    RateEntry,
    SourceDocument,
    evaluate_proposals,
    mandatory_retrieval,
    tax_difference,
)
from pydantic import ValidationError

START = date(2025, 9, 22)
TODAY = date(2026, 10, 19)


@pytest.fixture
def evidence():
    facts = ProductFacts(
        name="Synthetic cream",
        composition=(Ingredient(name="water"),),
        form="cream",
        use="shaving",
    )
    citation = Citation(source_id="synthetic", page=1, quote="SYNTHETIC legal fixture")
    source = SourceDocument(
        "synthetic",
        {1: "SYNTHETIC legal fixture"},
        START,
        verified=True,
        official=True,
        kind="customs_tariff",
    )
    kinds = [f"gri_{i}" for i in range(1, 7)] + [
        "section_note",
        "chapter_note",
        "heading",
    ]
    rules = {
        kind: LegalRule(
            kind,
            kind,
            citation,
            START,
            chapters=("33",),
            reviewed=True,
            supports_codes=("33071010",) if kind == "heading" else (),
        )
        for kind in kinds
    }
    rates = {
        "central": RateEntry(
            "central",
            "3307",
            "CGST",
            "India",
            Decimal("2.5"),
            citation,
            START,
            conditions=(Condition("form", "cream"),),
            reviewed=True,
        ),
        "state": RateEntry(
            "state",
            "3307",
            "SGST",
            "Goa",
            Decimal("2.5"),
            citation,
            START,
            conditions=(Condition("form", "cream"),),
            reviewed=True,
        ),
    }
    corpus = Corpus(
        "synthetic-not-law",
        {"synthetic": source},
        rules,
        {
            "33071010": CodeEntry(
                "33071010", citation, START, authenticated_national=True
            )
        },
        rates,
        (Coverage("33", "Goa", START),),
        required_source_ids={"33": ("synthetic",)},
        mandatory_rule_ids={"33": tuple(kinds)},
    )
    proposal = Proposal(
        code="33071010",
        rule_ids=("heading",),
        rate_entry_ids=("central", "state"),
        citations=(citation,),
    )
    return facts, corpus, [proposal] * 3, CheckContext(TODAY)


def decide(evidence, **kwargs):
    facts, corpus, proposals, context = evidence
    return evaluate_proposals(facts, proposals, corpus, context, **kwargs)


def test_blind_contract_rejects_bill_query_and_numeric_rate():
    for forbidden in ("claimed_code", "bill", "raw_upload", "query"):
        with pytest.raises(ValidationError):
            ProductFacts(name="x", form="cream", use="shaving", **{forbidden: "2501"})
    with pytest.raises(ValidationError):
        Proposal(code="3307", rule_ids=(), rate_pct="5")
    with pytest.raises(ValidationError):
        ProductFacts(
            name="x",
            form="x",
            use="x",
            composition=[
                {"name": "water", "proportion_pct": "90"},
                {"name": "oil", "proportion_pct": "20"},
            ],
        )


def test_decimal_components_and_tax_gap(evidence):
    result = decide(
        evidence,
        bill=BillFields(
            claimed_code="33071010", billed_rate_pct="18", taxable_value="1234.56"
        ),
    )
    assert result.category == "Wrong"
    assert result.rate_pct == Decimal("5.0")
    assert result.tax_difference == Decimal("-160.49")
    assert result.exposure_label == "excludes interest and penalty"
    assert AMENDMENT_BANNER in result.banners
    assert result.confidence == "Medium"
    assert tax_difference(Decimal(100), Decimal(18), Decimal(5)) == Decimal("13.00")


def test_source_missing_is_not_legal_pass(evidence):
    facts, corpus, proposals, context = evidence
    corpus = replace(corpus, sources={})
    result = decide((facts, corpus, proposals, context))
    assert (result.category, result.reason) == ("Need more info", "source_missing")
    assert result.rate_pct is None and result.tax_difference is None


def test_full_mandatory_retrieval_and_missing_note(evidence):
    facts, corpus, proposals, context = evidence
    assert len(mandatory_retrieval(corpus, "33", context)) == 9
    corpus = replace(
        corpus, rules={k: v for k, v in corpus.rules.items() if k != "gri_6"}
    )
    assert decide((facts, corpus, proposals, context)).reason == "source_missing"


def test_no_national_authentication_no_eighth_digit(evidence):
    facts, corpus, proposals, context = evidence
    entry = replace(corpus.codes["33071010"], authenticated_national=False)
    corpus = replace(corpus, codes={entry.code: entry})
    assert decide((facts, corpus, proposals, context)).reason == "source_missing"


def test_exact_quote_and_postdated_source(evidence):
    facts, corpus, proposals, context = evidence
    source = replace(corpus.sources["synthetic"], pages={1: "Different text"})
    assert (
        decide(
            (facts, replace(corpus, sources={"synthetic": source}), proposals, context)
        ).reason
        == "source_missing"
    )
    source = replace(source, publication_date=date(2027, 1, 1))
    assert (
        decide(
            (facts, replace(corpus, sources={"synthetic": source}), proposals, context)
        ).reason
        == "source_missing"
    )


def test_condition_and_exclusion_must_validate(evidence):
    facts, corpus, proposals, context = evidence
    foam = facts.model_copy(update={"form": "foam"})
    assert decide((foam, corpus, proposals, context)).reason == "rate_not_verified"
    entry = replace(corpus.rates["state"], excluded_prefixes=("330710",))
    corpus = replace(corpus, rates={**corpus.rates, "state": entry})
    assert decide((facts, corpus, proposals, context)).reason == "rate_not_verified"


def test_wrong_state_component_and_expired_rate(evidence):
    facts, corpus, proposals, context = evidence
    for entry in (
        replace(corpus.rates["state"], jurisdiction="Maharashtra"),
        replace(corpus.rates["state"], effective_to=date(2025, 10, 1)),
    ):
        rates = {**corpus.rates, "state": entry}
        assert (
            decide((facts, replace(corpus, rates=rates), proposals, context)).reason
            == "rate_not_verified"
        )


def test_consistency_is_not_dispute_authority(evidence):
    facts, corpus, proposals, context = evidence
    proposals = proposals[:2] + [Proposal(code="33071090", rule_ids=("heading",))]
    result = decide((facts, corpus, proposals, context))
    assert (result.category, result.reason) == (
        "Need more info",
        "inconsistent_classification",
    )


def test_defense_requires_verified_applicable_rival(evidence):
    facts, corpus, proposals, context = evidence
    bill = BillFields(claimed_code="33071090", billed_rate_pct="5")
    defense = Defense("33071090", ("unverified_rival",))
    assert (
        decide(evidence, bill=bill, defense=defense).category == "Rate right, HSN wrong"
    )
    rival = LegalRule(
        "rival",
        "own_ruling",
        corpus.rules["heading"].citation,
        START,
        reviewed=True,
        status="in_force",
        applicable_party=False,
        supports_codes=("33071090",),
    )
    corpus = replace(corpus, rules={**corpus.rules, "rival": rival})
    defense = Defense("33071090", ("rival",))
    assert (
        decide((facts, corpus, proposals, context), bill=bill, defense=defense).category
        == "Rate right, HSN wrong"
    )
    corpus = replace(
        corpus, rules={**corpus.rules, "rival": replace(rival, applicable_party=True)}
    )
    result = decide((facts, corpus, proposals, context), bill=bill, defense=defense)
    assert result.category == "Disputable" and result.tax_difference is None


def test_missing_deciding_fact_strict_and_date_gates(evidence):
    facts, corpus, proposals, context = evidence
    assert (
        decide(
            (
                facts,
                corpus,
                proposals,
                replace(context, required_facts=("proportion:oil",)),
            )
        ).reason
        == "facts_missing"
    )
    assert (
        decide((facts, corpus, proposals, replace(context, mode="strict"))).reason
        == "coverage_incomplete"
    )
    assert (
        decide(
            (facts, corpus, proposals, replace(context, as_of=date(2023, 1, 1)))
        ).reason
        == "date_not_covered"
    )
    assert (
        decide(
            (facts, corpus, proposals, replace(context, supply="inter_state"))
        ).reason
        == "jurisdiction_not_covered"
    )


def test_unsupported_optional_claim_dropped(evidence):
    facts, corpus, proposals, context = evidence
    claim = Citation(source_id="synthetic", page=1, quote="invented legal assertion")
    proposals = [p.model_copy(update={"citations": (claim,)}) for p in proposals]
    result = decide((facts, corpus, proposals, context))
    assert result.category == "Supported" and result.confidence == "Low"
    assert result.dropped_claims == 3
    assert all(c.quote != claim.quote for c in result.citations)


def test_other_state_has_no_goa_total_or_exposure(evidence):
    facts, corpus, proposals, context = evidence
    result = decide(
        (facts, corpus, proposals, replace(context, jurisdiction="Maharashtra")),
        bill=BillFields(
            claimed_code="33071010", billed_rate_pct="5", taxable_value="1000"
        ),
    )
    assert result.code == "33071010" and result.rate_pct is None
    assert (
        result.tax_difference is None and result.reason == "state_component_not_loaded"
    )


def test_no_supported_claim_at_unverified_precision(evidence):
    facts, corpus, proposals, context = evidence
    heading = replace(corpus.rules["heading"], supports_codes=("3307",))
    code = replace(corpus.codes["33071010"], code="3307")
    corpus = replace(
        corpus, rules={**corpus.rules, "heading": heading}, codes={"3307": code}
    )
    proposals = [p.model_copy(update={"code": "3307"}) for p in proposals]
    result = decide(
        (facts, corpus, proposals, context),
        bill=BillFields(claimed_code="33071010", billed_rate_pct="5"),
    )
    assert (result.category, result.reason) == (
        "Need more info",
        "code_precision_not_verified",
    )


def test_other_state_classification_does_not_require_goa_rate(evidence):
    facts, corpus, proposals, context = evidence
    corpus = replace(corpus, rates={})
    result = decide(
        (facts, corpus, proposals, replace(context, jurisdiction="Maharashtra"))
    )
    assert result.code == "33071010" and result.rate_pct is None
    assert result.reason == "state_component_not_loaded"


def test_components_cannot_be_duplicated_and_source_must_be_official(evidence):
    facts, corpus, proposals, context = evidence
    state = replace(corpus.rates["state"], component="CGST", jurisdiction="India")
    result = decide(
        (
            facts,
            replace(corpus, rates={**corpus.rates, "state": state}),
            proposals,
            context,
        )
    )
    assert result.reason == "rate_component_missing"
    source = replace(corpus.sources["synthetic"], official=False)
    assert (
        decide(
            (facts, replace(corpus, sources={"synthetic": source}), proposals, context)
        ).reason
        == "source_missing"
    )


def test_rate_only_invoice_is_still_compared(evidence):
    result = decide(evidence, bill=BillFields(billed_rate_pct="18"))
    assert result.category == "Wrong" and result.rate_pct == Decimal(5)


def test_missing_review_threshold_is_conservative(evidence):
    assert decide(evidence).needs_review is True
