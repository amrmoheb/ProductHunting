from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .sources.serpapi import SerpApiBudget, SerpApiCache, SerpApiSource, normalize_product_response, normalize_search_response


def merge_serpapi_usage(*phases: dict | None, configured_max_calls: int | None = None) -> dict:
    """Accumulate phase counters into the canonical complete-run usage record."""
    items=[item for item in phases if item]
    if not items: return {}
    attempted=sum(int(x.get("calls_attempted",0)) for x in items)
    configured_max=max([int(x.get("configured_max_calls",0)) for x in items]+[attempted,configured_max_calls or 0])
    unique=lambda key: list(dict.fromkeys(value for item in items for value in item.get(key,[])))
    purposes=[]; seen=set()
    for item in items:
        for purpose in item.get("purpose_for_each_call",[]):
            fingerprint=purpose.get("fingerprint") or json.dumps(purpose,sort_keys=True)
            if fingerprint not in seen: seen.add(fingerprint); purposes.append(purpose)
    return {"configured":any(bool(x.get("configured")) for x in items),"enabled":any(bool(x.get("enabled")) for x in items),"configured_max_calls":configured_max,"calls_attempted":attempted,"calls_succeeded":sum(int(x.get("calls_succeeded",0)) for x in items),"calls_failed":sum(int(x.get("calls_failed",0)) for x in items),"calls_saved_by_cache":sum(int(x.get("calls_saved_by_cache",0)) for x in items),"calls_remaining":max(0,configured_max-attempted),"estimated_cost_usd":sum(float(x.get("estimated_cost_usd",0) or 0) for x in items),"keywords_queried":unique("keywords_queried"),"asins_queried":unique("asins_queried"),"product_detail_calls":sum(int(x.get("product_detail_calls",0)) for x in items),"purpose_for_each_call":purposes,"local_budget_note":"Canonical complete local run usage; not SerpApi account quota."}


def _relevance(keyword: str):
    tokens={x.lower() for x in keyword.split() if len(x)>2}
    required=max(1,(len(tokens)+1)//2)
    def check(result):
        title=str(result.get("title") or "").lower()
        if not result.get("asin") or not title: return False,"missing ASIN/title"
        if any(word in title for word in ("book","kindle","replacement part","spare part")): return False,"media/replacement part"
        if tokens and sum(token in title for token in tokens)<required: return False,"keyword/use-case mismatch"
        return True,None
    return check


def run(candidates: list[tuple[str,str]], *, output: str | Path, max_calls: int | None = None, product_deep_dives: list[tuple[str,str]] | None = None, base_bundle: str | Path | None = None) -> Path:
    if len(candidates)>15: raise ValueError("Structured validation phase supports at most 15 candidates per batch")
    budget=SerpApiBudget.from_environment()
    configured_run_max=budget.max_calls
    if max_calls is not None: budget.max_calls=min(budget.max_calls,max_calls)
    source=SerpApiSource(); cache=SerpApiCache(); now=datetime.now(timezone.utc); timestamp=now.isoformat().replace("+00:00","Z")
    base=json.loads(Path(base_bundle).read_text(encoding="utf-8")) if base_bundle else None
    products=list(base.get("products",[])) if base else []; evidence=list(base.get("evidence",[])) if base else []; errors=list(base.get("provider_errors",[])) if base else []; relevance_runs=[]
    for niche,keyword in candidates:
        try:
            response,state=source.execute(source.search_params(keyword),budget,cache,f"structured validation: {niche}")
            if response is None:
                errors.append({"provider":"serpapi","purpose":niche,"error_type":"request_failed","message":state}); continue
            normalized=normalize_search_response(response,niche=niche,keyword=keyword,run_id=f"serpapi-{now:%Y%m%d%H%M%S}",retrieved_at=timestamp,relevant=_relevance(keyword))
            products.extend(normalized["products"]); evidence.extend(normalized["evidence"]); relevance_runs.append({"niche":niche,"keyword":keyword,"target_commercial_profile":normalized["target_commercial_profile"],"aggregates":normalized["aggregates"],"classified_results":normalized["all_classified_results"],"excluded_results":normalized["excluded_results"]})
        except (PermissionError,ValueError) as exc:
            errors.append({"provider":"serpapi","purpose":niche,"error_type":type(exc).__name__,"message":str(exc).replace(os.getenv('SERPAPI_API_KEY','__never__'),'[REDACTED]')})
            if isinstance(exc,PermissionError) and budget.calls_remaining<=budget.reserve_calls: break
    for niche,asin in product_deep_dives or []:
        try:
            response,state=source.execute(source.product_params(asin),budget,cache,f"representative ASIN deep dive: {niche}")
            if response is None:
                errors.append({"provider":"serpapi","purpose":niche,"error_type":"request_failed","message":state}); continue
            normalized=normalize_product_response(response,niche=niche,keyword=asin,run_id=f"serpapi-{now:%Y%m%d%H%M%S}",retrieved_at=timestamp)
            products.extend(normalized["products"]); evidence.extend(normalized["evidence"])
        except (PermissionError,ValueError) as exc:
            errors.append({"provider":"serpapi","purpose":niche,"error_type":type(exc).__name__,"message":str(exc).replace(os.getenv('SERPAPI_API_KEY','__never__'),'[REDACTED]')})
            if isinstance(exc,PermissionError): break
    prior=base.get("research_run",{}) if base else {}; prior_funnel=prior.get("candidate_funnel",{})
    current_usage=budget.usage(configured=bool(os.getenv("SERPAPI_API_KEY")))
    bundle={"research_run":{"id":f"serpapi-{now:%Y%m%d%H%M%S}","slug":"serpapi-amazon-uae-validation","marketplace":"amazon.ae","started_at":prior.get("started_at",timestamp),"evidence_cutoff":timestamp,"filters":prior.get("filters",{"price_min_aed":50,"price_max_aed":150}),"candidate_funnel":{"generated":prior_funnel.get("generated",max(60,len(candidates))),"screened":prior_funnel.get("screened",len(candidates))}},"keywords":list(dict.fromkeys((list(base.get("keywords",[])) if base else [])+[k for _,k in candidates])),"products":products,"evidence":evidence,"source_summary":{"SerpApi":"USED" if any(x.get('source_provider')=='serpapi' for x in evidence) else "FAILED"},"serpapi_usage":merge_serpapi_usage(base.get("serpapi_usage") if base else None,current_usage,configured_max_calls=configured_run_max),"serpapi_phase_usage":[*(base.get("serpapi_phase_usage",[]) if base else []),current_usage],"serpapi_relevance":relevance_runs,"provider_errors":errors}
    path=Path(output); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(bundle,indent=2),encoding="utf-8"); return path


def main() -> int:
    parser=argparse.ArgumentParser(description="Use bounded SerpApi Amazon.ae searches for screened niches")
    parser.add_argument("--candidate",action="append",required=True,help="NICHE=KEYWORD; repeat up to 15 times")
    parser.add_argument("--product",action="append",default=[],help="NICHE=ASIN representative product deep dive")
    parser.add_argument("--output",required=True); parser.add_argument("--max-calls",type=int); parser.add_argument("--base-bundle")
    args=parser.parse_args(); candidates=[]
    for value in args.candidate:
        if "=" not in value: parser.error("--candidate must be NICHE=KEYWORD")
        candidates.append(tuple(value.split("=",1)))
    products=[]
    for value in args.product:
        if "=" not in value: parser.error("--product must be NICHE=ASIN")
        products.append(tuple(value.split("=",1)))
    try: path=run(candidates,output=args.output,max_calls=args.max_calls,product_deep_dives=products,base_bundle=args.base_bundle)
    except (ValueError,PermissionError) as exc: print(f"SerpApi validation stopped safely: {exc}",file=__import__('sys').stderr); return 2
    print(f"Wrote structured Amazon.ae evidence: {path}"); return 0


if __name__=="__main__": raise SystemExit(main())
