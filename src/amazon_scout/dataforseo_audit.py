from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Any

from .sources.dataforseo import EvidenceEnvironment

POC_KEYWORDS = {
 "long handle baseboard cleaning tool": ["baseboard cleaner tool with handle","baseboard cleaning tool","wall cleaner mop"],
 "wood crochet blocking board": ["wood crochet blocking board","crochet blocking board","granny square blocking board"],
 "washable ceiling fan blade sleeve duster": ["ceiling fan blade duster","ceiling fan cleaner duster","washable fan duster"],
 "adjustable airplane foot hammock": ["airplane foot hammock","airplane footrest","travel foot hammock"],
 "foldable calf slant board": ["calf slant board","slant board for calf stretching","adjustable calf stretcher"],
}

@dataclass(frozen=True)
class AmazonKeywordEvidence:
    keyword: str
    amazon_monthly_search_volume: int | None
    source: str = "dataforseo"
    environment: str = EvidenceEnvironment.PRODUCTION.value
    last_updated: str | None = None
    confidence_status: str = "UNKNOWN"

@dataclass
class AmazonKeywordCluster:
    primary_keyword: str
    related_keywords: list[str]
    keyword_source: str
    keywords: list[AmazonKeywordEvidence] = field(default_factory=list)
    cluster_search_volume_estimate: int | None = None
    cluster_search_volume_status: str = "UNKNOWN_OVERLAP_NOT_DEDUPLICATED"

@dataclass
class DemandAudit:
    old_demand_score: float | None
    old_demand_status: str
    amazon_search_volume_status: str = "UNKNOWN"
    amazon_search_volume_confidence: str = "UNKNOWN"
    primary_keyword_search_volume: int | None = None
    related_keyword_search_volumes: dict[str,int|None] = field(default_factory=dict)
    ranked_keyword_count: int | None = None
    ranked_keyword_volume_summary: dict[str,Any] = field(default_factory=dict)

@dataclass
class CompetitionAudit:
    old_competition_score: float | None
    old_competition_status: str
    keyword_competitor_count: int | None = None
    high_overlap_competitor_count: int | None = None
    median_keyword_overlap: float | None = None
    competitor_visibility_concentration: float | None = None
    organic_competition_strength: float | None = None
    paid_competition_strength: float | None = None

def assert_audit_only(environment: str) -> None:
    if environment == EvidenceEnvironment.SANDBOX_DUMMY.value:
        raise ValueError("SANDBOX_DUMMY evidence is prohibited from scoring and evidence gates")

def select_representative_asins(products: list[dict[str,Any]], limit: int=3) -> list[dict[str,str]]:
    comparable=[p for p in products if p.get("asin") and p.get("commercial_comparability") in {None,"COMPARABLE"} and isinstance(p.get("current_price_aed"), (int,float))]
    if not comparable: return []
    mid=median(float(p["current_price_aed"]) for p in comparable)
    def rank(p):
        rating=p.get("rating"); reviews=p.get("reviews",p.get("review_count")); profile_penalty=int(rating is None)+int(reviews is None)
        profile_penalty += int(isinstance(rating,(int,float)) and (rating >= 4.9 or rating <= 2.5))
        profile_penalty += int(isinstance(reviews,(int,float)) and reviews <= 1)
        return (profile_penalty,abs(float(p["current_price_aed"])-mid),str(p["asin"]))
    return [{"asin":p["asin"],"selection_reason":"Exact/close comparable product nearest the comparable-segment median price, with non-extreme rating/review evidence preferred; deterministic ASIN tie-break."} for p in sorted(comparable,key=rank)[:limit]]

def prepare_poc_mappings(products: list[dict[str,Any]]) -> dict[str,Any]:
    result={}
    for niche,keywords in POC_KEYWORDS.items():
        candidates=[p for p in products if p.get("niche")==niche]
        result[niche]={"keyword_cluster":asdict(AmazonKeywordCluster(keywords[0],keywords[1:],"existing_repository_evidence")),"representative_asins":select_representative_asins(candidates)}
    return result
