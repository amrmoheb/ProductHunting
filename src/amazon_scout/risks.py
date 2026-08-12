from __future__ import annotations

from .models import Product
from .normalization import clamp

RISK_TERMS: dict[str, tuple[int, str]] = {
    "battery": (22, "Battery handling, shipping, and compliance"),
    "electronic": (18, "Electronics complexity and returns"),
    "glass": (16, "Fragile/breakage risk"),
    "liquid": (18, "Liquid leakage and handling risk"),
    "cosmetic": (25, "Cosmetics regulatory and claims risk"),
    "supplement": (35, "Supplement regulatory and safety risk"),
    "food": (25, "Food shelf-life and regulatory risk"),
    "medical": (35, "Medical claims/regulatory risk"),
    "baby": (25, "Children's safety/product liability risk"),
    "child": (25, "Children's safety/product liability risk"),
}


def calculate_risk(name: str, products: list[Product], competition_risk_score: float = 0) -> tuple[float, list[str]]:
    text = " ".join([name, *(p.title for p in products), *(p.product_type or "" for p in products)]).lower()
    score = competition_risk_score * 0.35
    reasons: list[str] = []
    for term, (penalty, reason) in RISK_TERMS.items():
        if term in text and reason not in reasons:
            score += penalty
            reasons.append(reason)
    weights = [p.weight_kg for p in products if p.weight_kg is not None]
    if weights and sum(weights) / len(weights) > 1.5:
        score += 12
        reasons.append("Above preferred 1.5 kg shipping weight")
    prices = [p.price_aed for p in products if p.price_aed is not None]
    if prices and sum(prices) / len(prices) < 40:
        score += 10
        reasons.append("Low selling price leaves little fee/cost headroom")
    brands = {p.brand.lower() for p in products if p.brand}
    if any(b in text for b in ("apple", "disney", "nike", "lego")) or len(brands) == 1 and len(products) > 2:
        score += 15
        reasons.append("Dominant brand or intellectual-property risk requires review")
    return round(clamp(score), 2), reasons

