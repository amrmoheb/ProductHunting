from __future__ import annotations

from statistics import median

from .normalization import clamp


def calculate_demand(query_volume: int | None, sales_ranks: list[int], catalog_result_count: int | None) -> tuple[float, str]:
    """Score evidence without converting BSR into invented unit sales."""
    valid_ranks = [r for r in sales_ranks if r > 0]
    if query_volume is not None:
        volume_score = clamp(20 * (__import__("math").log10(max(1, query_volume)) - 1))
        rank_support = 0 if not valid_ranks else clamp(100 - 20 * __import__("math").log10(median(valid_ranks)))
        return round(0.75 * volume_score + 0.25 * rank_support, 2), "HIGH"
    if valid_ranks:
        rank_score = clamp(110 - 22 * __import__("math").log10(median(valid_ranks)))
        breadth = clamp(len(valid_ranks) * 10)
        return round(0.8 * rank_score + 0.2 * breadth, 2), "MEDIUM" if len(valid_ranks) >= 3 else "LOW"
    if catalog_result_count is not None:
        # Catalog breadth is weak evidence, deliberately capped.
        return round(min(35, 8 * __import__("math").log10(max(1, catalog_result_count))), 2), "LOW"
    return 0.0, "LOW"

