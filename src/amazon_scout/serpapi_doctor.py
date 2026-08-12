from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .sources.serpapi import SerpApiBudget, SerpApiCache, SerpApiSource


def main() -> int:
    budget=SerpApiBudget(True,1,max(0.000001,float(os.getenv("RESEARCH_MAX_COST_USD","0"))),reserve_calls=0)
    source=SerpApiSource()
    with tempfile.TemporaryDirectory(prefix="scout-serpapi-doctor-") as directory:
        response,state=source.execute(source.search_params("drawer organizer"),budget,SerpApiCache(Path(directory),ttl_hours=0),"explicit doctor amazon.ae health test",use_reserve=True)
    if response is None:
        print("SerpApi amazon.ae test         FAIL")
        print("One SerpApi search was attempted and consumed from the provider account; response was not usable.")
        return 1
    organic=response.get("organic_results") or []
    asins=sum(bool(item.get("asin")) for item in organic)
    aed=sum("AED" in str(item.get("price") or "").upper() or "د.إ" in str(item.get("price") or "") for item in organic)
    if not organic or not asins:
        print("SerpApi amazon.ae test         FAIL")
        print("One SerpApi search was consumed; no parseable organic results/ASINs were returned.")
        return 1
    print("SerpApi amazon.ae test         PASS")
    print(f"Organic results parsed         {len(organic)}")
    print(f"ASINs parsed                   {asins}")
    print(f"AED-labelled prices parsed     {aed}")
    print("One SerpApi Amazon search was consumed for this explicit doctor test.")
    return 0


if __name__=="__main__": raise SystemExit(main())
