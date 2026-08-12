from __future__ import annotations

SOURCE_PRIORITY = {
    "sp_api": 100,
    "amazon_public": 85,
    "serpapi": 75,
    "rainforest": 75,
    "dataforseo": 70,
    "codex_web": 55,
    "external_retailer": 30,
    "blog": 20,
}


def source_priority(provider: str, metric_name: str | None = None) -> int:
    base = SOURCE_PRIORITY.get(provider, 10)
    if metric_name == "amazon_search_volume":
        if provider == "brand_analytics": return 100
        if provider == "dataforseo": return 80
    if metric_name and "price" in metric_name and provider == "amazon_public":
        return 60
    return base


def choose_preferred(records):
    return max(records, key=lambda r: (source_priority(r.source_provider, r.metric_name), r.observed_at)) if records else None
