from __future__ import annotations

from collections import Counter

from .models import Product
from .normalization import clamp


def competition_metrics(products: list[Product], catalog_result_count: int | None = None) -> dict[str, float | int | None]:
    brands = [p.brand.strip().lower() for p in products if p.brand and p.brand.strip()]
    counts = Counter(brands)
    top_share = max(counts.values()) / len(brands) if brands else None
    hhi = sum((count / len(brands)) ** 2 for count in counts.values()) if brands else None
    offers = [p.offer_count for p in products if p.offer_count is not None]
    variations = [p.variation_count for p in products if p.variation_count is not None]
    return {
        "catalog_result_count": catalog_result_count,
        "sampled_asins": len(products),
        "brand_concentration": round(hhi, 3) if hhi is not None else None,
        "top_brand_share": round(top_share, 3) if top_share is not None else None,
        "mean_offer_count": round(sum(offers) / len(offers), 2) if offers else None,
        "variation_density": round(sum(1 for v in variations if v > 0) / len(variations), 3) if variations else None,
        "amazon_retail_presence": any(p.amazon_retail_present is True for p in products),
    }


def competition_risk(products: list[Product], catalog_result_count: int | None = None) -> float:
    metrics = competition_metrics(products, catalog_result_count)
    risk = 0.0
    result_count = metrics["catalog_result_count"]
    if isinstance(result_count, int):
        risk += min(30, 7.5 * __import__("math").log10(max(1, result_count)))
    top_share = metrics["top_brand_share"]
    risk += 25 * float(top_share) if top_share is not None else 5
    offers = metrics["mean_offer_count"]
    risk += min(25, 3 * float(offers)) if offers is not None else 5
    if metrics["amazon_retail_presence"]:
        risk += 15
    variation_density = metrics["variation_density"]
    risk += 5 * float(variation_density) if variation_density is not None else 0
    return round(clamp(risk), 2)

