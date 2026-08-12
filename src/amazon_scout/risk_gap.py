from __future__ import annotations

from typing import Any

AUTHORITATIVE_SOURCE_PRIORITY = ["moiat.gov.ae", "dm.gov.ae", "u.ae", "sell.amazon.ae"]


def risk_only_gaps(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps=[]
    for item in analyses:
        gates=item["gates"]
        if gates["price"]["gate"] and gates["demand"]["gate"] and gates["competition"]["gate"] and not gates["risk"]["gate"]:
            gaps.append({"niche":item["niche"],"failed_gate":"risk","zero_paid_provider_only":True,"serpapi_calls_allowed":0,"questions":["UAE conformity or category-specific compliance requirements","hazardous/material/chemical classification","food-contact, electrical, wireless, or children's safety implications","size, weight, and logistics handling risk","trademark, design, and counterfeit exposure"],"preferred_domains":list(AUTHORITATIVE_SOURCE_PRIORITY)})
    return gaps


def build_risk_gap_plan(analyses: list[dict[str, Any]], serpapi_usage: dict[str, Any] | None = None) -> dict[str, Any]:
    before=int((serpapi_usage or {}).get("calls_attempted",0))
    return {"triggered":bool(risk_only_gaps(analyses)),"candidates":risk_only_gaps(analyses),"serpapi_calls_before":before,"serpapi_calls_after":before,"additional_serpapi_calls":0,"orchestrator":"codex_live_web","instruction":"Research only authoritative UAE/public sources, ingest explicit risk evidence, then rerun deterministic analytics. Absence of a restriction is not LOW risk."}
