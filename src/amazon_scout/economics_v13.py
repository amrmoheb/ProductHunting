from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .normalization import clamp


@dataclass(frozen=True)
class ProductPhysicalProfile:
    product_weight_kg: float | None
    packaged_weight_kg: float | None
    product_length_cm: float | None
    product_width_cm: float | None
    product_height_cm: float | None
    packaged_length_cm: float | None
    packaged_width_cm: float | None
    packaged_height_cm: float | None
    dimensional_weight_kg: float | None
    units_per_package: int
    pack_configuration: str
    source: str
    confidence: float

    def to_dict(self) -> dict[str, Any]: return asdict(self)


PHYSICAL_ESTIMATES={
    "long handle baseboard cleaning tool": ProductPhysicalProfile(None,.8,None,None,None,45,12,10,None,1,"one tool with pads","ESTIMATE",45),
    "washable ceiling fan blade sleeve duster": ProductPhysicalProfile(None,.45,None,None,None,40,10,8,None,1,"one duster kit","ESTIMATE",45),
    "adjustable airplane foot hammock": ProductPhysicalProfile(None,.3,None,None,None,24,16,5,None,1,"one foot hammock","ESTIMATE",45),
    "wood crochet blocking board": ProductPhysicalProfile(None,.9,None,None,None,30,30,4,None,1,"one board with pegs","ESTIMATE",45),
}


CATEGORY_MAP={
    "long handle baseboard cleaning tool": (["HOME","TOOLS_HOME_IMPROVEMENT"],"HOME",65,"Household cleaning tool; Home and Tools & Home Improvement are both plausible."),
    "washable ceiling fan blade sleeve duster": (["HOME","TOOLS_HOME_IMPROVEMENT"],"HOME",65,"Household cleaning tool; Home and Tools & Home Improvement are both plausible."),
    "adjustable airplane foot hammock": (["LUGGAGE","SPORTS"],"LUGGAGE",70,"Travel accessory most likely maps to Luggage; Sports remains a plausible alternative."),
    "wood crochet blocking board": (["HOME","OFFICE_PRODUCTS","ALL_OTHER"],"HOME",55,"Craft tool has no explicit fee-table craft category; Home, Office Products, and All Other are plausible."),
}


def load_economics_config(path: str | Path="config/amazon_uae_economics_v13.yaml") -> dict[str,Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def map_fee_categories(niche: str, config: dict[str,Any] | None=None) -> dict[str,Any]:
    cfg=config or load_economics_config(); categories,primary,confidence,reason=CATEGORY_MAP.get(niche,(["ALL_OTHER"],"ALL_OTHER",30,"No deterministic niche mapping; conservative All Other scenario only."))
    return {"amazon_fee_category":primary,"category_scenarios":categories,"category_confidence":confidence,"category_reason":reason,"category_source":cfg["sources"]["pricing"]}


def referral_fee(selling_price_aed: float, category: str, config: dict[str,Any] | None=None) -> dict[str,float]:
    cfg=config or load_economics_config(); rule=cfg["referral_fees"][category]
    rate=float(rule["rate"] if "rate" in rule else rule["rate_below_or_equal_50"] if selling_price_aed<=50 else rule["rate_above_50"])
    amount=round(max(float(rule["minimum_aed"]),selling_price_aed*rate),2)
    return {"category":category,"rate":rate,"minimum_aed":float(rule["minimum_aed"]),"amount_aed":amount,"source_url":cfg["sources"]["pricing"],"retrieved_at":cfg["retrieved_at"],"effective_date":cfg["effective_date"],"fee_rule_version":cfg["fee_rule_version"],"conditions":rule}


def fba_size_tier(profile: ProductPhysicalProfile) -> str | None:
    dims=(profile.packaged_length_cm,profile.packaged_width_cm,profile.packaged_height_cm); weight=profile.packaged_weight_kg
    if any(value is None for value in dims) or weight is None: return None
    longest,median,shortest=sorted((float(value) for value in dims),reverse=True)
    if longest<=20 and median<=15 and shortest<=1 and weight<=.1: return "SMALL_ENVELOPE"
    if longest<=33 and median<=23 and shortest<=2.5 and weight<=.5: return "STANDARD_ENVELOPE"
    if longest<=33 and median<=23 and shortest<=5 and weight<=1: return "LARGE_ENVELOPE"
    if longest<=45 and median<=34 and shortest<=26 and weight<=12: return "STANDARD_PARCEL"
    return "OVERSIZE"


def fba_fulfillment_fee(selling_price_aed: float, profile: ProductPhysicalProfile, config: dict[str,Any] | None=None) -> dict[str,Any]:
    cfg=config or load_economics_config(); tier=fba_size_tier(profile)
    provenance={"source_url":cfg["sources"]["pricing"],"retrieved_at":cfg["retrieved_at"],"effective_date":cfg["effective_date"],"fee_rule_version":cfg["fee_rule_version"]}
    if tier is None: return {"tier":None,"shipping_weight_kg":None,"fee_aed":None,"status":"UNKNOWN",**provenance}
    if selling_price_aed<=25: return {"tier":tier,"shipping_weight_kg":profile.packaged_weight_kg,"fee_aed":None,"status":"UNSUPPORTED_LOW_PRICE_TABLE",**provenance}
    weight=float(profile.packaged_weight_kg); table=cfg["fba_fulfillment_above_25_aed"][tier]
    for maximum,fee in table:
        if weight<=maximum: return {"tier":tier,"shipping_weight_kg":weight,"fee_aed":float(fee),"status":"ESTIMATED_FROM_OFFICIAL_TIER","conditions":{"maximum_shipping_weight_kg":maximum},**provenance}
    if tier=="OVERSIZE": return {"tier":tier,"shipping_weight_kg":weight,"fee_aed":round(41.5+max(0,weight-30),2),"status":"ESTIMATED_FROM_OFFICIAL_TIER","conditions":{"base_through_30kg_aed":41.5,"increment_per_kg_aed":1},**provenance}
    return {"tier":tier,"shipping_weight_kg":weight,"fee_aed":None,"status":"OUT_OF_TIER",**provenance}


def storage_fee(profile: ProductPhysicalProfile, months: float, config: dict[str,Any] | None=None) -> float | None:
    cfg=config or load_economics_config(); dims=(profile.packaged_length_cm,profile.packaged_width_cm,profile.packaged_height_cm)
    if any(value is None for value in dims): return None
    cubic_feet=float(dims[0])*float(dims[1])*float(dims[2])/28316.84
    return round(cubic_feet*float(cfg["conditions"]["storage_aed_per_cubic_foot_month"])*months,2)


def maximum_landed_cost_v13(price: float, target_margin: float, costs_before_product: float | None) -> float | None:
    if costs_before_product is None: return None
    return round(max(0,price*(1-target_margin)-costs_before_product),2)


def required_economics_raw(score_without_economics: float, target_score: float, weight: float=.20) -> float:
    return round(max(0.0, (target_score-score_without_economics)/weight), 2)


def score_with_economics(score_without_economics: float, economics_raw: float, weight: float=.20) -> float:
    return round(score_without_economics+clamp(economics_raw)*weight, 2)


def _supplier_target(max_landed: float | None, assumptions: dict[str,float], customs_rate: float, import_vat_rate: float) -> dict[str,float | None]:
    if max_landed is None: return {"maximum_supplier_product_cost_aed":None,"customs_duty_aed":None,"import_vat_cash_flow_aed":None,"recoverable_import_vat_aed":None}
    freight=assumptions["international_freight_aed"]; fixed=freight+assumptions["local_clearance_delivery_aed"]+assumptions["inspection_prep_aed"]+assumptions["inbound_to_amazon_aed"]
    product=max(0,(max_landed-fixed-customs_rate*freight)/(1+customs_rate)); duty=customs_rate*(product+freight); import_vat=import_vat_rate*(product+freight+duty)
    return {"maximum_supplier_product_cost_aed":round(product,2),"customs_duty_aed":round(duty,2),"import_vat_cash_flow_aed":round(import_vat,2),"recoverable_import_vat_aed":round(import_vat,2)}


def _scenario(price: float, category: str, profile: ProductPhysicalProfile, name: str, cfg: dict[str,Any]) -> dict[str,Any]:
    assumptions=cfg["scenario_assumptions"][name]; referral=referral_fee(price,category,cfg); fba=fba_fulfillment_fee(price,profile,cfg); storage=storage_fee(profile,assumptions["storage_months"],cfg)
    if fba["fee_aed"] is None or storage is None: total=None; fee_vat=None
    else:
        amazon_pre_vat=referral["amount_aed"]+fba["fee_aed"]+storage; fee_vat=round(amazon_pre_vat*cfg["conditions"]["fee_vat_rate"],2)
        total=round(amazon_pre_vat+fee_vat+price*assumptions["advertising_rate"]+price*assumptions["returns_rate"]+assumptions["other_operating_reserve_aed"],2)
    max_costs={str(int(m*100)):maximum_landed_cost_v13(price,m,total) for m in (.20,.25,.30)}
    supplier={key:_supplier_target(max_costs[key],assumptions,cfg["conditions"]["customs_duty_rate_general"],cfg["conditions"]["import_vat_rate"]) for key in max_costs}
    fixed=0 if total is None else total-price*(referral["rate"]+assumptions["advertising_rate"]+assumptions["returns_rate"])-referral["amount_aed"]*cfg["conditions"]["fee_vat_rate"]
    variable=referral["rate"]*(1+cfg["conditions"]["fee_vat_rate"])+assumptions["advertising_rate"]+assumptions["returns_rate"]
    break_even_price=None if total is None or variable>=1 else round(fixed/(1-variable),2)
    return {"name":name,"selling_price_aed":round(price,2),"referral_fee_rate":referral["rate"],"referral_fee_minimum_aed":referral["minimum_aed"],"referral_fee_aed":referral["amount_aed"],"fba":fba,"amazon_fee_vat_aed":fee_vat,"amazon_fee_vat_cash_flow_aed":fee_vat,"recoverable_amazon_fee_vat_aed":fee_vat,"storage_fee_estimate_aed":storage,"advertising_reserve_aed":round(price*assumptions["advertising_rate"],2),"returns_refunds_reserve_aed":round(price*assumptions["returns_rate"],2),"inbound_to_amazon_aed":assumptions["inbound_to_amazon_aed"],"inspection_prep_aed":assumptions["inspection_prep_aed"],"other_operating_reserve_aed":assumptions["other_operating_reserve_aed"],"international_freight_aed":assumptions["international_freight_aed"],"local_clearance_delivery_aed":assumptions["local_clearance_delivery_aed"],"factory_cost_aed":None,"customs_duty_aed":None,"import_vat_cash_flow_aed":None,"local_transport_aed":assumptions["local_clearance_delivery_aed"],"landed_cost_aed":None,"total_amazon_operating_cost_before_product_aed":total,"maximum_landed_cost_aed":max_costs,"supplier_targets":supplier,"break_even_landing_cost_aed":None if total is None else round(price-total,2),"break_even_selling_price_before_product_cost_aed":break_even_price,"assumptions":assumptions}


def _economics_score(base: dict[str,Any], conservative: dict[str,Any], confidence: float, actual_landed: float | None=None) -> dict[str,Any]:
    price=base["selling_price_aed"]; max25=base["maximum_landed_cost_aed"]["25"]; conservative25=conservative["maximum_landed_cost_aed"]["25"]
    if max25 is None: return {"raw":None,"components":{},"rule_version":"v1.3"}
    actual_margin=None if actual_landed is None else (price-base["total_amazon_operating_cost_before_product_aed"]-actual_landed)/price
    components={"actual_margin":0 if actual_margin is None else clamp(actual_margin/0.30*100),"landed_cost_headroom":clamp(max25/price*200),"fee_burden":clamp((.50-base["total_amazon_operating_cost_before_product_aed"]/price)/.35*100),"conservative_robustness":clamp((conservative25 or 0)/max25*100),"evidence_confidence":confidence}
    weights={"actual_margin":.30,"landed_cost_headroom":.30,"fee_burden":.20,"conservative_robustness":.15,"evidence_confidence":.05}
    contributions={key:round(components[key]*weights[key],4) for key in weights}; return {"raw":round(sum(contributions.values()),2),"components":components,"weights":weights,"contributions":contributions,"rule_version":"v1.3","actual_margin_unknown_behavior":"ZERO_WITHIN_ECONOMICS_SCORE" if actual_margin is None else "CALCULATED"}


def _sensitivity(price: float, category: str, profile: ProductPhysicalProfile, cfg: dict[str,Any], reference_landed: float | None) -> dict[str,Any]:
    cases=[]
    for label,value in (("PRICE_MINUS_10",price*.9),("PRICE_BASE",price),("PRICE_PLUS_10",price*1.1)):
        scenario=_scenario(value,category,profile,"BASE",cfg); profit=None if reference_landed is None else value-scenario["total_amazon_operating_cost_before_product_aed"]-reference_landed; cases.append({"case":label,"net_margin":None if profit is None else round(profit/value,4)})
    for rate in (.05,.10,.15):
        scenario=_scenario(price,category,profile,"BASE",cfg); delta=price*(rate-cfg["scenario_assumptions"]["BASE"]["advertising_rate"]); profit=None if reference_landed is None else price-scenario["total_amazon_operating_cost_before_product_aed"]-delta-reference_landed; cases.append({"case":f"ADS_{int(rate*100)}", "net_margin":None if profit is None else round(profit/price,4)})
    for rate in (.02,.05,.10):
        scenario=_scenario(price,category,profile,"BASE",cfg); delta=price*(rate-cfg["scenario_assumptions"]["BASE"]["returns_rate"]); profit=None if reference_landed is None else price-scenario["total_amazon_operating_cost_before_product_aed"]-delta-reference_landed; cases.append({"case":f"RETURNS_{int(rate*100)}", "net_margin":None if profit is None else round(profit/price,4)})
    margins=[case["net_margin"] for case in cases if case["net_margin"] is not None]; classification="UNKNOWN" if not margins else "ROBUST" if min(margins)>=.15 else "SENSITIVE" if min(margins)>=.05 else "FRAGILE"
    return {"classification":classification,"cases":cases,"reference_landed_cost_aed":reference_landed}


def calculate_candidate_economics(niche: str, selling_price_aed: float | None, *, actual_landed_cost_aed: float | None=None, physical_profile: ProductPhysicalProfile | None=None, config: dict[str,Any] | None=None) -> dict[str,Any]:
    cfg=config or load_economics_config(); category=map_fee_categories(niche,cfg); profile=physical_profile or PHYSICAL_ESTIMATES.get(niche)
    if selling_price_aed is None: return {"status":"UNKNOWN","confidence":0,"score":{"raw":None},"category":category,"physical_profile":None,"evidence_sources":[cfg["sources"]["pricing"]]}
    if profile is None: return {"status":"INSUFFICIENT","confidence":20,"score":{"raw":None},"category":category,"physical_profile":None,"evidence_sources":[cfg["sources"]["pricing"]]}
    category_scenarios={cat:{name:_scenario(float(selling_price_aed),cat,profile,name,cfg) for name in ("OPTIMISTIC","BASE","CONSERVATIVE")} for cat in category["category_scenarios"]}
    primary=category_scenarios[category["amazon_fee_category"]]; confidence=max(0,min(100,55-(10 if len(category["category_scenarios"])>1 else 0)+(10 if profile.source in {"OBSERVED_ASIN","SERPAPI","SUPPLIER","USER"} else 0)+(20 if actual_landed_cost_aed is not None else 0)))
    score=_economics_score(primary["BASE"],primary["CONSERVATIVE"],confidence,actual_landed_cost_aed); reference=actual_landed_cost_aed if actual_landed_cost_aed is not None else primary["BASE"]["maximum_landed_cost_aed"]["25"]
    return {"status":"SUFFICIENT" if confidence>=75 and score["raw"] is not None else "PARTIAL" if score["raw"] is not None else "INSUFFICIENT","confidence":confidence,"score":score,"category":category,"physical_profile":profile.to_dict(),"scenarios":primary,"category_scenarios":category_scenarios,"sensitivity":_sensitivity(float(selling_price_aed),category["amazon_fee_category"],profile,cfg,reference),"fee_rule_version":cfg["fee_rule_version"],"effective_date":cfg["effective_date"],"retrieved_at":cfg["retrieved_at"],"evidence_sources":list(cfg["sources"].values()),"calculator_workflow":"Manual public/guest or Seller Central workflow: search an existing ASIN, or use Define Product for a hypothetical product; enter accurate dimensions, weight, price, goods cost, and non-Amazon costs. No authenticated automation or invented calculator output was used."}
