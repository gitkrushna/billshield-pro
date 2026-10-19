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
    assert "national_tariff_33" in corpus.required_source_ids["33"]
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
