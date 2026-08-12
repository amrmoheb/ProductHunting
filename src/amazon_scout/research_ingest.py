from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .database import ScoutDatabase
from .evidence import freshness_for, load_bundle, parse_aware_datetime, utc_iso
from .research_pipeline import analyze_evidence_bundle
from .research_report import render_research_report
from .risk_gap import build_risk_gap_plan
from .serpapi_research import merge_serpapi_usage


def ingest(path: str | Path, database: str | Path = "data/scout.db", *, quarantine_future: bool = False, slug_suffix: str = "", additional_evidence: str | Path | None = None, usage_base: str | Path | None = None, usage_max_calls: int | None = None) -> tuple[Path, Path, int]:
    generated_at = datetime.now(timezone.utc)
    if additional_evidence:
        raw=json.loads(Path(path).read_text(encoding="utf-8")); extra=json.loads(Path(additional_evidence).read_text(encoding="utf-8")); raw["evidence"].extend(extra["evidence"])
        from .evidence import validate_bundle
        raw,records=validate_bundle(raw,validation_time=generated_at,quarantine_future=quarantine_future)
    else: raw, records = load_bundle(path, validation_time=generated_at, quarantine_future=quarantine_future)
    if usage_base:
        base_usage=json.loads(Path(usage_base).read_text(encoding="utf-8")).get("serpapi_usage")
        raw["serpapi_usage"]=merge_serpapi_usage(base_usage,raw.get("serpapi_usage"),configured_max_calls=usage_max_calls)
    analyses = analyze_evidence_bundle(raw, records, generated_at=generated_at)
    raw["risk_gap_research_plan"] = build_risk_gap_plan(analyses, raw.get("serpapi_usage"))
    report = render_research_report(raw, analyses, generated_at=generated_at)
    db = ScoutDatabase(database); db.initialize()
    now = utc_iso(generated_at)
    invalid_run_fields = {item["field"] for item in raw.get("_validation_errors", [])}
    started = now if "started_at" in invalid_run_fields else utc_iso(parse_aware_datetime(str(raw["research_run"].get("started_at", now)), "research_run.started_at"))
    run_id = db.start_run(started, "research", raw["research_run"].get("filters", {}))
    with db.connect() as connection:
        for record in records:
            fresh = freshness_for(record, generated_at).value
            connection.execute("INSERT OR IGNORE INTO evidence_records(id,run_id,external_run_id,metric_name,metric_value_json,metric_unit,asin,keyword,niche,marketplace,source_provider,source_type,source_url,source_title,observed_at,retrieved_at,confidence,is_estimate,notes,market_relevance,source_timezone,evidence_freshness) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (record.id, run_id, record.research_run_id, record.metric_name, json.dumps(record.metric_value), record.metric_unit, record.asin, record.keyword, record.niche, record.marketplace, record.source_provider, record.source_type, record.source_url, record.source_title, record.observed_at, record.retrieved_at, record.confidence.value, int(record.is_estimate), record.notes, record.market_relevance.value, record.source_timezone, fresh))
            connection.execute("INSERT OR IGNORE INTO research_run_evidence(run_id,evidence_id) VALUES(?,?)", (run_id, record.id))
        for item in analyses:
            evidence_ids = [r.id for r in item["evidence"]]
            derived=(("demand_score", item["demand_score"]), ("competition_score", item["competition_score"]), ("risk_score", item["risk_score"]), ("preliminary_opportunity_score", item["preliminary_opportunity_score"]), ("validated_opportunity_score", item["validated_opportunity_score"]), ("data_confidence_score", item["data_confidence_score"]))
            if raw.get("v13_economics"):
                derived += (("economics_score", item.get("economics",{}).get("score",{}).get("raw")), ("economics_confidence", item.get("economics",{}).get("confidence")))
            for metric, value in derived:
                connection.execute("INSERT INTO derived_metrics(run_id,niche,metric_name,metric_value_json,metric_unit,evidence_ids_json,calculated_at) VALUES(?,?,?,?,?,?,?)", (run_id, item["niche"], metric, json.dumps(value), "score_0_100", json.dumps(evidence_ids), now))
            serializable = {k:v for k,v in item.items() if k not in {"evidence","products"}}
            connection.execute("INSERT INTO niche_metrics(run_id,niche,metrics_json,observed_at) VALUES(?,?,?,?)", (run_id, item["niche"], json.dumps(serializable, default=str), now))
            connection.execute("INSERT INTO research_candidates(run_id,niche,candidate_type,observed_market_price_aed,observed_price_min_aed,observed_price_max_aed,proposed_selling_price_aed,bundle_hypothesis_price_aed,fee_calculation_price_aed,preliminary_score,validated_score,data_confidence_score,recommendation_tier,gates_json,components_json,freshness,calculated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (run_id,item["niche"],item["candidate_type"],item["observed_market_price_aed"],item["observed_price_min_aed"],item["observed_price_max_aed"],item["proposed_selling_price_aed"],item["bundle_hypothesis_price_aed"],item["fee_calculation_price_aed"],item["preliminary_opportunity_score"],item["validated_opportunity_score"],item["data_confidence_score"],item["recommendation_tier"],json.dumps(item["gates"]),json.dumps(item["components"]),item["evidence_freshness"],now))
            if item["preliminary_opportunity_score"] is not None:
                connection.execute("INSERT INTO opportunity_scores(run_id,niche,score,confidence_score,factors_json,scoring_version,calculated_at,preliminary_score,validated_score,recommendation_tier) VALUES(?,?,?,?,?,?,?,?,?,?)", (run_id,item["niche"],item["preliminary_opportunity_score"],item["data_confidence_score"],json.dumps(item["factors"]),"research-v1.3",now,item["preliminary_opportunity_score"],item["validated_opportunity_score"],item["recommendation_tier"]))
        usage=raw.get("serpapi_usage")
        if usage:
            connection.execute("INSERT OR REPLACE INTO serpapi_usage(run_id,configured,enabled,configured_max_calls,calls_attempted,calls_succeeded,calls_failed,calls_saved_by_cache,calls_remaining,estimated_cost_usd,keywords_json,asins_json,purposes_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(run_id,int(bool(usage.get('configured'))),int(bool(usage.get('enabled'))),int(usage.get('configured_max_calls',0)),int(usage.get('calls_attempted',0)),int(usage.get('calls_succeeded',0)),int(usage.get('calls_failed',0)),int(usage.get('calls_saved_by_cache',0)),int(usage.get('calls_remaining',0)),usage.get('estimated_cost_usd'),json.dumps(usage.get('keywords_queried',[])),json.dumps(usage.get('asins_queried',[])),json.dumps(usage.get('purpose_for_each_call',[]))))
        for error in raw.get("provider_errors",[]):
            connection.execute("INSERT INTO provider_errors(run_id,provider,purpose,error_type,message,occurred_at) VALUES(?,?,?,?,?,?)",(run_id,error.get('provider','serpapi'),error.get('purpose'),error.get('error_type','provider_error'),error.get('message','Provider failed; evidence remains unknown.'),now))
        for relevance in raw.get("serpapi_relevance",[]):
            connection.execute("INSERT INTO serpapi_relevance_runs(run_id,niche,keyword,rule_version,aggregates_json,classified_results_json,excluded_results_json) VALUES(?,?,?,?,?,?,?)",(run_id,relevance["niche"],relevance["keyword"],"v1.2.4",json.dumps(relevance["aggregates"]),json.dumps(relevance["classified_results"]),json.dumps(relevance["excluded_results"])))
        connection.execute("UPDATE research_runs SET completed_at=?,generated_at=?,evidence_cutoff=?,candidate_funnel_json=? WHERE id=?", (now,now,raw["research_run"]["evidence_cutoff"],json.dumps(raw["research_run"]["candidate_funnel"]),run_id))
    slug = str(raw["research_run"].get("slug", "research")) + slug_suffix
    stamp = generated_at.astimezone().strftime("%Y-%m-%d-%H%M%S")
    md = Path("reports") / f"{stamp}-{slug}.md"; js = md.with_suffix(".json")
    md.parent.mkdir(parents=True, exist_ok=True); md.write_text(report, encoding="utf-8")
    normalized = {"research_run": raw["research_run"], "serpapi_usage": raw.get("serpapi_usage", {}), "risk_gap_research_plan": raw.get("risk_gap_research_plan", {}), "v124_audit": {k:v for k,v in raw.get("v124_audit",{}).items() if k != "baseline_report"}, "v13_economics": raw.get("v13_economics", {}), "validation_errors": raw.get("_validation_errors", []), "quarantined_evidence": raw.get("_quarantined_evidence", []), "analyses": [{k:v for k,v in item.items() if k != "evidence"} for item in analyses]}
    payload = json.dumps(normalized, indent=2, default=str)
    js.write_text(payload, encoding="utf-8")
    Path("research/normalized").mkdir(parents=True, exist_ok=True)
    (Path("research/normalized") / f"{stamp}-{slug}.json").write_text(payload, encoding="utf-8")
    with db.connect() as connection:
        connection.execute("INSERT INTO reports(run_id,markdown_path,json_path,created_at) VALUES(?,?,?,?)", (run_id,str(md),str(js),now))
    return md, js, run_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and ingest a Codex research evidence bundle")
    parser.add_argument("bundle"); parser.add_argument("--database", default="data/scout.db"); parser.add_argument("--usage-base",help="Earlier phase bundle whose SerpApi usage is accumulated into complete-run totals"); parser.add_argument("--usage-max-calls",type=int,help="Persisted complete-run ceiling when phase bundles used smaller caps")
    parser.add_argument("--quarantine-future", action="store_true", help="Exclude impossible future records and continue; default is rejection")
    parser.add_argument("--slug-suffix", default=""); parser.add_argument("--additional-evidence",help="Zero-paid gap-directed evidence fragment with an evidence array")
    args = parser.parse_args()
    try: md, js, run_id = ingest(args.bundle,args.database,quarantine_future=args.quarantine_future,slug_suffix=args.slug_suffix,additional_evidence=args.additional_evidence,usage_base=args.usage_base,usage_max_calls=args.usage_max_calls)
    except (ValueError,KeyError,json.JSONDecodeError) as exc:
        print(f"Evidence rejected: {exc}", file=__import__("sys").stderr); return 2
    print(f"Ingested research run {run_id}; report: {md}; JSON: {js}"); return 0


if __name__ == "__main__": raise SystemExit(main())
