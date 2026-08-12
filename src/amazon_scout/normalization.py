from __future__ import annotations

from statistics import mean, median
from typing import Iterable


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def minmax(value: float | None, minimum: float, maximum: float, *, reverse: bool = False, missing: float = 0) -> float:
    if value is None:
        return missing
    if maximum <= minimum:
        raise ValueError("maximum must exceed minimum")
    result = 100 * (value - minimum) / (maximum - minimum)
    result = clamp(result)
    return round(100 - result if reverse else result, 2)


def percentile(values: Iterable[float], p: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    if not 0 <= p <= 1:
        raise ValueError("p must be in [0, 1]")
    index = (len(ordered) - 1) * p
    lower, upper = int(index), min(int(index) + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def price_statistics(values: Iterable[float | None]) -> dict[str, float | None]:
    clean = [float(v) for v in values if v is not None and v > 0]
    if not clean:
        return {k: None for k in ("mean", "median", "p25", "p75", "dispersion")}
    med = median(clean)
    return {"mean": round(mean(clean), 2), "median": round(med, 2), "p25": round(percentile(clean, .25) or 0, 2), "p75": round(percentile(clean, .75) or 0, 2), "dispersion": round((max(clean) - min(clean)) / med, 3) if med else None}
