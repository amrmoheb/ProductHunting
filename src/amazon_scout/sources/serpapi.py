from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable

from ..commercial_segments import classify_commercial_segment, target_commercial_profile
from .base import PaidProviderBudget, ResearchSource

AMAZON_DOMAIN = "amazon.ae"
MARKETPLACE_ID = "A2VIGQ35RCS4UG"
ENDPOINT = "https://serpapi.com/search.json"
RELEVANCE_STATUSES = {"TARGET_PRODUCT", "TARGET_IS_ACCESSORY", "ACCESSORY_TO_TARGET", "WRONG_PRODUCT", "AMBIGUOUS"}
TOKEN_ALIASES = {"mats":"mat","cubes":"cube","organizers":"organizer","organisers":"organizer","desks":"desk","feeding":"feed","packing":"pack","clips":"clip","straps":"strap","racks":"rack","holders":"holder","stands":"stand","risers":"riser","hooks":"hook"}
GENERIC_TOKENS = {"premium","large","small","xl","xxl","set","sets","for","and","with","the","of","in","non","slip","waterproof"}
ACCESSORY_CONCEPTS = {"holder", "strap", "clip", "stand", "riser", "rack", "mount", "sling", "hook", "hammock"}
ACCESSORY_TO_TARGET_TERMS = {"replacement", "refill", "spare part", "replacement part", "cover only", "case only", "rubber feet", "rubber foot", "carabiner only", "screw only", "clamp only", "pad only"}
PRODUCT_ANCHORS = (({"mat","pad"},{"mat","pad"}),({"cube","organizer"},{"cube","organizer"}),({"tray"},{"tray"}),({"bottle"},{"bottle"}),({"brush"},{"brush"}))
TARGET_ANCHOR_GROUPS = (
    ({"laptop", "riser"}, {"riser", "stand"}),
    ({"ankle", "strap"}, {"ankle", "strap"}),
    ({"luggage", "cup"}, {"holder", "sling"}),
    ({"towel", "clip"}, {"clip"}),
    ({"drying", "rack"}, {"rack"}),
)


def _tokens(value: str) -> set[str]:
    return {TOKEN_ALIASES.get(token,token) for token in re.findall(r"[a-z0-9]+",value.lower()) if len(token)>1}


def classify_relevance(result: dict[str, Any], niche: str, keyword: str) -> dict[str, Any]:
    title=str(result.get("title") or ""); title_tokens=_tokens(title); requested=_tokens(f"{niche} {keyword}")-GENERIC_TOKENS
    target_accessory_concepts=sorted(requested & ACCESSORY_CONCEPTS)
    anchors=set(); quality=None
    for triggers,values in TARGET_ANCHOR_GROUPS:
        if triggers <= requested: anchors |= values
    for triggers,values in PRODUCT_ANCHORS:
        if not anchors and requested & triggers: anchors |= values
    if not anchors and requested: anchors={max(requested,key=len)}
    matched=sorted(requested & title_tokens); missing=sorted(requested-title_tokens); anchor_match=bool(anchors & title_tokens)
    accessory_hits=sorted(term for term in ACCESSORY_TO_TARGET_TERMS if term in title.lower())
    if not title or not result.get("asin"): status="AMBIGUOUS"; quality=None; reason="missing title or ASIN"
    elif accessory_hits: status="ACCESSORY_TO_TARGET"; quality=None; reason=f"explicit replacement/subcomponent sold for the target: {', '.join(accessory_hits)}"
    elif not anchor_match: status="WRONG_PRODUCT"; reason=f"missing product-type anchor: {', '.join(sorted(anchors)) or 'unknown'}"
    else:
        coverage=len(matched)/max(1,len(requested)); modifiers=requested-anchors; modifier_coverage=len(modifiers & title_tokens)/max(1,len(modifiers))
        quality="EXACT_TARGET" if coverage >= .75 or modifier_coverage >= .75 else "CLOSE_VARIANT" if coverage >= .4 or modifier_coverage >= .4 else None
        if quality is None: status="AMBIGUOUS"; reason="product anchor matched but niche modifier coverage was insufficient"
        elif target_accessory_concepts: status="TARGET_IS_ACCESSORY"; reason=f"target product anchors matched; accessory concept is part of target definition: {', '.join(target_accessory_concepts)}"
        else: status="TARGET_PRODUCT"; reason="target product anchor and sufficient niche modifiers matched"
    if status in {"WRONG_PRODUCT", "ACCESSORY_TO_TARGET", "AMBIGUOUS"}: quality=None
    legacy_status = quality if status in {"TARGET_PRODUCT", "TARGET_IS_ACCESSORY"} else "ACCESSORY" if status == "ACCESSORY_TO_TARGET" else status
    return {"relevance_status":legacy_status,"target_relationship":status,"target_match_quality":quality,"relevance_reason":reason,"requested_tokens":sorted(requested),"matched_tokens":matched,"missing_tokens":missing,"product_anchor_tokens":sorted(anchors),"target_accessory_concepts":target_accessory_concepts,"accessory_to_target_terms":accessory_hits,"rule_version":"v1.2.4"}


def request_fingerprint(params: dict[str, Any]) -> str:
    safe = {str(k): v for k, v in params.items() if k != "api_key" and v is not None}
    canonical = json.dumps(safe, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class SerpApiBudget(PaidProviderBudget):
    reserve_calls: int = 5
    keywords_queried: list[str] = field(default_factory=list)
    asins_queried: list[str] = field(default_factory=list)
    purposes: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_environment(cls) -> "SerpApiBudget":
        base = PaidProviderBudget.from_environment()
        return cls(base.allow, base.max_calls, base.max_cost_usd)

    def authorize_request(self, params: dict[str, Any], purpose: str, *, use_reserve: bool = False, estimated_cost_usd: float = 0) -> None:
        if self.calls_remaining <= 0:
            raise PermissionError("SerpApi local run call budget exhausted")
        if not use_reserve and self.calls_remaining <= self.reserve_calls:
            raise PermissionError("SerpApi reserve protected; this call is not marked high-value gap-directed validation")
        self.authorize(estimated_cost_usd)
        keyword = str(params.get("k") or "")
        asin = str(params.get("asin") or "")
        if keyword and keyword not in self.keywords_queried: self.keywords_queried.append(keyword)
        if asin and asin not in self.asins_queried: self.asins_queried.append(asin)
        self.purposes.append({"fingerprint": request_fingerprint(params), "purpose": purpose, "engine": str(params.get("engine"))})

    def usage(self, *, configured: bool) -> dict[str, Any]:
        return {
            "configured": configured, "enabled": self.allow and self.max_calls > 0 and self.max_cost_usd > 0,
            "configured_max_calls": self.max_calls, "calls_attempted": self.calls_attempted,
            "calls_succeeded": self.calls_succeeded, "calls_failed": self.calls_failed,
            "calls_saved_by_cache": self.calls_saved_by_cache, "calls_remaining": self.calls_remaining,
            "estimated_cost_usd": self.cost_used_usd, "keywords_queried": list(self.keywords_queried),
            "asins_queried": list(self.asins_queried), "product_detail_calls": sum(p["engine"] == "amazon_product" for p in self.purposes),
            "purpose_for_each_call": list(self.purposes), "local_budget_note": "Local run budget; not SerpApi account quota."
        }


class SerpApiCache:
    def __init__(self, root: str | Path = "research/cache/serpapi", ttl_hours: float | None = None) -> None:
        self.root = Path(root)
        self.ttl = timedelta(hours=ttl_hours if ttl_hours is not None else float(os.getenv("SERPAPI_CACHE_TTL_HOURS", "8")))

    def get(self, params: dict[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
        path = self.root / f"{request_fingerprint(params)}.json"
        if not path.exists(): return None
        try: payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return None
        retrieved = datetime.fromisoformat(payload["retrieved_at"].replace("Z", "+00:00"))
        if (now or datetime.now(timezone.utc)) - retrieved > self.ttl: return None
        return payload["response"]

    def put(self, params: dict[str, Any], response: dict[str, Any], now: datetime | None = None) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"request_fingerprint": request_fingerprint(params), "request_parameters": {k:v for k,v in params.items() if k != "api_key"}, "retrieved_at": (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z"), "response": response, "normalized_evidence_ids": []}
        (self.root / f"{request_fingerprint(params)}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


class SerpApiSource(ResearchSource):
    name = "SerpApi"
    paid = True
    required_env = ("SERPAPI_API_KEY",)

    @staticmethod
    def search_params(keyword: str, *, page: int = 1) -> dict[str, Any]:
        if not keyword.strip(): raise ValueError("SerpApi Amazon keyword must not be empty")
        return {"engine": "amazon", "amazon_domain": AMAZON_DOMAIN, "k": keyword.strip(), "page": page}

    @staticmethod
    def product_params(asin: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Z0-9]{10}", asin.strip().upper()): raise ValueError("Invalid ASIN")
        return {"engine": "amazon_product", "amazon_domain": AMAZON_DOMAIN, "asin": asin.strip().upper()}

    def build_search_request(self, keyword: str, budget: PaidProviderBudget) -> tuple[str, dict[str, str]]:
        budget.authorize()
        return ENDPOINT, {**self.search_params(keyword), "api_key": os.environ["SERPAPI_API_KEY"]}

    def execute(self, params: dict[str, Any], budget: SerpApiBudget, cache: SerpApiCache, purpose: str, *, use_reserve: bool = False, transport: Callable[[str], dict[str, Any]] | None = None) -> tuple[dict[str, Any] | None, str]:
        self._validate_params(params)
        cached = cache.get(params)
        if cached is not None:
            self._validate_response(cached, params["engine"])
            budget.calls_saved_by_cache += 1
            keyword=str(params.get("k") or ""); asin=str(params.get("asin") or "")
            if keyword and keyword not in budget.keywords_queried: budget.keywords_queried.append(keyword)
            if asin and asin not in budget.asins_queried: budget.asins_queried.append(asin)
            return cached, "CACHE"
        key = os.getenv("SERPAPI_API_KEY")
        if not key: raise PermissionError("SerpApi is not configured")
        budget.authorize_request(params, purpose, use_reserve=use_reserve)
        try:
            if transport:
                payload = transport(ENDPOINT + "?" + urllib.parse.urlencode({**params, "api_key": key}))
            else:
                request = urllib.request.Request(ENDPOINT + "?" + urllib.parse.urlencode({**params, "api_key": key}), headers={"Accept":"application/json","User-Agent":"amazon-uae-product-scout/1.2"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            self._validate_response(payload, params["engine"])
            cache.put(params, payload); budget.succeeded()
            return payload, "LIVE"
        except Exception as exc:
            budget.failed()
            # Never include transport URLs/query strings because they contain the API key.
            return None, f"{type(exc).__name__}: SerpApi request failed or returned invalid UAE data"

    @staticmethod
    def _validate_params(params: dict[str, Any]) -> None:
        if params.get("amazon_domain") != AMAZON_DOMAIN: raise ValueError("SerpApi request rejected: amazon_domain must be amazon.ae")
        if params.get("engine") not in {"amazon", "amazon_product"}: raise ValueError("Unsupported SerpApi engine")

    @staticmethod
    def _validate_response(payload: dict[str, Any], engine: str) -> None:
        if not isinstance(payload, dict): raise ValueError("Malformed SerpApi response")
        if payload.get("error"): raise ValueError("SerpApi provider returned an error")
        params = payload.get("search_parameters") or {}
        if params.get("amazon_domain") != AMAZON_DOMAIN: raise ValueError("Non-UAE SerpApi response rejected")
        if params.get("engine") != engine: raise ValueError("SerpApi response engine mismatch")
        status = (payload.get("search_metadata") or {}).get("status")
        if status and status != "Success": raise ValueError("SerpApi search did not succeed")


def parse_bought_last_month(value: Any) -> tuple[str | None, int | None, bool]:
    if not isinstance(value, str) or not value.strip(): return None, None, False
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([KkMm]?)\s*\+?", value)
    if not match: return value, None, False
    multiplier = {"":1,"k":1000,"m":1_000_000}[match.group(2).lower()]
    return value, int(float(match.group(1)) * multiplier), False


def _percentile(values: list[float], q: float) -> float | None:
    if not values: return None
    ordered=sorted(values); index=(len(ordered)-1)*q; low=math.floor(index); high=math.ceil(index)
    return round(ordered[low] if low==high else ordered[low]*(high-index)+ordered[high]*(index-low),2)


def _aed_price(result: dict[str, Any]) -> float | None:
    raw=str(result.get("price") or "").upper()
    value=result.get("extracted_price")
    return float(value) if isinstance(value,(int,float)) and ("AED" in raw or "د.إ" in raw) else None


def normalize_search_response(payload: dict[str, Any], *, niche: str, keyword: str, run_id: str, retrieved_at: str, relevant: Callable[[dict[str, Any]], tuple[bool,str | None]] | None = None, price_min_aed: float = 50, price_max_aed: float = 150) -> dict[str, Any]:
    SerpApiSource._validate_response(payload, "amazon")
    target_profile=target_commercial_profile(niche,keyword)
    considered=[]; excluded=[]; classified=[]
    for result in payload.get("organic_results") or []:
        classification=classify_relevance(result,niche,keyword)
        if relevant:
            ok,reason=relevant(result)
            if not ok and classification["target_relationship"] in {"TARGET_PRODUCT","TARGET_IS_ACCESSORY"}:
                classification.update({"relevance_status":"WRONG_PRODUCT","target_relationship":"WRONG_PRODUCT","target_match_quality":None,"relevance_reason":reason or "caller deterministic exclusion"})
        segment=classify_commercial_segment(result,target_profile) if classification["target_relationship"] in {"TARGET_PRODUCT","TARGET_IS_ACCESSORY"} else {}
        enriched={**result,**classification,**segment}; classified.append(enriched)
        if classification["target_relationship"] in {"TARGET_PRODUCT","TARGET_IS_ACCESSORY"}: considered.append(enriched)
        else: excluded.append({"asin":result.get("asin"),"title":result.get("title"),"relevance_status":classification["relevance_status"],"reason":classification["relevance_reason"],"normalized_fields":classification})
    products=[]; evidence=[]
    for index,result in enumerate(considered):
        asin=result.get("asin"); prefix=f"serpapi-{request_fingerprint({'run':run_id,'keyword':keyword,'asin':asin,'index':index})[:20]}"
        product={key:result.get(key) for key in ("asin","title","brand","rating","reviews","sponsored","position","prime","stock","badges","options","variants","bought_last_month","link_clean","relevance_status","target_relationship","target_match_quality","relevance_reason","requested_tokens","matched_tokens","missing_tokens","product_anchor_tokens","target_accessory_concepts","accessory_to_target_terms","rule_version","pack_count","size_class","dimensions","positioning","material","major_feature_set","product_subtype","brand_tier","bundle_configuration","desk_sized","commercial_segment_status","commercial_segment_reasons","commercial_segment_rule_version")}
        current_price=_aed_price(result)
        product.update({"niche":niche,"marketplace":"amazon.ae","current_price_aed":current_price,"original_price_aed":result.get("extracted_old_price") if current_price is not None else None,"target_commercial_profile":target_profile.to_dict(),"observed_at":retrieved_at,"retrieved_at":retrieved_at})
        products.append(product)
        metrics=(("current_price_aed",current_price,"AED"),("rating",result.get("rating"),"stars"),("review_count",result.get("reviews"),"reviews"),("sponsored_status",result.get("sponsored"),None),("search_position",result.get("position"),"position"),("brand",result.get("brand"),None),("asin",asin,None),("amazon_visibility",1,"visible_result"))
        raw_bought,lower,is_exact=parse_bought_last_month(result.get("bought_last_month"))
        for metric,value,unit in metrics:
            if value is not None: evidence.append(_evidence(f"{prefix}-{metric}",metric,value,unit,asin,keyword,niche,retrieved_at,False, f"SerpApi Amazon.ae organic result; query={keyword}"))
        if raw_bought is not None:
            evidence.append(_evidence(f"{prefix}-bought-raw","bought_last_month_raw",raw_bought,None,asin,keyword,niche,retrieved_at,False,"Amazon-displayed purchase signal; not exact monthly sales."))
        if lower is not None:
            evidence.append(_evidence(f"{prefix}-bought-lower","monthly_purchase_signal_lower_bound",lower,"units_lower_bound",asin,keyword,niche,retrieved_at,True,f"Conservative parse of '{raw_bought}'; is_exact={str(is_exact).lower()}"))
    prices=[float(p["current_price_aed"]) for p in products if isinstance(p.get("current_price_aed"),(int,float))]
    comparable=[p for p in products if p.get("commercial_segment_status")=="COMPARABLE"]
    adjacent=[p for p in products if p.get("commercial_segment_status")=="ADJACENT"]
    non_comparable=[p for p in products if p.get("commercial_segment_status")=="NON_COMPARABLE"]
    unknown_segment=[p for p in products if p.get("commercial_segment_status")=="UNKNOWN"]
    comparable_prices=[float(p["current_price_aed"]) for p in comparable if isinstance(p.get("current_price_aed"),(int,float))]
    exact_prices=[float(p["current_price_aed"]) for p in products if p.get("target_match_quality")=="EXACT_TARGET" and isinstance(p.get("current_price_aed"),(int,float))]
    close_prices=[float(p["current_price_aed"]) for p in products if p.get("target_match_quality")=="CLOSE_VARIANT" and isinstance(p.get("current_price_aed"),(int,float))]
    reviews=[float(p["reviews"]) for p in products if isinstance(p.get("reviews"),(int,float))]
    ratings=[float(p["rating"]) for p in products if isinstance(p.get("rating"),(int,float))]
    brands=[str(p["brand"]).strip() for p in products if p.get("brand")]; sponsored=[bool(p["sponsored"]) for p in products if p.get("sponsored") is not None]
    in_band=sum(price_min_aed <= price <= price_max_aed for price in prices)
    sponsored_complete=bool(products) and len(sponsored)==len(products)
    counts=Counter(x["target_relationship"] for x in classified)
    comparable_in_band=sum(price_min_aed <= price <= price_max_aed for price in comparable_prices)
    quality_counts=Counter(x.get("target_match_quality") for x in classified)
    aggregates={"total_results_received":len(classified),"total_serpapi_results":len(classified),"target_product_results":counts["TARGET_PRODUCT"],"target_is_accessory_results":counts["TARGET_IS_ACCESSORY"],"exact_results":quality_counts["EXACT_TARGET"],"close_variants":quality_counts["CLOSE_VARIANT"],"accessory_to_target_exclusions":counts["ACCESSORY_TO_TARGET"],"excluded_accessories":counts["ACCESSORY_TO_TARGET"],"excluded_wrong_products":counts["WRONG_PRODUCT"],"ambiguous_results":counts["AMBIGUOUS"],"results_considered_relevant":len(products),"results_excluded":len(excluded),"exclusion_reasons":dict(Counter(x["reason"] for x in excluded)),"exact_target_price_sample":exact_prices,"close_variant_price_sample":close_prices,"combined_validated_price_sample":prices,"amazon_uae_price_sample_size":len(prices),"price_min_aed":min(prices) if prices else None,"price_p25_aed":_percentile(prices,.25),"price_median_aed":median(prices) if prices else None,"price_mean_aed":round(sum(prices)/len(prices),2) if prices else None,"price_p75_aed":_percentile(prices,.75),"price_max_aed":max(prices) if prices else None,"price_dispersion":round((max(prices)-min(prices))/median(prices),3) if prices and median(prices) else None,"in_target_price_band_count":in_band,"in_target_price_band_ratio":in_band/len(prices) if prices else None,"relevant_result_count":len(products),"unique_asin_count":len({p['asin'] for p in products if p.get('asin')}),"unique_brand_count":len(set(brands)),"top_brand_share":max(Counter(brands).values())/len(brands) if brands else None,"brand_concentration":sum((c/len(brands))**2 for c in Counter(brands).values()) if brands else None,"sponsored_sample_size":len(sponsored),"sponsored_count":sum(sponsored) if sponsored else None,"sponsored_density":sum(sponsored)/len(sponsored) if sponsored_complete else None,"rating_sample_size":len(ratings),"median_rating":median(ratings) if ratings else None,"review_sample_size":len(reviews),"median_reviews":median(reviews) if reviews else None,"p75_reviews":_percentile(reviews,.75),"p90_reviews":_percentile(reviews,.90),"target_commercial_profile":target_profile.to_dict(),"comparable_results":len(comparable),"adjacent_results":len(adjacent),"non_comparable_results":len(non_comparable),"unknown_segment_results":len(unknown_segment),"comparable_sample_size":len(comparable_prices),"comparable_price_min_aed":min(comparable_prices) if comparable_prices else None,"comparable_price_p25_aed":_percentile(comparable_prices,.25),"comparable_price_median_aed":median(comparable_prices) if comparable_prices else None,"comparable_price_mean_aed":round(sum(comparable_prices)/len(comparable_prices),2) if comparable_prices else None,"comparable_price_p75_aed":_percentile(comparable_prices,.75),"comparable_price_max_aed":max(comparable_prices) if comparable_prices else None,"comparable_in_target_band_count":comparable_in_band,"comparable_in_target_band_ratio":comparable_in_band/len(comparable_prices) if comparable_prices else None}
    for metric in ("relevant_result_count","brand_concentration","top_brand_share","sponsored_density","median_rating","median_reviews","p75_reviews"):
        if aggregates.get(metric) is not None: evidence.append(_evidence(f"serpapi-{request_fingerprint({'run':run_id,'keyword':keyword,'metric':metric})[:20]}",metric,aggregates[metric],None,None,keyword,niche,retrieved_at,True,"Derived from the current relevant SerpApi Amazon.ae result sample."))
    for metric in ("total_serpapi_results","target_product_results","target_is_accessory_results","exact_results","close_variants","accessory_to_target_exclusions","excluded_accessories","excluded_wrong_products","ambiguous_results"):
        evidence.append(_evidence(f"serpapi-{request_fingerprint({'run':run_id,'keyword':keyword,'metric':metric})[:20]}",metric,aggregates[metric],"results",None,keyword,niche,retrieved_at,True,"Deterministic V1.2.1 relevance classification aggregate."))
    return {"products":products,"all_classified_results":classified,"evidence":evidence,"aggregates":aggregates,"excluded_results":excluded,"serpapi_keyword":keyword,"target_commercial_profile":target_profile.to_dict()}


def normalize_product_response(payload: dict[str, Any], *, niche: str, keyword: str, run_id: str, retrieved_at: str) -> dict[str, Any]:
    SerpApiSource._validate_response(payload, "amazon_product")
    result=payload.get("product_results") or {}
    asin=result.get("asin") or (payload.get("search_parameters") or {}).get("asin")
    current_price=_aed_price(result)
    product={"niche":niche,"marketplace":"amazon.ae","asin":asin,"title":result.get("title"),"brand":result.get("brand"),"current_price_aed":current_price,"rating":result.get("rating"),"review_count":result.get("reviews"),"availability":result.get("availability"),"variants":result.get("variants"),"product_details":result.get("product_details"),"dimensions":result.get("dimensions")}
    evidence=[]; prefix=f"serpapi-product-{request_fingerprint({'run':run_id,'asin':asin})[:20]}"
    for metric,value,unit in (("current_price_aed",current_price,"AED"),("rating",result.get("rating"),"stars"),("review_count",result.get("reviews"),"reviews"),("brand",result.get("brand"),None),("availability",result.get("availability"),None)):
        if value is not None: evidence.append(_evidence(f"{prefix}-{metric}",metric,value,unit,asin,keyword,niche,retrieved_at,False,"SerpApi Amazon Product API observation for amazon.ae."))
    return {"products":[product],"evidence":evidence,"serpapi_keyword":keyword}


def _evidence(identifier: str, metric: str, value: Any, unit: str | None, asin: str | None, keyword: str, niche: str, timestamp: str, estimate: bool, notes: str) -> dict[str, Any]:
    return {"id":identifier,"metric_name":metric,"metric_value":value,"metric_unit":unit,"asin":asin,"keyword":keyword,"niche":niche,"marketplace":"amazon.ae","marketplace_id":MARKETPLACE_ID,"market_relevance":"AMAZON_UAE","source_timezone":"UTC","source_provider":"serpapi","source_type":"derived_metric" if estimate and metric in {"relevant_result_count","brand_concentration","top_brand_share","sponsored_density","median_rating","median_reviews","p75_reviews"} else "amazon_search","source_url":f"https://www.amazon.ae/dp/{asin}" if asin else None,"source_title":"SerpApi Amazon Search API — amazon.ae","observed_at":timestamp,"retrieved_at":timestamp,"confidence":"HIGH" if metric in {"current_price_aed","rating","review_count","sponsored_status","search_position","monthly_purchase_signal_lower_bound"} else "MEDIUM","is_estimate":estimate,"notes":notes}
