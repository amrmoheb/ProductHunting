from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from .models import NicheAnalysis
from .normalization import price_statistics
from .profitability import maximum_landed_cost


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "research"


def _money(value: float | None) -> str:
    return "Unavailable" if value is None else f"AED {value:,.2f}"


def render_report(analyses: list[NicheAnalysis], *, filters: dict[str, Any], sources: list[str], unavailable: list[str], mode: str) -> str:
    now = datetime.now(timezone.utc).isoformat()
    ranked = sorted(analyses, key=lambda a: (a.opportunity_score * a.data_confidence_score / 100, a.opportunity_score), reverse=True)[:10]
    lines = [
        "# AMAZON UAE PRODUCT OPPORTUNITY REPORT", "", f"Research time: {now}",
        "Marketplace: Amazon UAE / Amazon.ae (`A2VIGQ35RCS4UG`), region `eu`, currency AED",
        f"Mode: {mode}", f"Filters used: `{json.dumps(filters, sort_keys=True)}`",
        f"Data sources successfully used: {', '.join(sources) or 'None'}",
        f"Unavailable sources: {', '.join(unavailable) or 'None'}",
        "Confidence notes: Opportunity scores are deterministic. Low-confidence scores are not confident winners; mock observations are demonstrations, not live Amazon facts.", "",
        "## TOP 10 recommendations", "",
    ]
    for rank, item in enumerate(ranked, 1):
        stats = price_statistics(p.price_aed for p in item.products)
        typical = stats["median"]
        ranks = [p.sales_rank for p in item.products if p.sales_rank]
        offers = [p.offer_count for p in item.products if p.offer_count is not None]
        brands = sorted({p.brand for p in item.products if p.brand})
        asin_list = ", ".join(p.asin for p in item.products[:5])
        lines += [
            f"### {rank}. {item.name}", "", f"- Example ASINs: {asin_list or 'Unavailable'}",
            f"- Opportunity Score: **{item.opportunity_score:.1f}/100**; Data Confidence: **{item.data_confidence_score:.1f}/100**",
            f"- Demand Score: {item.demand_score:.1f} ({item.demand_confidence}); Competition attractiveness: {item.competition_score:.1f}; Risk Score: {item.risk_score:.1f}",
            f"- Typical selling price: {_money(typical)}; Estimated Amazon fees: {_money(item.fees_aed)}",
            f"- Maximum landed cost for 20% margin: {_money(maximum_landed_cost(typical or 0, item.fees_aed, .20))}",
            f"- Maximum landed cost for 25% margin: {_money(maximum_landed_cost(typical or 0, item.fees_aed, .25))}",
            f"- Maximum landed cost for 30% margin: {_money(maximum_landed_cost(typical or 0, item.fees_aed, .30))}",
            f"- Observed sales ranks: {', '.join(map(str, ranks)) or 'Unavailable'} (raw ranks; not converted to sales)",
            f"- Approximate offer competition: {round(sum(offers)/len(offers), 1) if offers else 'Unavailable'} offers per sampled ASIN; Major competing brands: {', '.join(brands[:5]) or 'Unavailable'}",
            f"- Why it could work: score reflects demand, competition, economics, price, risk, and differentiation evidence.",
            f"- Why it could fail: {('; '.join(item.risk_reasons)) or 'Missing live validation can materially change the result.'}",
            "- Next validation step: validate supplier quote and product compliance, then refresh UAE pricing, offers, sales ranks, and fee estimates.", "",
        ]
    lines += ["## Comparison table", "", "| Rank | Niche | Opportunity | Confidence | Demand | Competition | Risk | Median price |", "|---:|---|---:|---:|---:|---:|---:|---:|"]
    for rank, item in enumerate(ranked, 1):
        med = price_statistics(p.price_aed for p in item.products)["median"]
        lines.append(f"| {rank} | {item.name} | {item.opportunity_score:.1f} | {item.data_confidence_score:.1f} | {item.demand_score:.1f} | {item.competition_score:.1f} | {item.risk_score:.1f} | {_money(med)} |")
    lines += ["", "## TOP 3 TO INVESTIGATE NOW", ""]
    for item in ranked[:3]:
        lines.append(f"- **{item.name}** — opportunity {item.opportunity_score:.1f}, confidence {item.data_confidence_score:.1f}; prioritize evidence gaps before sourcing.")
    risky = [a for a in analyses if a.risk_score >= 60 or a.opportunity_score < 50]
    lines += ["", "## AVOID / HIGH-RISK OPPORTUNITIES", ""]
    lines += [f"- **{a.name}** — risk {a.risk_score:.1f}: {', '.join(a.risk_reasons) or 'weak evidence/economics'}" for a in risky] or ["- None identified in this candidate set."]
    label = "Live Amazon response values are observed" if mode == "live" else "Fixture values are synthetic mock observations"
    lines += ["", "## Data labeling", "", f"{label} and retain collection timestamps in normalized records/SQLite. Scores and aggregates are calculated. Demand inferred from rank is estimated evidence, never actual sales. Missing fields are unavailable, never invented."]
    return "\n".join(lines) + "\n"


def write_report(content: str, payload: dict[str, Any], slug: str, directory: str | Path = "reports") -> tuple[Path, Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    base = directory / f"{stamp}-{_slug(slug)}"
    markdown, json_path = base.with_suffix(".md"), base.with_suffix(".json")
    markdown.write_text(content, encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return markdown, json_path
