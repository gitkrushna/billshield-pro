"""Page loading preserves evidence provenance without activating research rows."""

import hashlib

import pytest
from billshield.corpus import CHAPTERS, corpus_from_verified_pages


def verified():
    text = "Synthetic canonical page used only to test the source loader"
    return {
        "accepted": [
            {
                "id": "goa_09_2025",
                "source": {
                    "source_key": "m2:synthetic:abc",
                    "url": "https://statetax.goa.gov.in/test.pdf",
                    "document_type": "sgst_notification",
                    "issued_on": "2025-09-17",
                    "content_sha256": "a" * 64,
                },
                "pages": [
                    {
                        "source_page": 1,
                        "text_original": text,
                        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    }
                ],
                "scope": {},
            }
        ]
    }


def test_verified_pages_do_not_activate_unreviewed_rates_codes_or_rules():
    corpus = corpus_from_verified_pages(verified(), "synthetic-loader-not-law")
    assert not corpus.codes and not corpus.rules and not corpus.rates
    assert set(corpus.required_source_ids) == set(CHAPTERS)
    assert all(
        not row.complete and row.verified_through is None for row in corpus.coverage
    )
    source = next(iter(corpus.sources.values()))
    assert (
        source.official
        and source.verified
        and source.publication_date.isoformat() == "2025-09-17"
    )
    assert source.source_id in corpus.required_source_ids["33"]
    assert "hs_tariff_33" in corpus.required_source_ids["33"]
    assert "mcnroe" in corpus.required_source_ids["33"]


def test_canonical_page_mutation_is_detected():
    data = verified()
    data["accepted"][0]["pages"][0]["text_original"] = "altered after verification"
    with pytest.raises(ValueError, match="hash mismatch"):
        corpus_from_verified_pages(data, "synthetic")


def test_mirror_cannot_be_promoted_to_official_evidence():
    data = verified()
    data["accepted"][0]["source"]["url"] = "https://tax-mirror.example/test.pdf"
    with pytest.raises(ValueError, match="Nonofficial"):
        corpus_from_verified_pages(data, "synthetic")


def _item(source_id, kind, text, **scope):
    source = verified()["accepted"][0]
    source["id"] = source_id
    source["source"].update(source_key=f"m2:{source_id}:fixture", document_type=kind)
    source["scope"] = scope
    source["pages"][0].update(
        text_original=text, text_sha256=hashlib.sha256(text.encode()).hexdigest()
    )
    return source


def test_exact_official_schedule_activates_numeric_rate_without_review_gate():
    # Synthetic parser evidence, never production law. A model supplies no number.
    text = (
        "Notification effective 22 September 2025\nSchedule I - 2.5%\n"
        "90. 1513 Coconut (copra), palm kernel or babassu oil and fractions thereof\n"
        "91. 1514 Rape oil\n"
    )
    item = _item("cgst_09_2025", "cgst_notification", text)
    corpus = corpus_from_verified_pages({"accepted": [item]}, "test")
    rate = next(iter(corpus.rates.values()))
    assert str(rate.rate_pct) == "2.5" and rate.code_prefix == "1513"
    assert rate.auto_verified and rate.jurisdiction == "India"
    assert rate.citation.quote in text
    assert "91." not in rate.citation.quote
    basis = next(rule for rule in corpus.rules.values() if rule.kind == "rate_basis")
    assert "Schedule I - 2.5%" in basis.citation.quote


def test_rate_cannot_activate_without_its_own_schedule_rate():
    item = _item(
        "cgst_09_2025", "cgst_notification", "22 September 2025\n90. 1513 Coconut oil"
    )
    assert not corpus_from_verified_pages({"accepted": [item]}, "test").rates


def test_full_hs_notes_and_literal_six_digit_codes_activate_but_no_eight_digit():
    text = "Chapter 33\nNotes\n1. Complete qualifying note.\n33.07 Shaving preparations\n 3307.10 - Pre-shave, shaving or after-shave preparations\n"
    item = _item("hs33", "hs_chapter", text, chapter="33")
    item["source"]["url"] = (
        "https://www.wcoomd.org/-/media/wco/public/global/pdf/topics/nomenclature/instruments-and-tools/hs-nomenclature-2022/2022/0633_2022e.pdf"
    )
    corpus = corpus_from_verified_pages({"accepted": [item]}, "test")
    assert set(corpus.codes) == {"3307", "330710"}
    assert not any(code.authenticated_national for code in corpus.codes.values())
    note = next(rule for rule in corpus.rules.values() if rule.kind == "chapter_note")
    assert (
        note.citation.quote == text and note.rule_id in corpus.mandatory_rule_ids["33"]
    )


def test_activation_hash_binds_predicates_numeric_rates_and_quotes():
    from dataclasses import replace
    from decimal import Decimal

    from billshield.corpus import activation_manifest

    text = "22 September 2025\nSchedule II - 9%\n64. 3307 Pre-shave shaving preparations [other than shaving cream]\n"
    item = _item("goa_09_2025", "sgst_notification", text)
    corpus = corpus_from_verified_pages({"accepted": [item]}, "test")
    original = activation_manifest(corpus)
    entry_id, rate = next(iter(corpus.rates.items()))
    assert any(
        c.fact == "form" and c.equals == "foam" and c.operator == "contains"
        for c in rate.conditions
    )
    assert any(c.operator == "not_contains" for c in rate.conditions)
    altered = replace(corpus, rates={entry_id: replace(rate, rate_pct=Decimal("2.5"))})
    assert activation_manifest(altered) != original
    altered = replace(corpus, rates={entry_id: replace(rate, conditions=())})
    assert activation_manifest(altered) != original


def test_section_absence_uses_actual_contents_quote_and_never_invents_note():
    text = "SECTION III\nANIMAL FATS AND OILS\n15 Animal fats.\nSECTION IV\nPREPARED FOOD\nSection Note.\n16 Food.\n"
    item = _item("hs_contents", "hs_contents", text)
    corpus = corpus_from_verified_pages({"accepted": [item]}, "test")
    rules = [r for r in corpus.rules.values() if r.kind == "section_note"]
    assert len(rules) == 1
    assert rules[0].status == "no_section_notes_in_official_contents"
    assert (
        rules[0].citation.quote in text and "SECTION IV" not in rules[0].citation.quote
    )
    assert "hs_section_III" not in corpus.required_source_ids["15"]


def test_contents_with_section_note_does_not_falsely_certify_no_notes():
    item = _item("hs_contents", "hs_contents", "SECTION III\nSection Note.\n15 Fats.\n")
    corpus = corpus_from_verified_pages({"accepted": [item]}, "test")
    assert not corpus.rules


def test_partial_gri_cannot_be_activated_as_all_six_rules():
    item = _item("gri", "gri", "1. Heading terms.\n2. Incomplete goods.\n")
    assert not corpus_from_verified_pages({"accepted": [item]}, "test").rules


def test_non_toilet_soap_requires_positive_use_or_liquid_skin_washing_facts():
    from billshield.engine import ProductFacts, matches

    text = (
        "22 September 2025\nSchedule I - 2.5%\n251. 3401 Toilet soap in bars\n"
        "Schedule II - 9%\n66. 3401 Soap; organic surface-active products and preparations for use as soap [other than toilet soap in bars]; liquid preparations for washing skin\n"
    )
    item = _item("goa_09_2025", "sgst_notification", text)
    corpus = corpus_from_verified_pages({"accepted": [item]}, "test")

    def applicable(form, use):
        facts = ProductFacts(name="Synthetic cleanser", form=form, use=use)
        return [
            rate for rate in corpus.rates.values() if matches(rate.conditions, facts)
        ]

    # Merely omitting a toilet-use claim cannot establish the residual rate.
    assert not applicable("Soap bar", "Unspecified cleansing use")
    laundry = applicable("Soap bar/cake", "Washing clothes, not toilet use")
    assert len(laundry) == 1 and str(laundry[0].rate_pct) == "9"
    skin_liquid = applicable("Liquid in a pump bottle", "Washing skin")
    assert len(skin_liquid) == 1 and str(skin_liquid[0].rate_pct) == "9"
    assert not applicable("Soap bar", "Not for washing clothes or toilet use")


def test_licence_without_therapeutic_retail_facts_cannot_select_medicament_rate():
    from billshield.engine import ProductFacts, matches

    text = "22 September 2025\nSchedule I - 2.5%\n234. 3004 Medicaments for therapeutic or prophylactic uses in measured doses or retail packings\n"
    item = _item("cgst_09_2025", "cgst_notification", text)
    rate = next(
        iter(corpus_from_verified_pages({"accepted": [item]}, "test").rates.values())
    )
    assert not matches(
        rate.conditions,
        ProductFacts(
            name="Licensed cream",
            form="Retail cream",
            use="General moisturising",
            medicinal_licence=True,
        ),
    )
    assert not matches(
        rate.conditions,
        ProductFacts(
            name="Therapeutic preparation",
            form="Bulk oil",
            use="Therapeutic use",
            medicinal_licence=True,
        ),
    )
    assert matches(
        rate.conditions,
        ProductFacts(
            name="Therapeutic preparation",
            form="Retail medicinal preparation",
            use="Therapeutic use",
            medicinal_licence=True,
        ),
    )


def test_activation_is_identical_after_manifest_source_order_round_trip():
    from billshield.corpus import activation_manifest

    text = "22 September 2025\nSchedule I - 2.5%\n90. 1513 Coconut oil\n"
    items = [
        _item("goa_09_2025", "sgst_notification", text),
        _item("cgst_09_2025", "cgst_notification", text),
    ]
    before = corpus_from_verified_pages({"accepted": items}, "same-snapshot")
    after = corpus_from_verified_pages(
        {"accepted": list(reversed(items))}, "same-snapshot"
    )
    assert activation_manifest(before) == activation_manifest(after)


def test_legal_note_numbers_are_distinct_from_canonical_page_numbers():
    text = (
        "Chapter 33\nNotes.\n1.- First exclusion.\n"
        "2.- Second qualification.\n3.- Retail extension, inter alia.\n"
        "_________________\nHeading H.S. Code\n33.07 Shaving preparations\n"
    )
    item = _item("hs33", "hs_chapter", text, chapter="33")
    item["pages"][0]["source_page"] = 2
    corpus = corpus_from_verified_pages({"accepted": [item]}, "test")
    page = corpus.rules["hs33:chapter_page:2"]
    note = corpus.rules["hs33:chapter_note:3"]
    assert page.citation.quote == text
    assert page.rule_id in corpus.mandatory_rule_ids["33"]
    assert note.citation.page == 2
    assert note.citation.quote == "3.- Retail extension, inter alia.\n"
    assert note.citation.quote in text
    assert "hs33:chapter_note:4" not in corpus.rules


def test_possibly_continued_note_keeps_only_full_page_evidence():
    item = _item(
        "hs33", "hs_chapter", "Notes.\n1.- Qualification continues", chapter="33"
    )
    corpus = corpus_from_verified_pages({"accepted": [item]}, "test")
    assert "hs33:chapter_page:1" in corpus.rules
    assert "hs33:chapter_note:1" not in corpus.rules
