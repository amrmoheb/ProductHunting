---
name: amazon-uae-research
description: Research evidence-backed Amazon UAE product opportunities using current live web search and optional structured providers, then ingest and deterministically score them. Use for prompts including find products to sell on Amazon UAE, research Amazon UAE, find product opportunities, analyze an Amazon niche or ASIN, what should I sell, profitability, competition, or a product deep dive. Do not use for non-UAE marketplaces or seller-state mutations.
---

# Amazon UAE research workflow

Work only on Amazon.ae / `A2VIGQ35RCS4UG`, currency AED. Treat Codex as the web-research orchestrator and Python as the validator/scorer. Never call Codex search from Python, scrape Amazon directly, evade controls, or invent missing fields.

1. Understand user filters. Preserve unknown filter inputs as unknown.
2. For broad hunting, generate 30–100 narrow niches before selecting products. Prefer AED 40–200, small/light, simple, non-hazardous, evergreen, lower-compliance opportunities with realistic differentiation. Use English and Arabic terms where useful.
3. Search current sources with live web search. Start with `site:amazon.ae "<niche>"`, Amazon UAE variants, UAE demand/trend searches, and authoritative UAE regulatory sources. Record the exact query. Do not treat snippets as SP-API data.
4. Search official `sell.amazon.ae` pages for current fee/restriction methodology. Never apply a fee percentage without dated evidence; leave FBA fees unknown when dimensions/tier are inadequate.
5. Check configuration through `./scripts/research-doctor`. Never invoke SerpApi unless `RESEARCH_ALLOW_PAID_PROVIDERS=true` and both call/cost limits permit it. DataForSEO and Rainforest remain disabled. Never expose a provider key.
6. Use Codex web research for the 60+ idea universe and lightweight screening. Do not spend SerpApi calls during broad discovery. Reduce to approximately 12–15 promising, compliant, buyer-intent niches first.
7. Use SerpApi as the precision layer: one `engine=amazon`, `amazon_domain=amazon.ae`, `k=<buyer-intent keyword>` search per screened niche. Reject non-`amazon.ae` responses, deduplicate requests, and reuse only cache entries within the configured TTL.
8. Preserve the local 40-call ceiling and five-call reserve. Aim for no more than 15 initial searches, about 10 gap-directed variants, and selective `engine=amazon_product` deep dives. Do not consume reserve unless a call could change a gate or ranking. Forty is a ceiling, not a target.
9. Collect atomic evidence. Search position is not BSR, reviews are not sales, sponsored density is competition rather than demand, and `bought_last_month` is a non-exact lower-bound signal. Missing evidence is UNKNOWN, never neutral or positive.
10. Generate structured bundles with `./scripts/serpapi-validate --candidate 'niche=keyword' ... --output <bundle>`, then run `./scripts/ingest-research <bundle>`. Fix validation errors rather than weakening validation.
11. A finalist still needs current Amazon UAE price plus meaningful competition, demand, and risk evidence. Top-three sourcing requires confidence >= 60; do not loosen this gate or fill a Top 10.
12. Perform gap-directed follow-up. Use product API deep dives only for representative ASINs when details can close an important gap.
13. Before presenting a final report, inspect `risk_gap_research_plan`. If price, demand, and competition pass while risk is unknown, automatically use zero-paid Codex live web research—never SerpApi—to check MoIAT, Dubai Municipality, UAE government, and Amazon UAE official guidance. Ingest explicit `regulatory_risk` or `risk_score` evidence with reasons and URLs, then re-run ingestion. If authoritative evidence is insufficient, keep risk UNKNOWN; absence of a located restriction is not LOW risk.

SerpApi relevance is deterministic. Persist each result as `EXACT_TARGET`, `CLOSE_VARIANT`, `ACCESSORY`, `WRONG_PRODUCT`, or `AMBIGUOUS` using normalized title, requested tokens, product anchors, material/size/use-case modifiers, and exclusion terms. Only exact targets and close variants may feed numeric aggregates. Do not manually promote ambiguous results without explicit validation.

Semantic relevance is not commercial comparability. After relevance filtering, derive and persist pack count, size/dimensions, positioning, material/features, subtype, brand tier, and bundle configuration. Classify each relevant result as `COMPARABLE`, `ADJACENT`, `NON_COMPARABLE`, or `UNKNOWN` against the candidate's explicit target commercial profile. Price gates and primary competition statistics use only current comparable Amazon.ae products. A cheap exact target stays relevant but cannot distort a large/premium segment when its size or configuration is not comparable. Require the configured comparable sample and in-band distribution; one premium outlier never passes the gate. Report a distinct `PREMIUM_POSITIONING_HYPOTHESIS` when appropriate.

Always use the canonical price-gate function, including for broad/generic target profiles: require the configured comparable sample, then pass only when the comparable median is in range or the configured in-band ratio is met. Keep the canonical tier consistent across every report section. Distinguish technical validation (all five evidence/confidence gates pass) from a strong opportunity (technical validation plus score at least 65). Use the accumulated complete-run SerpApi usage in the primary report header, never a phase subtotal.

Keep price semantics separate. An observed Amazon UAE price, a proposed selling price, a bundle hypothesis price, and the fee-calculation price are different fields. Never overwrite one with another. External retailer prices cannot satisfy the Amazon price gate. A proposed bundle is a hypothesis, not observed willingness-to-pay, and must not enter sourcing recommendations until validated by market evidence.

Never invent bundle demand. Never convert absent demand or competition evidence into an average score. Explain every failed gate plainly. Prefer fewer qualified finalists to a padded list, and conduct more focused research where a promising candidate has a resolvable evidence gap.

For deep dives, collect 10–30 competitors where practical: prices, ratings, review counts, brands, positions, sponsored density, features, permitted negative-review themes, keywords, UAE demand, regulation, and supplier terms. Never equate reviews/rank with sales.

For finalists include English and useful Chinese supplier terms, target factory price, maximum landed cost, MOQ target, important specifications, and a quality checklist. Do not contact or buy from suppliers.
