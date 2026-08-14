# Current Task

Task ID: BH-001
Status: READY
Owner: Codex execution / ChatGPT review

## Objective

Run the **first real V1.4D production Big Hunt** for Amazon UAE and return a small set of genuinely sourceable product opportunities with evidence, economics, and `MAX LANDED COST @25%`.

This is a research run, not a scoring-calibration task. Do not tune or modify V1.4D/V1.3 formulas during the hunt.

## Marketplace and business constraints

- Marketplace: Amazon UAE / `amazon.ae` only (`A2VIGQ35RCS4UG`).
- Target current Amazon UAE selling-price band: **AED 50–150**.
- Target net margin: **25%**.
- Prefer packaged weight below **1.5 kg**.
- Prefer evergreen, simple, compact, low-breakage, low-compliance products.
- Exclude or heavily reject: electronics, batteries, cosmetics, supplements, food, medicines/medical claims, hazardous goods, fragile/oversized items, obvious IP/counterfeit risk, and high-regulation products.
- Do not force a Top 10. Fewer strong/validated finalists are better than padded results.

## Production model

Use canonical **V1.4D** only:

- Demand 30%
- Competition attractiveness 25%
- unchanged V1.3 economics 35%
- Risk attractiveness 10%

Confidence/tier rules remain unchanged:

- `<55` => `PRELIMINARY_NEEDS_EVIDENCE`
- `55–69` => maximum `VALIDATED`
- `>=70` => potentially strong only if score, known risk, economics, and all required gates support it
- UNKNOWN/missing evidence never improves score
- score and confidence remain separate

## Funnel target

Use the existing production discovery/collector pipeline and current V1.4D scorer. Do not create a parallel scoring implementation.

Target funnel:

1. Generate **300–500 distinct niche/product concepts** using Codex web research and repository rules.
2. Semantic/risk/constraint deduplicate and cheap-screen to roughly **60–100**.
3. Select the best **20–25** for current Amazon.ae validation.
4. Deep-evaluate roughly **8–12** where evidence supports it.
5. Produce **up to 5–10 finalists**, but only when supported. Zero STRONG candidates is acceptable.

Avoid semantic duplicates, trivial color/size variants, and the five V1.4C calibration candidates as seeded winners. Historical candidates may appear only if independently rediscovered and current evidence truly supports them; do not bias toward them.

## Provider policy and hard spend cap

### SerpApi

SerpApi Amazon.ae is the primary structured public marketplace validation source.

For this task, SerpApi is authorized with these **hard maximums**:

- maximum paid/provider calls: **25**
- maximum provider cost budget: **USD 0.50**
- every Amazon request must explicitly target `amazon_domain=amazon.ae`
- reuse fresh local cache/fingerprints first
- stop before exceeding either cap

If local configuration cannot safely enforce these caps, do not make paid calls; report the blocker instead.

### DataForSEO

**Forbidden for BH-001: 0 calls, USD 0.00.**

Do not use Bulk Search Volume, Product Competitors, Ranked Keywords, or Merchant endpoints in this run. Existing cached evidence may be used only if already attached to a current candidate and can be read offline without network, but absence must remain absence.

### SP-API

0 calls unless valid seller credentials are already configured and the existing safe read-only production route explicitly supports the requested evidence. Do not require SP-API for success and do not attempt onboarding/auth setup.

## Demand / competition evidence

Use current Amazon.ae structured/public evidence under existing V1.2.4/V1.4D correctness rules:

- EXACT_TARGET / CLOSE_VARIANT only for numeric market aggregates
- unique-ASIN deduplication
- current Amazon UAE price gate
- review depth/distribution
- bought-last-month only as a lower-bound/non-exact signal
- sponsored density when observable
- brand concentration
- comparable density
- relevance/breadth/freshness

Never interpret reviews as units sold and never invent exact monthly sales.

## Risk evidence

For finalists/deep candidates, resolve material UAE regulatory/safety risk using authoritative UAE/primary sources when needed. UNKNOWN risk blocks STRONG.

Do not spend SerpApi calls solely on regulatory lookup; use Codex web research/authoritative sources.

## Economics

For every deep finalist with a valid current price basis, run unchanged **V1.3 economics**.

Report at minimum:

- current/fee-calculation selling-price basis
- referral fee estimate
- FBA/fulfilment estimate
- storage
- VAT treatment
- advertising/returns reserves
- inbound/prep/freight/customs assumptions
- economics raw score
- economics confidence/status
- **MAX LANDED COST @25%**
- **supplier product cost target @25%**

Physical profiles may be estimated only under the existing V1.3 policy and must remain explicitly `ESTIMATED`/`PARTIAL`. Never present estimated dimensions/weight, freight, or factory cost as observed.

Do not claim actual profit when supplier/factory landed cost is unknown. The user will compare sourcing quotes against the maximum landed-cost threshold manually.

## Final report

Write timestamped Markdown + JSON outputs under the existing report paths.

The final Markdown must be decision-oriented and concise. For each finalist show:

- rank
- niche/product concept
- representative ASIN(s)
- current Amazon UAE comparable price / price band
- V1.4D opportunity score
- confidence
- recommendation tier
- demand score
- competition attractiveness score
- risk score/status
- economics score/status/confidence
- **MAX LANDED COST @25%**
- supplier product cost target @25%
- why it is attractive
- main reason not to source / remaining unknown
- next manual validation step

Also include:

- full funnel counts
- SerpApi call count and cost
- DataForSEO calls = 0
- source/evidence freshness notes
- rejected/high-risk examples only when useful
- explicit statement if no candidate qualifies as STRONG

Sort final recommendations using canonical V1.4D opportunity/tier logic, not score × confidence.

## Safety / integrity

- No scraping private Seller Central.
- No CAPTCHA/proxy evasion.
- No fake SP-API or Brand Analytics claims.
- No hidden marketplace substitution.
- No fabricated product metrics.
- No model-weight changes during this task.
- Do not modify production code just to improve hunt results.

If a genuine code defect blocks the run, stop and report it separately instead of silently changing scoring logic during BH-001.

## Tests

Before the paid validation stage, run targeted smoke tests for the production collector/scorer/report path. After the run, run relevant non-network tests. Do not run tests that trigger provider calls.

## Git behavior

Research outputs may remain local/gitignored. **No code commit is required** when the hunt completes without code changes.

Do not create a pointless commit for generated reports.

## Handoff response

Return a concise summary only:

- Task ID
- generated / cheap-screened / Amazon-validated / deep / finalist funnel counts
- number of STRONG / VALIDATED / PRELIMINARY finalists
- Top finalists with score, confidence, tier, and `MAX LANDED COST @25%`
- SerpApi calls + cost
- DataForSEO calls (must be 0)
- tests
- report Markdown path
- report JSON path
- any blocker or major evidence limitation
