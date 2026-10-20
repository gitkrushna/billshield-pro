"""Evidence-first M2 decisions. No database, network, or provider dependencies.

A model proposes only identifiers and quotations. This module authenticates those
identifiers against a versioned corpus before calculating rates or a verdict.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MVP_START = date(2025, 9, 22)
AMENDMENT_BANNER = "amendments after 22 Sep 2025 not verified"
EXPOSURE_LABEL = "excludes interest and penalty"
AUTO_VERIFICATION_BANNER = "auto-verified, not professionally reviewed"
Category = Literal["Supported", "Rate right, HSN wrong", "Wrong", "Disputable", "Need more info"]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Ingredient(StrictInput):
    name: str = Field(min_length=1, max_length=200)
    proportion_pct: Decimal | None = Field(default=None, ge=0, le=100)


class ProductFacts(StrictInput):
    """Only factual product properties; invoice and user argument have no slot."""

    name: str = Field(min_length=1, max_length=200)
    composition: tuple[Ingredient, ...] = ()
    form: str = Field(min_length=1, max_length=200)
    use: str = Field(min_length=1, max_length=300)
    preparation: str | None = Field(default=None, max_length=300)
    packaging: str | None = Field(default=None, max_length=200)
    food_grade: bool | None = None
    medicinal_licence: bool | None = None

    @field_validator("composition")
    @classmethod
    def proportions_fit(cls, value: tuple[Ingredient, ...]) -> tuple[Ingredient, ...]:
        if sum((i.proportion_pct or Decimal(0) for i in value), Decimal(0)) > 100:
            raise ValueError("composition proportions exceed 100")
        return value


class BillFields(StrictInput):
    claimed_code: str | None = Field(default=None, pattern=r"^\d{4}(?:\d{2})?(?:\d{2})?$")
    billed_rate_pct: Decimal | None = Field(default=None, ge=0, le=100)
    taxable_value: Decimal | None = Field(default=None, ge=0)


class Citation(StrictInput):
    source_id: str
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)


class Proposal(StrictInput):
    """No rate numbers, bill fields, or free-form instructions accepted here."""

    code: str = Field(pattern=r"^\d{4}(?:\d{2})?(?:\d{2})?$")
    rule_ids: tuple[str, ...]
    rate_entry_ids: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()
    missing_facts: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    pages: dict[int, str]
    publication_date: date | None
    verified: bool = False
    official: bool = False
    kind: str = "legal"
    sha256: str | None = None


@dataclass(frozen=True)
class Condition:
    """An exact equality predicate on a structured factual field."""

    fact: str
    equals: str | bool | Decimal
    operator: Literal["equals", "contains", "not_contains"] = "equals"


@dataclass(frozen=True)
class LegalRule:
    rule_id: str
    kind: str  # gri_1 ... gri_6, section_note, chapter_note, heading, rival_heading, own_ruling
    citation: Citation
    effective_from: date | None
    effective_to: date | None = None
    chapters: tuple[str, ...] = ()
    conditions: tuple[Condition, ...] = ()
    reviewed: bool = False
    applicable_party: bool = False
    status: str = "unknown"
    supports_codes: tuple[str, ...] = ()
    auto_verified: bool = False


@dataclass(frozen=True)
class CodeEntry:
    code: str
    citation: Citation
    effective_from: date
    effective_to: date | None = None
    authenticated_national: bool = False


@dataclass(frozen=True)
class RateEntry:
    entry_id: str
    code_prefix: str
    component: Literal["CGST", "SGST", "IGST"]
    jurisdiction: str
    rate_pct: Decimal
    citation: Citation
    effective_from: date
    effective_to: date | None = None
    conditions: tuple[Condition, ...] = ()
    reviewed: bool = False
    excluded_prefixes: tuple[str, ...] = ()
    auto_verified: bool = False


@dataclass(frozen=True)
class Coverage:
    chapter: str
    jurisdiction: str
    effective_from: date
    effective_to: date | None = None
    complete: bool = False
    verified_through: date | None = None


@dataclass(frozen=True)
class Corpus:
    snapshot_id: str
    sources: dict[str, SourceDocument]
    rules: dict[str, LegalRule]
    codes: dict[str, CodeEntry]
    rates: dict[str, RateEntry]
    coverage: tuple[Coverage, ...]
    required_source_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)
    mandatory_rule_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)
    rival_chapters: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckContext:
    as_of: date
    jurisdiction: str = "Goa"
    supply: str = "intra_state"
    mode: Literal["demo", "strict"] = "demo"
    required_facts: tuple[str, ...] = ()
    own_ruling_ids: tuple[str, ...] = ()
    needs_review_threshold: Decimal | None = None


@dataclass(frozen=True)
class Defense:
    rival_code: str
    rule_ids: tuple[str, ...]


@dataclass(frozen=True)
class EngineResult:
    category: Category
    reason: str
    code: str | None = None
    rate_pct: Decimal | None = None
    rate_entry_ids: tuple[str, ...] = ()
    confidence: Literal["High", "Medium", "Low"] = "Low"
    citations: tuple[Citation, ...] = ()
    missing_facts: tuple[str, ...] = ()
    missing_sources: tuple[str, ...] = ()
    needs_review: bool = True
    tax_difference: Decimal | None = None
    exposure_label: str = EXPOSURE_LABEL
    banners: tuple[str, ...] = (AMENDMENT_BANNER,)
    dropped_claims: int = 0
    law_snapshot_id: str = ""


def active(start: date | None, end: date | None, as_of: date) -> bool:
    return start is not None and start <= as_of and (end is None or as_of <= end)


def valid_citation(citation: Citation, corpus: Corpus, as_of: date) -> bool:
    document = corpus.sources.get(citation.source_id)
    return bool(
        document
        and document.verified
        and document.official
        and document.publication_date is not None
        and document.publication_date <= as_of
        and citation.quote in document.pages.get(citation.page, "")
    )


def fact_value(facts: ProductFacts, name: str):
    """No arbitrary Python evaluation or executable rate predicates."""
    if name.startswith("proportion:"):
        ingredient = name.removeprefix("proportion:").casefold()
        return next(
            (i.proportion_pct for i in facts.composition if i.name.casefold() == ingredient), None
        )
    if name not in ProductFacts.model_fields:
        return None
    return getattr(facts, name)


def matches(conditions: tuple[Condition, ...], facts: ProductFacts) -> bool:
    for condition in conditions:
        actual = fact_value(facts, condition.fact)
        if condition.operator == "equals":
            satisfied = actual == condition.equals
        elif condition.operator in ("contains", "not_contains"):
            if not isinstance(actual, str) or not isinstance(condition.equals, str):
                return False
            if not condition.equals.strip():
                return False
            contained = condition.equals.casefold() in actual.casefold()
            satisfied = (
                positive_contains(actual, condition.equals)
                if condition.operator == "contains"
                else not contained
            )
        else:
            return False
        if not satisfied:
            return False
    return True


def positive_contains(actual: str, term: str) -> bool:
    """Conservative lexical support, never interpret a negated term as positive.

    This is a fail-closed guard on authored predicates, not a natural-language
    classification system. Ambiguous negation may withhold a selector and ask
    for clearer structured facts. Unrelated clauses cannot negate earlier facts.
    """
    actual, term = actual.casefold(), term.casefold()
    for match in re.finditer(re.escape(term), actual):
        prefix = re.split(r"[.;,:\n]", actual[: match.start()])[-1][-80:]
        suffix = actual[match.end() :]
        if re.search(r"\b(?:not|no|non|without|rather\s+than|does\s+not)\b", prefix):
            continue
        if re.match(r"[\s-]*(?:free|absent|excluded)\b", suffix):
            continue
        return True
    return False


def mandatory_retrieval(
    corpus: Corpus, chapter: str, context: CheckContext
) -> tuple[LegalRule, ...]:
    """Return all required material; no ranking/top-k truncation is permitted."""
    chapters = (chapter,) + corpus.rival_chapters.get(chapter, ())
    ids = tuple(
        dict.fromkeys(
            tuple(rid for ch in chapters for rid in corpus.mandatory_rule_ids.get(ch, ()))
            + context.own_ruling_ids
        )
    )
    return tuple(corpus.rules[rid] for rid in ids if rid in corpus.rules)


def mandatory_material_complete(rules: tuple[LegalRule, ...], chapters: tuple[str, ...]) -> bool:
    """One chapter's notes cannot substitute for missing rival chapter material."""
    if not {f"gri_{i}" for i in range(1, 7)} <= {rule.kind for rule in rules}:
        return False
    scoped = {"section_note", "chapter_note", "heading"}
    return all(
        scoped <= {rule.kind for rule in rules if chapter in rule.chapters} for chapter in chapters
    )


def tax_difference(value: Decimal, applicable_rate: Decimal, billed_rate: Decimal) -> Decimal:
    """Signed tax gap on exclusive taxable value; positive means a higher applicable tax."""
    if not all(v.is_finite() for v in (value, applicable_rate, billed_rate)):
        raise ValueError("non-finite tax input")
    if value < 0 or not 0 <= applicable_rate <= 100 or not 0 <= billed_rate <= 100:
        raise ValueError("invalid tax input")
    return (value * (applicable_rate - billed_rate) / Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def evaluate_proposals(
    facts: ProductFacts,
    proposals: tuple[Proposal, ...] | list[Proposal],
    corpus: Corpus,
    context: CheckContext,
    bill: BillFields | None = None,
    defense: Defense | None = None,
) -> EngineResult:
    """Validate three blind runs before comparing the separately held invoice.

    Missing evidence always precedes a favorable or unfavorable verdict. A model
    disagreement never creates legal dispute authority.
    """
    banners = [AMENDMENT_BANNER]

    def abstain(reason, *, missing_facts=(), missing_sources=(), code=None):
        return EngineResult(
            "Need more info",
            reason,
            code=code,
            missing_facts=tuple(missing_facts),
            missing_sources=tuple(missing_sources),
            banners=tuple(banners),
            law_snapshot_id=corpus.snapshot_id,
        )

    if context.as_of < MVP_START:
        return abstain("date_not_covered")
    if context.supply != "intra_state":
        return abstain("jurisdiction_not_covered")
    if len(proposals) != 3:
        return abstain("three_runs_required")
    codes = Counter(p.code for p in proposals)
    if len(codes) != 1:
        return abstain("inconsistent_classification")
    code = proposals[0].code
    chapter = code[:2]
    relevant_chapters = (chapter,) + corpus.rival_chapters.get(chapter, ())
    rows = [
        r
        for r in corpus.coverage
        if r.chapter == chapter
        and r.jurisdiction == "Goa"
        and active(r.effective_from, r.effective_to, context.as_of)
    ]
    if not rows:
        return abstain("chapter_not_loaded")
    if context.mode == "strict" and not any(
        row.complete and row.verified_through and row.verified_through >= context.as_of
        for row in rows
    ):
        return abstain("coverage_incomplete")
    if not any(row.verified_through and row.verified_through >= context.as_of for row in rows):
        banners.append("verification not established for the requested date")
    required = tuple(
        dict.fromkeys(
            sid for ch in relevant_chapters for sid in corpus.required_source_ids.get(ch, ())
        )
    )
    # A chapter without an explicit acquisition checklist is not silently certified.
    missing_sources = [
        sid
        for sid in required
        if not (
            (doc := corpus.sources.get(sid))
            and doc.verified
            and doc.official
            and doc.publication_date
            and doc.publication_date <= context.as_of
        )
    ]
    if not required:
        missing_sources.append(f"chapter_{chapter}_source_checklist")
    if missing_sources:
        return abstain("source_missing", missing_sources=missing_sources)
    required_ids = set(
        rid for ch in relevant_chapters for rid in corpus.mandatory_rule_ids.get(ch, ())
    ) | set(context.own_ruling_ids)
    retrieved = mandatory_retrieval(corpus, chapter, context)
    if not mandatory_material_complete(retrieved, relevant_chapters) or len(retrieved) != len(
        required_ids
    ):
        return abstain("source_missing", missing_sources=("mandatory_legal_material",))
    for rule in retrieved:
        if not (
            active(rule.effective_from, rule.effective_to, context.as_of)
            and valid_citation(rule.citation, corpus, context.as_of)
        ):
            return abstain("source_missing", missing_sources=(rule.rule_id,))
        if rule.kind == "own_ruling" and not (
            rule.applicable_party and rule.status == "in_force" and matches(rule.conditions, facts)
        ):
            return abstain("own_ruling_unverified")
    missing_facts = tuple(
        dict.fromkeys(
            tuple(
                name for name in context.required_facts if fact_value(facts, name) in (None, "", ())
            )
            + tuple(name for p in proposals for name in p.missing_facts)
        )
    )
    if missing_facts:
        return abstain("facts_missing", missing_facts=missing_facts)
    code_entry = corpus.codes.get(code)
    if not code_entry or not active(
        code_entry.effective_from, code_entry.effective_to, context.as_of
    ):
        return abstain("code_not_verified")
    if not valid_citation(code_entry.citation, corpus, context.as_of):
        return abstain("source_missing", missing_sources=(code_entry.citation.source_id,))
    if len(code) == 8 and not (
        code_entry.authenticated_national
        and corpus.sources[code_entry.citation.source_id].kind == "customs_tariff"
    ):
        return abstain("source_missing", missing_sources=(f"national_tariff_{chapter}",))
    banners.append(AUTO_VERIFICATION_BANNER)
    if len(code) < 8:
        level = "heading" if len(code) == 4 else "HS 6-digit"
        banners.append(f"Classification assessed at {level} {code}; 8-digit code not verified")
    for proposal in proposals:
        selected_rules = [corpus.rules.get(rid) for rid in proposal.rule_ids]
        if not selected_rules or any(
            rule is None
            or not active(rule.effective_from, rule.effective_to, context.as_of)
            or not valid_citation(rule.citation, corpus, context.as_of)
            or not matches(rule.conditions, facts)
            or (rule.chapters and chapter not in rule.chapters)
            or (
                rule.supports_codes
                and not any(
                    code.startswith(supported) or supported.startswith(code)
                    for supported in rule.supports_codes
                )
            )
            for rule in selected_rules
        ):
            return abstain("reasoning_not_verified")
        if not any(
            rule.kind == "heading" and code in rule.supports_codes for rule in selected_rules
        ):
            return abstain("reasoning_not_verified")
    all_claims = tuple(c for p in proposals for c in p.citations)
    verified_claims = tuple(c for c in all_claims if valid_citation(c, corpus, context.as_of))
    dropped = len(all_claims) - len(verified_claims)
    citations = tuple(
        dict.fromkeys(
            (c.source_id, c.page, c.quote)
            for c in (code_entry.citation,) + tuple(r.citation for r in retrieved) + verified_claims
        )
    )
    if context.jurisdiction != "Goa":
        banners.append("state component not loaded; total and exposure withheld")
        same_code = (
            not bill
            or not bill.claimed_code
            or code.startswith(bill.claimed_code)
            or bill.claimed_code.startswith(code)
        )
        return EngineResult(
            "Supported" if same_code else "Need more info",
            "state_component_not_loaded",
            code=code,
            confidence="Low" if dropped else "Medium",
            citations=tuple(Citation(source_id=s, page=p, quote=q) for s, p, q in citations),
            needs_review=True,
            banners=tuple(banners),
            dropped_claims=dropped,
            law_snapshot_id=corpus.snapshot_id,
        )
    rate_sets = {tuple(sorted(p.rate_entry_ids)) for p in proposals}
    if len(rate_sets) != 1:
        return abstain("inconsistent_rate_selection", code=code)
    selected_ids = next(iter(rate_sets))
    selected_rates = [corpus.rates.get(rid) for rid in selected_ids]
    if len(selected_rates) != 2 or any(rate is None for rate in selected_rates):
        return abstain("rate_not_verified", code=code)
    if {rate.component for rate in selected_rates} != {"CGST", "SGST"}:
        return abstain("rate_component_missing", code=code)
    for rate in selected_rates:
        # A heading/HS6 determination cannot choose among national item rates.
        # The model must select an authenticated Indian item before such a rate
        # can be applied; a broader GST entry needs no invented eighth digit.
        if len(rate.code_prefix) == 8 and len(code) < 8 and rate.code_prefix.startswith(code):
            return abstain(
                "source_missing", missing_sources=(f"national_tariff_{chapter}",), code=code
            )
        if not (
            rate.rate_pct.is_finite()
            and 0 <= rate.rate_pct <= 100
            and active(rate.effective_from, rate.effective_to, context.as_of)
            and valid_citation(rate.citation, corpus, context.as_of)
            and rate.code_prefix
            and code.startswith(rate.code_prefix)
            and not any(code.startswith(excluded) for excluded in rate.excluded_prefixes)
            and matches(rate.conditions, facts)
            and rate.jurisdiction == ("India" if rate.component == "CGST" else "Goa")
        ):
            return abstain("rate_not_verified", code=code)
    citations += tuple(
        (r.citation.source_id, r.citation.page, r.citation.quote) for r in selected_rates
    )
    rate_total = sum((rate.rate_pct for rate in selected_rates), Decimal(0))
    category: Category = "Supported"
    if bill:
        same_code = (
            bill.claimed_code is None
            or code.startswith(bill.claimed_code)
            or bill.claimed_code.startswith(code)
        )
        same_rate = bill.billed_rate_pct is not None and bill.billed_rate_pct == rate_total
        if not same_code:
            category = "Rate right, HSN wrong" if same_rate else "Wrong"
        elif bill.billed_rate_pct is not None and not same_rate:
            category = "Wrong"
    if defense and bill and defense.rival_code != code and bill.claimed_code == defense.rival_code:
        rival_rules = [corpus.rules.get(rid) for rid in defense.rule_ids]
        if rival_rules and all(
            rule
            and rule.kind in ("rival_heading", "own_ruling")
            and rule.status == "in_force"
            and active(rule.effective_from, rule.effective_to, context.as_of)
            and valid_citation(rule.citation, corpus, context.as_of)
            and defense.rival_code in rule.supports_codes
            and matches(rule.conditions, facts)
            and (rule.kind != "own_ruling" or rule.applicable_party)
            for rule in rival_rules
        ):
            category = "Disputable"
            citations += tuple(
                (r.citation.source_id, r.citation.page, r.citation.quote) for r in rival_rules
            )
    total = rate_total
    difference = None
    if category != "Disputable" and bill:
        if bill.taxable_value is not None and bill.billed_rate_pct is not None:
            difference = tax_difference(bill.taxable_value, total, bill.billed_rate_pct)
    complete = any(
        r.complete and r.verified_through and r.verified_through >= context.as_of for r in rows
    )
    confidence: Literal["High", "Medium", "Low"] = "High" if complete else "Medium"
    if dropped or category == "Disputable":
        confidence = "Low"
    review = confidence == "Low" or category in ("Wrong", "Disputable", "Need more info")
    if context.needs_review_threshold is None:
        review = True  # No unapproved rupee threshold may silently clear review.
    if difference is not None and context.needs_review_threshold is not None:
        review = review or abs(difference) > context.needs_review_threshold
    return EngineResult(
        category,
        "validated" if total is not None else "state_component_not_loaded",
        code=code,
        rate_pct=total,
        rate_entry_ids=selected_ids if total is not None else (),
        confidence=confidence,
        citations=tuple(Citation(source_id=s, page=p, quote=q) for s, p, q in citations),
        needs_review=review,
        tax_difference=difference,
        banners=tuple(banners),
        dropped_claims=dropped,
        law_snapshot_id=corpus.snapshot_id,
    )
