import json
import tempfile
import unittest
from pathlib import Path

from amazon_scout.evidence import EvidenceRecord, EvidenceStrength, load_bundle, validate_bundle
from amazon_scout.research_pipeline import analyze_evidence_bundle


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(Path("tests/fixtures/research_evidence.json").read_text())

    def test_schema_shaped_bundle_and_provenance(self):
        raw, records = validate_bundle(self.raw)
        self.assertEqual(len(records), 6)
        self.assertEqual(records[0].marketplace, "amazon.ae")
        self.assertIsInstance(records[0].confidence, EvidenceStrength)
        self.assertTrue(records[0].source_url.startswith("https://"))

    def test_invalid_numeric_rejected(self):
        self.raw["products"][0]["current_price_aed"] = "79"
        with self.assertRaises(ValueError): validate_bundle(self.raw)

    def test_us_contamination_rejected(self):
        self.raw["evidence"][0]["marketplace"] = "amazon.com"
        with self.assertRaisesRegex(ValueError, "Non-UAE"): validate_bundle(self.raw)

    def test_duplicate_ids_rejected(self):
        self.raw["evidence"][1]["id"] = self.raw["evidence"][0]["id"]
        with self.assertRaisesRegex(ValueError, "Duplicate"): validate_bundle(self.raw)

    def test_missing_source_data_stays_unknown(self):
        self.raw["evidence"] = [e for e in self.raw["evidence"] if e["metric_name"] != "estimated_referral_fee_aed"]
        raw, records = validate_bundle(self.raw)
        result = analyze_evidence_bundle(raw, records)[0]
        self.assertIsNone(result["known_fee_aed"])
        self.assertEqual(result["fee_status"], "unknown")

    def test_research_confidence_and_gates(self):
        raw, records = validate_bundle(self.raw)
        result = analyze_evidence_bundle(raw, records)[0]
        self.assertFalse(result["final_top_10_eligible"])
        self.assertFalse(result["gates"]["competition"]["gate"])
        self.assertIsNone(result["validated_opportunity_score"])
        self.assertGreater(result["data_confidence_score"], 0)
        self.assertIn("recommendation_tier", result)
