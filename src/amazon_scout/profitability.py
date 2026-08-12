from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Economics:
    selling_price: float
    landed_cost: float | None
    amazon_fees: float | None
    profit_before_tax: float | None
    roi_on_landed_cost: float | None
    net_margin: float | None


def landed_cost(unit_cost: float, shipping: float = 0, customs: float = 0, prep: float = 0, other: float = 0) -> float:
    values = (unit_cost, shipping, customs, prep, other)
    if any(v < 0 for v in values):
        raise ValueError("Costs cannot be negative")
    return round(sum(values), 2)


def analyze_economics(selling_price: float, amazon_fees: float | None, landed: float | None) -> Economics:
    if selling_price < 0:
        raise ValueError("Selling price cannot be negative")
    if amazon_fees is None or landed is None:
        return Economics(selling_price, landed, amazon_fees, None, None, None)
    profit = selling_price - landed - amazon_fees
    roi = profit / landed if landed > 0 else None
    margin = profit / selling_price if selling_price > 0 else None
    return Economics(selling_price, landed, amazon_fees, round(profit, 2), roi, margin)


def maximum_landed_cost(selling_price: float, amazon_fees: float | None, target_margin: float) -> float | None:
    if selling_price <= 0 or amazon_fees is None:
        return None
    if not 0 <= target_margin < 1:
        raise ValueError("Target margin must be in [0, 1)")
    return round(max(0.0, selling_price * (1 - target_margin) - amazon_fees), 2)


def uncertain_fee_scenarios(selling_price: float, known_fees: float, unknown_fee_scenarios: tuple[float, float, float], landed: float | None = None) -> dict[str, float | None]:
    if selling_price <= 0 or known_fees < 0 or any(fee < 0 for fee in unknown_fee_scenarios):
        raise ValueError("Prices and fees must be valid non-negative values")
    names = ("low", "mid", "high")
    result: dict[str, float | None] = {"maximum_landed_cost_before_unknown_fba_fee": maximum_landed_cost(selling_price, known_fees, .25)}
    for name, unknown in zip(names, unknown_fee_scenarios):
        total = known_fees + unknown
        result[f"maximum_landed_cost_{name}_fee_scenario"] = maximum_landed_cost(selling_price, total, .25)
        result[f"estimated_profit_{name}_fee_scenario"] = None if landed is None else round(selling_price - total - landed, 2)
    return result
