from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .sources.dataforseo import (
    ENDPOINTS,
    DataForSEOBudget,
    DataForSEOCache,
    DataForSEOMode,
    DataForSEOProviderError,
    DataForSEOSettings,
    DataForSEOSource,
    EvidenceEnvironment,
    parse_product_competitors,
    parse_ranked_keywords,
)

VERSION = "V1.4B.2"
CANDIDATE = "wood crochet blocking board"
TARGET_ASIN = "B0C5WLFKDT"
SELECTION_REASON = 'Strongest usable Arabic broad-term signal in the coverage probe: "كروشيه" -> 31.'
LOCATION_CODE = 2784
LANGUAGE_CODE = "ar"
RESULT_LIMIT = 10
MAX_TASKS = 2
MAX_COST_USD = 0.05
ESTIMATED_COST_PER_TASK = 0.025
PROVIDER = "dataforseo_amazon_labs"
LANGUAGE_COVERAGE = "PARTIAL_AMAZON_UAE_LANGUAGE_COVERAGE"


def ranked_keywords_task() -> dict[str, Any]:
    return {"asin": TARGET_ASIN, "location_code": LOCATION_CODE, "language_code": LANGUAGE_CODE, "limit": RESULT_LIMIT}


def product_competitors_task() -> dict[str, Any]:
    return {"asin": TARGET_ASIN, "location_code": LOCATION_CODE, "language_code": LANGUAGE_CODE, "limit": RESULT_LIMIT}


def poc_settings() -> DataForSEOSettings:
    base = DataForSEOSettings.from_environment()
    max_cost = min(MAX_COST_USD, max(0.0, float(os.getenv("DATAFORSEO_V14B2_MAX_COST_USD", str(MAX_COST_USD)))))
    max_tasks = min(MAX_TASKS, max(0, int(os.getenv("DATAFORSEO_V14B2_MAX_TASKS", str(MAX_TASKS)))))
    return DataForSEOSettings(base.mode, base.allow_paid, max_cost, max_tasks, base.login, base.password)


def _normalize_ranked(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "target_asin": row.get("target_asin"),
        "keyword": row.get("keyword"),
        "search_volume": row.get("search_volume"),
        "organic_position": row.get("organic_position"),
        "paid_position": row.get("paid_position"),
        "ranking_metadata": row.get("ranking_information"),
        "language_code": LANGUAGE_CODE,
        "location_code": LOCATION_CODE,
        "provider": PROVIDER,
        "environment": row.get("environment", EvidenceEnvironment.PRODUCTION.value),
    } for row in rows]


def _normalize_competitors(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "target_asin": row.get("target_asin"),
        "competitor_asin": row.get("competitor_asin"),
        "keyword_intersections": row.get("keyword_intersections"),
        "average_position": row.get("average_position"),
        "organic_visibility": row.get("organic_metrics"),
        "paid_visibility": row.get("paid_metrics"),
        "search_volume_related_metrics": row.get("total_search_volume_related_metrics"),
        "language_code": LANGUAGE_CODE,
        "location_code": LOCATION_CODE,
        "provider": PROVIDER,
        "environment": row.get("environment", EvidenceEnvironment.PRODUCTION.value),
    } for row in rows]


def _utility_conclusion(rows: list[dict[str, Any]], endpoint: str, outcome: str) -> str:
    if outcome == "UNSUPPORTED":
        return "UNSUPPORTED"
    if outcome != "SUCCEEDED" or not rows:
        return "INSUFFICIENT_DATA"
    if endpoint == ENDPOINTS["ranked_keywords"]:
        meaningful = sum(bool(row.get("keyword")) and (row.get("organic_position") is not None or row.get("paid_position") is not None) for row in rows)
    else:
        meaningful = sum(bool(row.get("competitor_asin")) and any(row.get(field) is not None for field in ("keyword_intersections", "average_position", "organic_visibility", "paid_visibility")) for row in rows)
    if meaningful >= 5:
        return "USEFUL"
    if meaningful >= 1:
        return "SPARSE_BUT_USABLE"
    return "INSUFFICIENT_DATA"


def _overall_conclusion(ranked: str, competitors: str) -> str:
    usable = {"USEFUL", "SPARSE_BUT_USABLE"}
    if ranked == "USEFUL" and competitors in usable or competitors == "USEFUL" and ranked in usable:
        return "DATAFORSEO_COMPETITION_LAYER_USEFUL"
    if ranked in usable or competitors in usable:
        return "DATAFORSEO_COMPETITION_LAYER_SUPPLEMENTAL"
    return "DATAFORSEO_COMPETITION_LAYER_NOT_USEFUL"


def _call(source: Any, endpoint: str, task: dict[str, Any], budget: DataForSEOBudget, cache: DataForSEOCache, parser: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        payload, cached = source.request(endpoint, task, budget, cache, estimated_cost=ESTIMATED_COST_PER_TASK)
        return parser(payload, EvidenceEnvironment.PRODUCTION), {"endpoint": endpoint, "status": "SUCCEEDED", "cached": cached}
    except PermissionError as exc:
        return [], {"endpoint": endpoint, "status": "SKIPPED_LOCAL_BUDGET", "reason": str(exc)}
    except DataForSEOProviderError as exc:
        status = "UNSUPPORTED" if exc.status_name in {"FUNCTION_UNAVAILABLE", "OUTDATED_LOCATION_DATA"} else "FAILED"
        return [], {"endpoint": endpoint, "status": status, "reason": str(exc)}
    except Exception as exc:
        return [], {"endpoint": endpoint, "status": "FAILED", "reason": str(exc)}


def run_poc(*, source: Any = None, cache: DataForSEOCache | None = None, now: datetime | None = None) -> dict[str, Any]:
    settings = poc_settings()
    if settings.mode != DataForSEOMode.PRODUCTION or not settings.allow_paid:
        raise PermissionError("V1.4B.2 requires DATAFORSEO_MODE=production and DATAFORSEO_ALLOW_PAID=true")
    if settings.max_tasks_per_run <= 0 or settings.max_cost_usd_per_run < ESTIMATED_COST_PER_TASK:
        raise PermissionError("V1.4B.2 local task/cost guard does not permit the first task")
    source = source or DataForSEOSource(settings)
    cache = cache or DataForSEOCache()
    budget = DataForSEOBudget.from_settings(settings)
    ranked_raw, ranked_outcome = _call(source, ENDPOINTS["ranked_keywords"], ranked_keywords_task(), budget, cache, parse_ranked_keywords)
    competitor_raw, competitor_outcome = _call(source, ENDPOINTS["product_competitors"], product_competitors_task(), budget, cache, parse_product_competitors)
    ranked = _normalize_ranked(ranked_raw)
    competitors = _normalize_competitors(competitor_raw)
    ranked_conclusion = _utility_conclusion(ranked, ENDPOINTS["ranked_keywords"], ranked_outcome["status"])
    competitor_conclusion = _utility_conclusion(competitors, ENDPOINTS["product_competitors"], competitor_outcome["status"])
    usage = budget.as_dict()
    usage["total_provider_reported_cost"] = usage["provider_reported_cost"]
    return {
        "version": VERSION,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "marketplace": "amazon.ae",
        "candidate": CANDIDATE,
        "representative_asin": TARGET_ASIN,
        "selection_reason": SELECTION_REASON,
        "location_code": LOCATION_CODE,
        "language_code": LANGUAGE_CODE,
        "language_coverage": LANGUAGE_COVERAGE,
        "coverage_caveat": "Arabic-only visibility is not the complete Amazon UAE market.",
        "ranked_keywords": ranked,
        "product_competitors": competitors,
        "endpoint_outcomes": {"ranked_keywords": ranked_outcome, "product_competitors": competitor_outcome},
        "ranked_keywords_conclusion": ranked_conclusion,
        "product_competitors_conclusion": competitor_conclusion,
        "overall_conclusion": _overall_conclusion(ranked_conclusion, competitor_conclusion),
        "provider_usage": usage,
        "official_scores_changed": False,
        "bulk_search_volume_calls": 0,
        "merchant_sellers_calls": 0,
        "related_keywords_calls": 0,
        "keyword_intersection_calls": 0,
    }


def render_report(bundle: dict[str, Any]) -> str:
    usage = bundle["provider_usage"]
    lines = [
        "# DATAFORSEO AMAZON UAE COMPETITION UTILITY POC — V1.4B.2", "",
        f"Generated: {bundle['generated_at']}",
        f"Candidate: {bundle['candidate']}",
        f"Representative ASIN: `{bundle['representative_asin']}`",
        f"Selection reason: {bundle['selection_reason']}",
        "Scope: Amazon UAE, location `2784`, Arabic (`ar`).",
        "Coverage: PARTIAL_AMAZON_UAE_LANGUAGE_COVERAGE. Arabic-only visibility is not the complete Amazon UAE market.",
        "Official scoring, gates, tiers, and V1.3 economics: UNCHANGED.", "",
        "| Endpoint | Outcome | Rows | Utility conclusion |", "|---|---|---:|---|",
        f"| Ranked Keywords | {bundle['endpoint_outcomes']['ranked_keywords']['status']} | {len(bundle['ranked_keywords'])} | {bundle['ranked_keywords_conclusion']} |",
        f"| Product Competitors | {bundle['endpoint_outcomes']['product_competitors']['status']} | {len(bundle['product_competitors'])} | {bundle['product_competitors_conclusion']} |", "",
        f"Overall conclusion: **{bundle['overall_conclusion']}**", "",
        f"Provider-reported cost: USD {usage['provider_reported_cost']:.8f}",
        f"Tasks attempted/succeeded/failed: {usage['tasks_attempted']}/{usage['tasks_succeeded']}/{usage['tasks_failed']}",
        f"Cache hits: {usage['cache_hits']}",
        f"Remaining local budget: {usage['remaining_local_task_budget']} tasks; USD {usage['remaining_local_cost_budget']:.8f}",
        "Bulk Search Volume calls: 0", "Merchant Sellers calls: 0", "",
        "Normalized evidence is in the companion JSON. Missing provider values remain null.",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(bundle: dict[str, Any], directory: str | Path = "reports") -> tuple[Path, Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    base = directory / f"{stamp}-v1.4b2-dataforseo-competition-poc"
    markdown, evidence = base.with_suffix(".md"), base.with_suffix(".json")
    markdown.write_text(render_report(bundle), encoding="utf-8")
    evidence.write_text(json.dumps(bundle, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return markdown, evidence


def main() -> int:
    try:
        bundle = run_poc()
    except (PermissionError, ValueError) as exc:
        print(f"REFUSED: {exc}")
        return 2
    markdown, evidence = write_outputs(bundle)
    print(f"Report: {markdown}")
    print(f"Evidence: {evidence}")
    print(f"Overall conclusion: {bundle['overall_conclusion']}")
    print(f"Provider cost: USD {bundle['provider_usage']['provider_reported_cost']:.8f}")
    return 0
