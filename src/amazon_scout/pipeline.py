from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from .competition import competition_risk
from .database import ScoutDatabase
from .demand import calculate_demand
from .models import NicheAnalysis, Product
from .normalization import minmax, price_statistics
from .report import render_report, write_report
from .risks import calculate_risk
from .scoring import data_confidence, load_scoring_config, opportunity_score
from .economics_v13 import calculate_candidate_economics


def analyze_niche(raw: dict[str, Any], config: dict[str, Any]) -> NicheAnalysis:
    products = [Product(**item) for item in raw["products"]]
    analysis = NicheAnalysis(name=raw["name"], products=products, catalog_result_count=raw.get("catalog_result_count"), brand_analytics_available=raw.get("brand_analytics_available", False), query_volume=raw.get("query_volume"), fees_aed=raw.get("fees_aed"))
    ranks = [p.sales_rank for p in products if p.sales_rank is not None]
    analysis.demand_score, analysis.demand_confidence = calculate_demand(analysis.query_volume, ranks, analysis.catalog_result_count)
    comp_risk = competition_risk(products, analysis.catalog_result_count)
    analysis.competition_score = round(100 - comp_risk, 2)
    analysis.risk_score, analysis.risk_reasons = calculate_risk(analysis.name, products, comp_risk)
    stats = price_statistics(p.price_aed for p in products)
    analysis.price_attractiveness_score = minmax(stats["median"], 40, 200, missing=0)
    median_price = stats["median"]
    if median_price and analysis.fees_aed is not None:
        fee_ratio = analysis.fees_aed / median_price
        analysis.margin_potential_score = round(max(0, min(100, 100 - fee_ratio * 180)), 2)
    brand_count = len({p.brand.lower() for p in products if p.brand})
    analysis.differentiation_score = round(min(85, 35 + brand_count * 7 + (10 if len(products) >= 4 else 0)), 2)
    economics = calculate_candidate_economics(analysis.name, median_price)
    factors = {"demand": analysis.demand_score, "competition": analysis.competition_score, "economics": (economics.get("score") or {}).get("raw"), "risk": 100 - analysis.risk_score}
    analysis.opportunity_score = opportunity_score(factors, config["weights"])
    newest = max((p.observed_at for p in products), default=None)
    analysis.data_confidence_score = data_confidence(brand_analytics=analysis.brand_analytics_available, pricing=any(p.price_aed is not None for p in products), sales_rank=bool(ranks), sample_size=len(products), fee_estimate=analysis.fees_aed is not None, newest_observation=newest, config=config)
    return analysis


def run_mock(fixture: str | Path = "tests/fixtures/mock_research.json", filters: dict[str, Any] | None = None) -> tuple[Path, Path]:
    raw = json.loads(Path(fixture).read_text(encoding="utf-8"))
    config = load_scoring_config()
    analyses = [analyze_niche(niche, config) for niche in raw["niches"]]
    content = render_report(analyses, filters=filters or {}, sources=["mock SP-API fixture"], unavailable=["live SP-API", "Brand Analytics"], mode="mock")
    payload = {"scoring_version": "V1.4D", "marketplace_id": "A2VIGQ35RCS4UG", "generated_at": datetime.now(timezone.utc).isoformat(), "mode": "mock", "analyses": [{"name": a.name, "opportunity_score": a.opportunity_score, "data_confidence_score": a.data_confidence_score} for a in analyses]}
    paths = write_report(content, payload, "mock-product-opportunities")
    _persist_run(analyses, filters or {}, paths, mode="mock")
    normalized = Path("research/normalized/mock-latest.json")
    normalized.parent.mkdir(parents=True, exist_ok=True)
    normalized.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return paths


def _persist_run(analyses: list[NicheAnalysis], filters: dict[str, Any], report_paths: tuple[Path, Path], *, mode: str) -> None:
    db = ScoutDatabase()
    db.initialize()
    now = datetime.now(timezone.utc).isoformat()
    run_id = db.start_run(now, mode, filters)
    with db.connect() as connection:
        for analysis in analyses:
            connection.execute("INSERT INTO search_queries(run_id, query, number_of_results, observed_at) VALUES(?,?,?,?)", (run_id, analysis.name, analysis.catalog_result_count, now))
            for product in analysis.products:
                connection.execute("INSERT OR IGNORE INTO products(asin,title,brand,product_type,first_seen_at) VALUES(?,?,?,?,?)", (product.asin, product.title, product.brand, product.product_type, product.observed_at))
                connection.execute("INSERT INTO product_observations(run_id,asin,marketplace_id,source,observation_kind,payload_json,observed_at) VALUES(?,?,?,?,?,?,?)", (run_id, product.asin, "A2VIGQ35RCS4UG", product.source, "observed" if mode == "live" else "mock", json.dumps(product.as_dict()), product.observed_at))
                if product.price_aed is not None:
                    connection.execute("INSERT INTO prices(asin,marketplace_id,price,currency,price_type,source,observed_at) VALUES(?,?,?,?,?,?,?)", (product.asin, "A2VIGQ35RCS4UG", product.price_aed, "AED", "featured_or_observed", product.source, product.observed_at))
                if product.sales_rank is not None:
                    connection.execute("INSERT INTO sales_ranks(asin,marketplace_id,rank,source,observed_at) VALUES(?,?,?,?,?)", (product.asin, "A2VIGQ35RCS4UG", product.sales_rank, product.source, product.observed_at))
                if product.offer_count is not None:
                    connection.execute("INSERT INTO offers(asin,marketplace_id,offer_count,amazon_retail_present,source,observed_at) VALUES(?,?,?,?,?,?)", (product.asin, "A2VIGQ35RCS4UG", product.offer_count, product.amazon_retail_present, product.source, product.observed_at))
            economics = calculate_candidate_economics(analysis.name, price_statistics(p.price_aed for p in analysis.products)["median"])
            factors = {"demand": analysis.demand_score, "competition": analysis.competition_score, "economics": (economics.get("score") or {}).get("raw"), "risk": 100-analysis.risk_score}
            connection.execute("INSERT INTO niche_metrics(run_id,niche,metrics_json,observed_at) VALUES(?,?,?,?)", (run_id, analysis.name, json.dumps({"catalog_result_count": analysis.catalog_result_count, "risk_reasons": analysis.risk_reasons}), now))
            connection.execute("INSERT INTO opportunity_scores(run_id,niche,score,confidence_score,factors_json,scoring_version,calculated_at) VALUES(?,?,?,?,?,?,?)", (run_id, analysis.name, analysis.opportunity_score, analysis.data_confidence_score, json.dumps(factors), "V1.4D", now))
        connection.execute("INSERT INTO reports(run_id,markdown_path,json_path,created_at) VALUES(?,?,?,?)", (run_id, str(report_paths[0]), str(report_paths[1]), now))
        connection.execute("UPDATE research_runs SET completed_at=? WHERE id=?", (now, run_id))
