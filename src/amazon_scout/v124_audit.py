from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from .sources.serpapi import normalize_search_response


def reprocess_persisted_bundle(bundle: dict, baseline_report: dict | None = None) -> dict:
    """Reclassify persisted SerpApi rows without network or cache/provider access."""
    raw=deepcopy(bundle); retained_evidence=[row for row in raw.get("evidence",[]) if row.get("source_provider")!="serpapi"]
    retained_products=[row for row in raw.get("products",[]) if row.get("source_provider") not in {"serpapi",None}]
    rebuilt_products=[]; rebuilt_evidence=[]; rebuilt_runs=[]
    for index,run in enumerate(raw.get("serpapi_relevance",[])):
        niche=run["niche"]; keyword=run["keyword"]
        timestamps=[row.get("retrieved_at") for row in bundle.get("evidence",[]) if row.get("source_provider")=="serpapi" and row.get("niche")==niche and row.get("keyword")==keyword and row.get("retrieved_at")]
        retrieved=max(timestamps) if timestamps else raw["research_run"]["evidence_cutoff"]
        payload={"search_metadata":{"status":"Success"},"search_parameters":{"engine":"amazon","amazon_domain":"amazon.ae","k":keyword},"organic_results":run.get("classified_results",[])}
        normalized=normalize_search_response(payload,niche=niche,keyword=keyword,run_id=f"v124-cache-{index}",retrieved_at=retrieved)
        rebuilt_products.extend(normalized["products"]); rebuilt_evidence.extend(normalized["evidence"])
        rebuilt_runs.append({"niche":niche,"keyword":keyword,"target_commercial_profile":normalized["target_commercial_profile"],"aggregates":normalized["aggregates"],"classified_results":normalized["all_classified_results"],"excluded_results":normalized["excluded_results"]})
    raw["products"]=retained_products+rebuilt_products; raw["evidence"]=retained_evidence+rebuilt_evidence; raw["serpapi_relevance"]=rebuilt_runs
    prior_id=raw["research_run"].get("id"); raw["research_run"]["parent_run_id"]=prior_id; raw["research_run"]["id"]=f"{prior_id}-v124-audit"; raw["research_run"]["slug"]="resumed-diversified-hunt-v1.2.4-correctness-audit"
    raw["v124_audit"]={"release":"V1.2.4","provider_calls":0,"reprocessed_from_persisted_rows":len(rebuilt_runs),"baseline_report":baseline_report,"before_funnel":(baseline_report or {}).get("research_run",{}).get("candidate_funnel"),"canonical_generated":84,"canonical_screened":18}
    return raw


def main() -> int:
    parser=argparse.ArgumentParser(description="Offline V1.2.4 correctness reprocessing from persisted SerpApi rows")
    parser.add_argument("bundle"); parser.add_argument("--baseline-report"); parser.add_argument("--output",required=True); args=parser.parse_args()
    bundle=json.loads(Path(args.bundle).read_text(encoding="utf-8")); baseline=json.loads(Path(args.baseline_report).read_text(encoding="utf-8")) if args.baseline_report else None
    output=Path(args.output); output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(reprocess_persisted_bundle(bundle,baseline),indent=2),encoding="utf-8")
    print(f"Wrote offline V1.2.4 evidence: {output}"); return 0


if __name__=="__main__": raise SystemExit(main())
