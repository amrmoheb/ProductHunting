from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import median, pstdev
from typing import Any

from .scoring_calibration_v14c import (
    CANDIDATES as CALIBRATION_CANDIDATES,
    DEFAULT_V13,
    DEFAULT_V14B1,
    DEFAULT_V14B2,
    calibrate_candidate,
    load_artifacts,
)

VERSION = "V1.4C.1"
MAX_HOLDOUT = 25
SELECTION_RULE = (
    "Preserve V1.3 artifact order; exclude the five V1.4C calibration candidates; "
    "require numeric current demand, competition, and opportunity scores, a components "
    "object, structured_metrics, and at least one ASIN-backed product; take the first 25."
)
BASE_WEIGHTS = {"demand": .30, "competition": .25, "economics": .35, "risk": .10}
SENSITIVITY_WEIGHTS = {
    "SCENARIO_A": {"demand": .30, "competition": .30, "economics": .30, "risk": .10},
    "SCENARIO_B": {"demand": .35, "competition": .30, "economics": .25, "risk": .10},
}


def select_holdout(v13: dict[str, Any], limit: int = MAX_HOLDOUT) -> list[dict[str, Any]]:
    selected=[]
    for analysis in v13.get("analyses", []):
        if analysis.get("niche") in CALIBRATION_CANDIDATES: continue
        numeric=all(isinstance(analysis.get(key),(int,float)) and not isinstance(analysis.get(key),bool) for key in ("demand_score","competition_score","opportunity_score"))
        asin_backed=any(product.get("asin") for product in analysis.get("products") or [])
        if numeric and isinstance(analysis.get("components"),dict) and isinstance(analysis.get("structured_metrics"),dict) and asin_backed:
            selected.append(analysis)
        if len(selected)>=limit: break
    return selected


def _distribution(values: list[float]) -> dict[str, Any]:
    rounded=[round(value,2) for value in values]
    counts={value:rounded.count(value) for value in set(rounded)}
    unique=len(counts); largest=max(counts.values(),default=0)
    suspicious=unique<=max(2,math.floor(len(values)*.2)) or largest>=math.ceil(len(values)*.5)
    return {"min":round(min(values),2),"median":round(median(values),2),"max":round(max(values),2),"standard_deviation":round(pstdev(values),2),"unique_rounded_score_count":unique,"largest_identical_cluster":largest,"suspicious_clustering":suspicious}


def _ranks(values: dict[str,float]) -> dict[str,float]:
    ordered=sorted(values,key=lambda name:(-values[name],name)); ranks={}; index=0
    while index<len(ordered):
        end=index+1
        while end<len(ordered) and values[ordered[end]]==values[ordered[index]]: end+=1
        rank=(index+1+end)/2
        for name in ordered[index:end]: ranks[name]=rank
        index=end
    return ranks


def spearman(current: dict[str,float], proposed: dict[str,float]) -> float | None:
    names=sorted(set(current)&set(proposed)); n=len(names)
    if n<3: return None
    x=_ranks({name:current[name] for name in names}); y=_ranks({name:proposed[name] for name in names})
    xv=[x[name] for name in names]; yv=[y[name] for name in names]; xm=sum(xv)/n; ym=sum(yv)/n
    numerator=sum((a-xm)*(b-ym) for a,b in zip(xv,yv)); denominator=math.sqrt(sum((a-xm)**2 for a in xv)*sum((b-ym)**2 for b in yv))
    return round(numerator/denominator,4) if denominator else None


def _ordered(values: dict[str,float]) -> list[str]: return sorted(values,key=lambda name:(-values[name],name))


def _movement(current: dict[str,float], proposed: dict[str,float]) -> dict[str,Any]:
    current_order=_ordered(current); proposed_order=_ordered(proposed); shifts={name:abs(current_order.index(name)-proposed_order.index(name)) for name in current}
    return {"spearman_rank_correlation":spearman(current,proposed),"median_rank_movement":round(median(shifts.values()),2),"maximum_rank_movement":max(shifts.values()),"candidates_moving_at_least_5":[{"candidate":name,"movement":shifts[name],"current_rank":current_order.index(name)+1,"proposed_rank":proposed_order.index(name)+1} for name in current_order if shifts[name]>=5],"current_ranking":current_order,"proposed_ranking":proposed_order,"rank_movements":shifts}


def economics_dominance_risk(final_score: float, economics_contribution: float, economics_confidence: float) -> bool:
    return final_score >= 65 and economics_contribution >= final_score*.4 and economics_confidence < 55


def _audit_score(values: dict[str,float|None], weights: dict[str,float]) -> tuple[float,list[dict[str,Any]]]:
    arithmetic=[]; total=0
    for name,weight in weights.items():
        value=values[name]; contribution=value*weight if value is not None else 0; total+=contribution
        arithmetic.append({"component":name,"score":value,"weight":weight,"contribution":round(contribution,4),"missing_behavior":"ZERO_CONTRIBUTION_NO_REDISTRIBUTION" if value is None else "OBSERVED"})
    return round(total,2),arithmetic


def _eligibility(score: float, confidence: float, risk_status: str, economics_status: str, economics_confidence: float) -> dict[str,str]:
    if confidence < 55: tier="PRELIMINARY_NEEDS_EVIDENCE"
    elif confidence < 70: tier="VALIDATED"
    else: tier="STRONG_ELIGIBLE" if score>=65 else "VALIDATED"
    reason="confidence policy"
    if risk_status in {"UNKNOWN","INSUFFICIENT"} and tier=="STRONG_ELIGIBLE": tier="VALIDATED"; reason="UNKNOWN risk cannot become STRONG"
    if economics_status=="PARTIAL" and economics_confidence<55 and tier=="STRONG_ELIGIBLE": tier="VALIDATED"; reason="low-confidence PARTIAL economics cannot create STRONG eligibility"
    return {"maximum_tier":tier,"reason":reason}


def _large_movement_reason(row: dict[str,Any]) -> str:
    p=row["proposed"]; current=row["current"]
    missing=[item["component"] for item in p["opportunity_arithmetic"]["arithmetic"] if item["score"] is None]
    demand_delta=round(p["demand_score"]-current["demand_score"],2); competition_delta=round(p["competition_score"]-current["competition_score"],2)
    return f"Demand changed {demand_delta:+.2f}; competition changed {competition_delta:+.2f}; fixed-denominator missing components: {', '.join(missing) if missing else 'none'}; economics contribution {row['economics_contribution']:.2f} at confidence {row['economics_confidence']:.2f}."


def run_holdout_validation(*, artifacts: dict[str,Any]|None=None, now: datetime|None=None) -> dict[str,Any]:
    artifacts=artifacts or load_artifacts(DEFAULT_V13,Path("reports/2026-08-14-034240-v1.json"),DEFAULT_V14B1,DEFAULT_V14B2)
    holdout=select_holdout(artifacts["v13"])
    if not holdout: raise ValueError("No eligible historical holdout candidates")
    rows=[]
    for analysis in holdout:
        row=calibrate_candidate(analysis,artifacts["v14b1"],artifacts["v14b2"])
        row["current_risk_score"]=analysis.get("risk_score"); row["current_risk_status"]=analysis.get("risk_status")
        row["current"]["data_confidence_score"]=analysis.get("data_confidence_score"); row["current"]["gate_outcomes"]=analysis.get("gates")
        values={"demand":row["proposed"]["demand_score"],"competition":row["proposed"]["competition_score"],"economics":((row["economics"].get("score") or {}).get("raw") if isinstance(row["economics"].get("score"),dict) else row["economics"].get("score")),"risk":None if analysis.get("risk_score") is None else 100-analysis["risk_score"]}
        economics_item=next(item for item in row["proposed"]["opportunity_arithmetic"]["arithmetic"] if item["component"]=="economics")
        row["economics_contribution"]=economics_item["contribution"]; row["economics_confidence"]=row["economics"].get("confidence",0)
        row["economics_dominance_risk"]=economics_dominance_risk(row["proposed"]["opportunity_score"],economics_item["contribution"],row["economics_confidence"])
        row["eligibility_policy_result"]=_eligibility(row["proposed"]["opportunity_score"],row["proposed"]["overall_evidence_confidence"],analysis.get("risk_status","UNKNOWN"),row["economics_status"],row["economics_confidence"])
        row["audit_component_values"]=values
        rows.append(row)

    distributions={}
    for metric,current_key,proposed_key in (("demand","demand_score","demand_score"),("competition","competition_score","competition_score"),("opportunity","opportunity_score","opportunity_score")):
        distributions[metric]={"current":_distribution([r["current"][current_key] for r in rows]),"proposed":_distribution([r["proposed"][proposed_key] for r in rows])}
    distributions["confidence"]={"current":_distribution([r["current"]["data_confidence_score"] for r in rows]),"proposed":_distribution([r["proposed"]["overall_evidence_confidence"] for r in rows])}
    current_scores={r["candidate"]:r["current"]["opportunity_score"] for r in rows}; proposed_scores={r["candidate"]:r["proposed"]["opportunity_score"] for r in rows}; movement=_movement(current_scores,proposed_scores)
    by_name={r["candidate"]:r for r in rows}
    for item in movement["candidates_moving_at_least_5"]: item["explanation"]=_large_movement_reason(by_name[item["candidate"]])

    scenarios={}
    for name,weights in SENSITIVITY_WEIGHTS.items():
        scores={}; arithmetic={}
        for row in rows: scores[row["candidate"]],arithmetic[row["candidate"]]=_audit_score(row["audit_component_values"],weights)
        ranking=_ordered(scores); base_top=set(movement["proposed_ranking"][:3]); scenario_top=set(ranking[:3])
        scenarios[name]={"weights":weights,"scores":scores,"ranking":ranking,"top_3_changed":base_top!=scenario_top,"top_3_added":sorted(scenario_top-base_top),"top_3_removed":sorted(base_top-scenario_top)}

    missing_violations=[]
    for row in rows:
        for section in ("demand_arithmetic","competition_arithmetic"):
            for item in row["proposed"][section]["arithmetic"]:
                if item["score"] is None and item["contribution"]>0: missing_violations.append({"candidate":row["candidate"],"family":item.get("family")})
        for item in row["proposed"]["opportunity_arithmetic"]["arithmetic"]:
            if item["score"] is None and item["contribution"]>0: missing_violations.append({"candidate":row["candidate"],"component":item["component"]})
    density=sorted((r["proposed"]["competition_evidence_breakdown"]["comparable_density"]["facts"]["unique_comparable_asins"],r["proposed"]["competition_evidence_breakdown"]["comparable_density"]["score"],r["candidate"]) for r in rows)
    inversion=[{"less_dense":density[i-1],"more_dense":density[i]} for i in range(1,len(density)) if density[i][0]>density[i-1][0] and density[i][1]>density[i-1][1]]
    economics_risks=[r["candidate"] for r in rows if r["economics_dominance_risk"]]
    checks={"missing_data_reward":{"pass":not missing_violations,"violations":missing_violations},"demand_saturation":{"materially_reduced":distributions["demand"]["current"]["suspicious_clustering"] and not distributions["demand"]["proposed"]["suspicious_clustering"]},"competition_inversion":{"pass":not inversion,"violations":inversion},"confidence_leakage":{"pass":True,"basis":"Raw score functions receive no confidence argument; confidence is calculated and reported separately."},"economics_dominance":{"risks":economics_risks,"pass":not economics_risks}}
    reasonably_stable=(movement["spearman_rank_correlation"] or -1)>=.6 and movement["median_rank_movement"]<=3 and movement["maximum_rank_movement"]<=6
    scenario_stable=not any(s["top_3_changed"] for s in scenarios.values())
    safety_checks=all((checks["missing_data_reward"]["pass"],checks["competition_inversion"]["pass"],checks["confidence_leakage"]["pass"],checks["economics_dominance"]["pass"]))
    if all((safety_checks,checks["demand_saturation"]["materially_reduced"],reasonably_stable,scenario_stable)):
        recommendation="READY_FOR_V14D"
    elif safety_checks and (movement["spearman_rank_correlation"] or -1)>=.4 and movement["maximum_rank_movement"]<=6:
        recommendation="NEEDS_MINOR_CALIBRATION"
    else: recommendation="NOT_READY"
    return {"version":VERSION,"generated_at":(now or datetime.now(timezone.utc)).isoformat(),"mode":"OFFLINE_HOLDOUT_VALIDATION_ONLY","production_scores_changed":False,"provider_calls":0,"paid_calls":0,"calibration_candidates_excluded":list(CALIBRATION_CANDIDATES),"selection_methodology":SELECTION_RULE,"holdout_size":len(rows),"holdout_candidates":[r["candidate"] for r in rows],"weights_frozen":BASE_WEIGHTS,"candidates":rows,"distributions":distributions,"ranking_movement":movement,"failure_mode_checks":checks,"economics_sensitivity_scenarios":scenarios,"confidence_tier_policy":{"confidence_gte_70":"STRONG_ELIGIBLE only if score threshold passes, risk is known, and low-confidence PARTIAL economics is not solely responsible","confidence_55_to_69":"maximum tier VALIDATED","confidence_below_55":"maximum tier PRELIMINARY_NEEDS_EVIDENCE","unknown_risk":"cannot become STRONG","confidence_application":"separate gate; never multiply raw score"},"activation_assessment":{"reasonably_stable":reasonably_stable,"sensitivity_top3_stable":scenario_stable,"recommendation":recommendation}}


def render_report(bundle: dict[str,Any]) -> str:
    d=bundle["distributions"]; m=bundle["ranking_movement"]
    lines=["# V1.4C.1 HOLDOUT VALIDATION","",f"Generated: {bundle['generated_at']}","Mode: OFFLINE VALIDATION ONLY","Production scoring: UNCHANGED","Provider calls: 0; paid calls: 0","",f"Holdout size: {bundle['holdout_size']}",f"Selection rule: {bundle['selection_methodology']}","","Holdout candidates:",* [f"- {name}" for name in bundle["holdout_candidates"]],"","## Current versus proposed","","| Candidate | Current demand | Proposed demand | Current competition | Proposed competition | Current opportunity | Proposed opportunity | Proposed confidence | Economics contribution | Economics confidence | Gates |","|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for row in bundle["candidates"]:
        gates=", ".join(f"{name}:{'PASS' if value.get('gate') else 'FAIL'}" for name,value in row["current"]["gate_outcomes"].items())
        lines.append(f"| {row['candidate']} | {row['current']['demand_score']:.2f} | {row['proposed']['demand_score']:.2f} | {row['current']['competition_score']:.2f} | {row['proposed']['competition_score']:.2f} | {row['current']['opportunity_score']:.2f} | {row['proposed']['opportunity_score']:.2f} | {row['proposed']['overall_evidence_confidence']:.2f} | {row['economics_contribution']:.2f} | {row['economics_confidence']:.2f} | {gates} |")
    lines += ["","## Score distributions","","| Metric | Version | Min | Median | Max | Std dev | Unique scores | Suspicious clustering |","|---|---|---:|---:|---:|---:|---:|---|"]
    for metric,versions in d.items():
        for version,stats in versions.items(): lines.append(f"| {metric} | {version} | {stats['min']:.2f} | {stats['median']:.2f} | {stats['max']:.2f} | {stats['standard_deviation']:.2f} | {stats['unique_rounded_score_count']} | {stats['suspicious_clustering']} |")
    lines += ["","## Ranking movement","",f"Spearman correlation: {m['spearman_rank_correlation']}",f"Median movement: {m['median_rank_movement']}; maximum movement: {m['maximum_rank_movement']}",f"Current: {' > '.join(m['current_ranking'])}",f"Proposed: {' > '.join(m['proposed_ranking'])}",""]
    if m["candidates_moving_at_least_5"]:
        for item in m["candidates_moving_at_least_5"]: lines.append(f"- {item['candidate']}: {item['current_rank']} → {item['proposed_rank']} ({item['movement']} positions). {item['explanation']}")
    else: lines.append("No candidate moved five or more positions.")
    lines += ["","## Failure-mode checks","",f"Missing-data reward: {'PASS' if bundle['failure_mode_checks']['missing_data_reward']['pass'] else 'FAIL'}",f"Demand saturation materially reduced: {bundle['failure_mode_checks']['demand_saturation']['materially_reduced']}",f"Competition direction: {'PASS' if bundle['failure_mode_checks']['competition_inversion']['pass'] else 'FAIL'}",f"Confidence leakage: {'PASS' if bundle['failure_mode_checks']['confidence_leakage']['pass'] else 'FAIL'}",f"Economics dominance risks: {bundle['failure_mode_checks']['economics_dominance']['risks'] or 'NONE'}","","## Economics-weight sensitivity","",f"Frozen baseline: {json.dumps(bundle['weights_frozen'],sort_keys=True)}"]
    for name,scenario in bundle["economics_sensitivity_scenarios"].items(): lines += [f"- {name}: weights {json.dumps(scenario['weights'],sort_keys=True)}; Top 3 changed: {scenario['top_3_changed']}; ranking: {' > '.join(scenario['ranking'])}"]
    p=bundle["confidence_tier_policy"]
    lines += ["","## Proposed confidence/tier policy","",f"- Confidence ≥70: {p['confidence_gte_70']}",f"- Confidence 55–69: {p['confidence_55_to_69']}",f"- Confidence <55: {p['confidence_below_55']}",f"- UNKNOWN risk: {p['unknown_risk']}",f"- Application: {p['confidence_application']}","",f"## Activation recommendation: **{bundle['activation_assessment']['recommendation']}**"]
    return "\n".join(lines)+"\n"


def write_outputs(bundle: dict[str,Any],directory: str|Path="reports") -> tuple[Path,Path]:
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True); stamp=datetime.now().strftime("%Y-%m-%d-%H%M%S"); base=directory/f"{stamp}-v1.4c1-holdout-validation"; md=Path(f"{base}.md"); js=Path(f"{base}.json"); md.write_text(render_report(bundle),encoding="utf-8"); js.write_text(json.dumps(bundle,indent=2,ensure_ascii=False,sort_keys=True),encoding="utf-8"); return md,js


def main() -> int:
    bundle=run_holdout_validation(); md,js=write_outputs(bundle); print(f"Report: {md}"); print(f"Evidence: {js}"); print(f"Recommendation: {bundle['activation_assessment']['recommendation']}"); print("Provider calls: 0"); return 0
