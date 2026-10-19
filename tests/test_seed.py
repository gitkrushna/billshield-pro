"""Corpus invariants use the supplied evidence, never fake production rows."""

import unittest

from scripts.seed import build_corpus, deduplicate, derive_scope


class CorpusTests(unittest.TestCase):
    def test_reconciliation_and_no_certification(self):
        tables, manifest, snapshot, sha = build_corpus()
        self.assertEqual(len(tables["rate_entries"]), 292)
        self.assertEqual(
            sum(r["component"] == "CGST" for r in tables["rate_entries"]), 146
        )
        self.assertEqual(
            sum(r["component"] == "SGST" for r in tables["rate_entries"]), 146
        )
        self.assertEqual(
            {r["rate_entry_id"] for r in tables["rate_scopes"]},
            {r["id"] for r in tables["rate_entries"]},
        )
        self.assertTrue(
            all(
                r["complete"] == "False" and not r["verified_through"]
                for r in tables["data_coverage"]
            )
        )
        self.assertEqual((manifest, snapshot, sha), build_corpus()[1:])

    def test_conflicting_ids_rejected(self):
        with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
            deduplicate([{"id": "x", "rate": "1"}, {"id": "x", "rate": "2"}])

    def test_exclusions_never_broadened(self):
        result = derive_scope(
            {"id": "x", "hsn_selector_raw": "2106 (other than 21069020)"}
        )
        self.assertEqual(result[0]["scope_type"], "raw")
        self.assertEqual(
            derive_scope({"id": "x", "hsn_selector_raw": "2101 11, 2101 12 00"})[1][
                "scope_type"
            ],
            "item",
        )


if __name__ == "__main__":
    unittest.main()
