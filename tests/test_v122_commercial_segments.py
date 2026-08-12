from __future__ import annotations

import unittest
from datetime import datetime, timezone

from amazon_scout.commercial_segments import classify_commercial_segment, load_commercial_config, target_commercial_profile
from amazon_scout.evidence import EvidenceRecord
from amazon_scout.research_pipeline import analyze_evidence_bundle
from amazon_scout.sources.serpapi import normalize_search_response


NOW = datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc)
TS = NOW.isoformat()


def item(index: int, title: str, price: float, brand: str = "MidBrand") -> dict:
    return {"position": index, "asin": f"B0SEG{index:05d}", "title": title, "brand": brand, "price": f"AED {price}", "extracted_price": price, "rating": 4.2, "reviews": index * 10, "sponsored": index % 2 == 0}


def response(keyword: str, items: list[dict]) -> dict:
    return {"search_metadata": {"status": "Success"}, "search_parameters": {"engine": "amazon", "amazon_domain": "amazon.ae", "k": keyword}, "organic_results": items}


def analysis(niche: str, keyword: str, items: list[dict]) -> dict:
    normalized = normalize_search_response(response(keyword, items), niche=niche, keyword=keyword, run_id="v122", retrieved_at=TS)
    records = [EvidenceRecord.from_dict(x, "v122", validation_time=NOW) for x in normalized["evidence"]]
    raw = {"research_run": {"id": "v122", "marketplace": "amazon.ae", "started_at": TS, "evidence_cutoff": TS, "filters": {"price_min_aed": 50, "price_max_aed": 150}, "candidate_funnel": {"generated": 1, "screened": 1}}, "keywords": [keyword], "products": normalized["products"], "evidence": normalized["evidence"], "source_summary": {}}
    return analyze_evidence_bundle(raw, records, generated_at=NOW)[0]


class CommercialSegmentTests(unittest.TestCase):
    def test_same_product_different_size_segment(self):
        profile = target_commercial_profile("XL silicone pet feeding mats", "silicone pet feeding mat")
        small = classify_commercial_segment(item(1, "Small Silicone Pet Feeding Mat with Raised Edges 30x20cm", 12), profile)
        large = classify_commercial_segment(item(2, "1 Pc XL Silicone Pet Feeding Mat with Raised Edges 70x50cm", 80), profile)
        self.assertEqual(small["commercial_segment_status"], "ADJACENT")
        self.assertEqual(large["commercial_segment_status"], "COMPARABLE")

    def test_single_pack_vs_multipack(self):
        profile = target_commercial_profile("XL silicone pet feeding mats", "silicone pet feeding mat")
        multi = classify_commercial_segment(item(1, "2 Pcs XL Silicone Pet Feeding Mats with Raised Edges 70x50cm", 90), profile)
        self.assertEqual(multi["commercial_segment_status"], "NON_COMPARABLE")

    def test_standard_vs_premium_brand_segment(self):
        profile = target_commercial_profile("premium fabric desk mats", "fabric desk mat")
        standard = classify_commercial_segment(item(1, "Large Felt Fabric Desk Mat 90x40cm with Stitched Edge", 45), profile)
        premium = classify_commercial_segment(item(2, "Logitech Large Fabric Desk Mat 90x40cm", 99, "Logitech"), profile)
        self.assertEqual(standard["commercial_segment_status"], "COMPARABLE")
        self.assertEqual(premium["commercial_segment_status"], "ADJACENT")

    def test_cheap_exact_target_remains_relevant_but_not_comparable(self):
        out = normalize_search_response(response("silicone pet feeding mat", [item(1, "Silicone Pet Feeding Mats Nonslip Waterproof with Raised Edges", 6.02)]), niche="XL silicone pet feeding mats", keyword="silicone pet feeding mat", run_id="x", retrieved_at=TS)
        product = out["products"][0]
        self.assertEqual(product["relevance_status"], "EXACT_TARGET")
        self.assertEqual(product["commercial_segment_status"], "ADJACENT")

    def test_adjacent_product_excluded_from_comparable_median(self):
        products = [item(1, "Silicone Pet Feeding Mat with Raised Edges", 6.02)] + [item(i, f"1 Pc XL Silicone Pet Feeding Mat with Raised Edges 70x50cm model {i}", p) for i, p in enumerate((70, 80, 90, 100, 110), 2)]
        out = normalize_search_response(response("silicone pet feeding mat", products), niche="XL silicone pet feeding mats", keyword="silicone pet feeding mat", run_id="x", retrieved_at=TS)
        self.assertEqual(out["aggregates"]["price_median_aed"], 85)
        self.assertEqual(out["aggregates"]["comparable_price_median_aed"], 90)

    def test_one_premium_outlier_does_not_pass_price_gate(self):
        products = [item(i, f"Large Felt Fabric Desk Mat 90x40cm Stitched Edge {i}", p) for i, p in enumerate((20, 25, 30, 35, 40), 1)]
        products.append(item(6, "Logitech Large Fabric Desk Mat 90x40cm", 99, "Logitech"))
        result = analysis("premium fabric desk mats", "fabric desk mat", products)
        self.assertFalse(result["gates"]["price"]["gate"])
        self.assertEqual(result["commercial_opportunity_classification"], "PREMIUM_POSITIONING_HYPOTHESIS")

    def test_price_gate_fails_when_comparable_median_below_floor(self):
        products = [item(i, f"Large Felt Fabric Desk Mat 90x40cm Stitched Edge {i}", p) for i, p in enumerate((20, 25, 30, 35, 60), 1)]
        self.assertFalse(analysis("premium fabric desk mats", "fabric desk mat", products)["gates"]["price"]["gate"])

    def test_configurable_in_band_ratio(self):
        self.assertEqual(load_commercial_config()["price_gate"]["minimum_in_target_band_ratio"], .4)
        products = [item(i, f"Large Felt Fabric Desk Mat 90x40cm Stitched Edge {i}", p) for i, p in enumerate((30, 35, 40, 60, 70), 1)]
        self.assertTrue(analysis("premium fabric desk mats", "fabric desk mat", products)["gates"]["price"]["gate"])

    def test_competition_metrics_use_comparable_segment(self):
        products = [item(i, f"Large Felt Fabric Desk Mat 90x40cm Stitched Edge {i}", 60 + i) for i in range(1, 6)]
        outlier = item(6, "Logitech Large Fabric Desk Mat 90x40cm", 99, "Logitech"); outlier["reviews"] = 100000
        result = analysis("premium fabric desk mats", "fabric desk mat", products + [outlier])
        self.assertEqual(result["structured_metrics"]["review_sample_size"], 5)
        self.assertLess(result["structured_metrics"]["p75_reviews"], 100000)

    def test_premium_positioning_hypothesis(self):
        products = [item(i, f"Large Felt Fabric Desk Mat 90x40cm Stitched Edge {i}", 20 + i) for i in range(1, 6)] + [item(6, "Satechi Premium Fabric Desk Mat 90x40cm", 120, "Satechi")]
        self.assertEqual(analysis("premium fabric desk mats", "fabric desk mat", products)["commercial_opportunity_classification"], "PREMIUM_POSITIONING_HYPOTHESIS")

    def test_packing_cube_subtype_separation(self):
        profile = target_commercial_profile("premium compression packing cubes", "compression packing cubes")
        compression = classify_commercial_segment(item(1, "6 Piece Compression Packing Cubes Set", 90), profile)
        ordinary = classify_commercial_segment(item(2, "6 Piece Packing Cubes Set", 40), profile)
        self.assertEqual(compression["commercial_segment_status"], "COMPARABLE")
        self.assertEqual(ordinary["commercial_segment_status"], "NON_COMPARABLE")

    def test_desk_mat_mouse_pad_segmentation(self):
        profile = target_commercial_profile("premium fabric desk mats", "fabric desk mat")
        tiny = classify_commercial_segment(item(1, "Fabric Mouse Pad 20x18cm", 8), profile)
        self.assertNotEqual(tiny["commercial_segment_status"], "COMPARABLE")

    def test_pet_mat_size_segmentation(self):
        profile = target_commercial_profile("XL silicone pet feeding mats", "silicone pet feeding mat")
        unknown = classify_commercial_segment(item(1, "Silicone Pet Feeding Mat with Raised Edges", 6.02), profile)
        self.assertEqual(unknown["size_class"], "UNKNOWN")
        self.assertEqual(unknown["commercial_segment_status"], "ADJACENT")


if __name__ == "__main__": unittest.main()
