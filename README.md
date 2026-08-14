# amazon-uae-product-scout

A local, read-only Amazon.ae product-opportunity research system in which Codex CLI is the AI/orchestration layer and Python supplies deterministic normalization, scoring, profitability, history, and reports. It supports fixture-only `mock`, zero-key current-web `research`, and SP-API-enhanced `live` modes. V1 has no additional LLM API and no web application.

The fixed target is Amazon UAE (`A2VIGQ35RCS4UG`), region `eu`, endpoint `https://sellingpartnerapi-eu.amazon.com`, and AED. The project never silently substitutes Amazon US.

## Architecture

Codex follows [AGENTS.md](AGENTS.md), uses two project-scoped Amazon SP-API MCP servers for read-only discovery, and hands observations to the typed Python analytics under `src/amazon_scout`. Configuration lives in `config/`; append-only observations and run history live in SQLite; raw/normalized snapshots live under `research/`; Markdown/JSON outputs live under `reports/`. Tests use synthetic fixtures and cannot call SP-API.

The official Amazon package is an example/educational Local MCP implementation, not a supported production product. Secure, test, audit, and optimize it to your organization’s standards before production use.

## Prerequisites

- macOS/Linux shell, Python 3.11+, Node.js 20+, `npx`, and Codex CLI
- For live mode: an Amazon Professional selling account, an SP-API developer application, the required roles, self-authorization/authorization, and a refresh token
- Optional for development: `python3 -m pip install -e '.[dev]'`; the runtime itself has no third-party Python dependency

## How the Amazon MCP works

[`.codex/config.toml`](.codex/config.toml) registers:

- `sp-api-dev-assistant`: reference/exploration assistance and SP-API execution tooling
- `sp-api-workflow`: workflow-oriented SP-API tooling

Both run locally through `npx -y @amazon-sp-api-release/sp-api-dev-mcp ...`, inherit only the three credential environment variables, and receive static EU endpoint configuration. Credentials are never written into TOML. MCP configuration is loaded when Codex starts, so restart Codex after changes and trust the project if prompted.

Amazon’s currently published example package documentation and command names can evolve. The setup checker smoke-tests the exact commands requested by this project; if an installed release rejects one, consult the package’s official README/MCP reference before changing `.codex/config.toml`.

## Obtain and store credentials

1. In Seller Central, maintain a Professional account and register as an SP-API developer if needed.
2. Create or select a private SP-API application with the least-privilege roles needed for Sellers, Catalog Items, Product Pricing, Product Fees, and optionally Reports/Brand Analytics.
3. Self-authorize the application for your seller account (or complete the OAuth authorization flow) and obtain the refresh token.
4. Copy `.env.example` to `.env` and fill `SP_API_CLIENT_ID`, `SP_API_CLIENT_SECRET`, and `SP_API_REFRESH_TOKEN`. Do not add quotes unless they are part of normal shell-style quoting.
5. Keep `.env` local. It is ignored by Git. Never paste secrets into prompts, reports, issue trackers, or logs.

Amazon account UI and role names can change; use the current SP-API registration and application-authorization documentation in Seller Central. Brand Analytics is optional and usually requires appropriate brand/report access.

## Verify setup and MCP

```bash
./scripts/check-setup.sh
```

This performs offline checks and never prints secret values. To allow `npx` to download/start the MCP package for an eight-second smoke test:

```bash
SCOUT_CHECK_MCP_PACKAGE=1 ./scripts/check-setup.sh
```

Restart Codex from this directory after creating/changing `.codex/config.toml`, then run `codex mcp list`. Inside Codex, run `/mcp` and verify both `sp-api-dev-assistant` and `sp-api-workflow` appear.

With live credentials, ask Codex: “Perform the safe read-only MCP validation: call getMarketplaceParticipations, confirm marketplace A2VIGQ35RCS4UG, then perform one harmless UAE catalog lookup. Do not mutate seller state.” Do not proceed if UAE participation is absent. V1 never writes listings, prices, inventory, shipments, or orders.

## Run

Initialize the historical database and exercise deterministic research without credentials:

```bash
./scripts/init-db
SCOUT_MODE=mock ./scripts/score-products
./scripts/run-agent.sh
```

`run-agent.sh` parses only an allowlist of `.env` keys (it does not execute the file), checks Node 20+, Codex, and credentials, hides secret values, and safely launches mock mode when credentials are absent.

For live mode, populate `.env` and set `SCOUT_MODE=live`, then:

```bash
./scripts/run-agent.sh
```

Codex performs live collection through MCP. The Python package intentionally contains no second SP-API client or LLM dependency; its job is deterministic analytics and persistence. Tests always stay on fixtures.

## RESEARCH MODE — NO AMAZON SP-API REQUIRED

Research mode performs current, evidence-driven Amazon UAE product hunting without `SP_API_CLIENT_ID`, `SP_API_CLIENT_SECRET`, or `SP_API_REFRESH_TOKEN`. Codex uses live web search, creates a structured evidence bundle, and hands it to deterministic Python validation and scoring:

```text
Codex live research → evidence JSON → validation/normalization → SQLite
                    → deterministic scoring → Markdown/JSON report
```

Python never calls Codex web search and never fills missing observations. Unknown values remain null/UNKNOWN. Web and third-party observations are never represented as SP-API or Amazon Brand Analytics data.

Run the source doctor, then launch:

```bash
./scripts/research-doctor
SCOUT_MODE=research ./scripts/run-agent.sh
```

If `SCOUT_MODE` is unset, `run-agent.sh` selects `live` when all three Amazon credentials exist and otherwise selects `research`. It never silently selects mock. Mock mode remains explicit for fixtures/tests:

```bash
SCOUT_MODE=mock ./scripts/score-products
```

### Research sources and truthfulness

- Codex live web search is the zero-credential baseline. It can observe indexed Amazon.ae results, titles, visible ASINs, approximate prices, brands, rating/review snippets, badges, UAE context, seasonality, regulation, and sourcing information. Search snippets have limited freshness/authority and receive appropriate LOW/MEDIUM confidence.
- Official Amazon UAE pages (`sell.amazon.ae`) are preferred for fee methodology and seller guidance. `config/amazon_uae_public_fees.yaml` records verification references and assumptions. Referral fees are category-dependent; FBA depends on packaged dimensions, weight, price, and tier. Unknown components stay unknown.
- SerpApi is optional. Its current Amazon Search/Product engines explicitly support `amazon_domain=amazon.ae`. Set `SERPAPI_API_KEY` only if desired.
- DataForSEO is an optional V1.4A Amazon Labs audit provider. It defaults to disabled, dynamically validates UAE/location-language support, isolates sandbox dummy evidence, and never changes demand, competition, opportunity scores, gates, or tiers. Production requires explicit `DATAFORSEO_ALLOW_PAID=true` plus local task and cost budgets; Merchant Amazon sellers remains schema-only and disabled.
- The V1.4B real-data POC is a separate, default-refusing audit command for the five persisted candidates. Its V1.4B.1 refresh is bulk-only, reuses the production cache, and does not rescore candidates: `./scripts/dataforseo-v14b-poc`.
- V1.4B.1 makes the POC refresh bulk-only, distinguishes numeric/zero/null/missing provider volumes, reports unrun competition as `NOT_RUN`, and adds a separate six-keyword, one-task coverage diagnostic: `./scripts/dataforseo-v14b-coverage-probe`. Neither path changes official scores.
- Rainforest/Traject Data is optional and fail-closed until current official documentation confirms `amazon.ae` support.
- SP-API remains highest priority in live mode and improves catalog, offer, rank, and fee confidence. Brand Analytics, when authorized, improves demand evidence.

External retailer prices are never Amazon prices. Review counts and ranks are never monthly sales. Generic global/GCC trends remain separate from UAE signals.

### Evidence bundles and provenance

Codex writes `research/raw/<timestamp>-<slug>-evidence.json` conforming to [research/evidence.schema.json](research/evidence.schema.json). Each atomic `EvidenceRecord` contains its ID, run, metric/value/unit, ASIN/keyword/niche, UAE marketplace, provider/type, URL/title, observation and retrieval timestamps, VERY_HIGH/HIGH/MEDIUM/LOW/VERY_LOW confidence, estimate flag, and notes.

Validate, persist, calculate, and report with:

```bash
./scripts/ingest-research research/raw/<file>-evidence.json
```

The command rejects non-UAE marketplace records, invalid/non-finite numeric values, malformed timestamps/URLs, and duplicate evidence IDs. It appends evidence and derived metrics to SQLite; it never persists provider credentials. Derived metrics reference supporting evidence IDs.

Historical observations are not overwritten. When enough history exists, the analytics can calculate changes in price, reviews, rating, rank, competitor count, and search volume; a single observation produces UNKNOWN rather than a fabricated trend.

### Progressive research and scoring

Broad runs start with 30–100 narrow niches, then progressively screen, validate, score, and deep-dive. A candidate cannot enter FINAL_TOP_10 without multiple current observations plus price, competition, demand, and risk evidence. V1.4D caps confidence 55–69 at VALIDATED, confidence below 55 at PRELIMINARY_NEEDS_EVIDENCE, and requires confidence >=70 plus known risk and adequate economics for STRONG sourcing consideration.

Opportunity and confidence remain separate. A high opportunity score with confidence 25 is labeled “research more,” never “buy inventory.” Reports expose candidate funnel, source status, evidence URLs, fee uncertainty, regulatory risk, seasonality, differentiation, and verification steps.

Research-mode public fee economics distinguishes known referral estimates from unknown fulfillment components. It reports maximum landed cost before unknown FBA adjustment and bounded low/mid/high fee scenarios where assumptions are practical. Exact profitability is never claimed without sourcing and fulfillment costs.

### V1.1 evidence gates

V1.1 treats unknown as missing evidence—not as a neutral score. Demand, competition, and risk components each expose a nullable score, confidence, and status. A validated opportunity score exists only when the price, demand, competition, and risk gates pass; the separate preliminary score may help prioritize further research but is never a sourcing recommendation. Overall confidence below 60 also blocks sourcing consideration.

Price fields have deliberately different meanings:

- `observed_market_price_aed` is a current Amazon UAE price observation.
- `proposed_selling_price_aed` is a proposed commercial scenario.
- `bundle_hypothesis_price_aed` is an unvalidated pack-price hypothesis.
- `fee_calculation_price_aed` is the exact selling-price basis used for fee and maximum-landed-cost calculations.

An external UAE retailer price is context, not an Amazon UAE price. A stale observation is historical context, not current gate evidence. A proposed bundle price never overwrites the observed unit price or passes the normal observed-price gate.

Candidates are classified deterministically as `OBSERVED_MARKET_OPPORTUNITY`, `BUNDLE_HYPOTHESIS`, or `DIFFERENTIATION_HYPOTHESIS`, then reported as qualified, promising but unvalidated, hypotheses, evidence gaps, constraint rejections, or do-not-source cases. Reports may contain fewer than ten qualified finalists; missing slots are never filled with weak candidates.

Demand normally requires one current strong structured observation (Brand Analytics, supported Amazon search volume, or reliable rank) or two distinct weaker signals with at least one Amazon UAE/UAE-specific signal. Competition normally requires multiple Amazon/UAE competing products and at least two dimensions such as product count, brands, reviews, sponsored density, price dispersion, offers, keyword overlap, or result density. Stale evidence cannot independently pass either gate.

Follow-up work is gap-directed: if a promising candidate fails only demand, the next research pass targets UAE demand evidence rather than collecting more generic context. The same principle applies to price, competition, risk, and confidence gaps.

### V1.2 — SerpApi Amazon UAE precision layer

V1.2 keeps Codex live web search as the inexpensive broad-discovery layer. Generate at least 60 narrow niches, screen them to roughly 12–15 candidates, and only then use SerpApi. Searches use `engine=amazon`, `amazon_domain=amazon.ae`, and a buyer-intent `k` keyword. Selective finalist deep dives use `engine=amazon_product`, the same domain, and an ASIN. Non-UAE responses are rejected.

SerpApi can provide current Amazon UAE fields such as ASIN, title, brand, position, sponsored status, rating, reviews, displayed AED price, Prime/stock hints, badges, variants, and occasionally `bought_last_month`. It does not provide SP-API seller/account data, Brand Analytics search volume, exact sales, or necessarily seller/offer counts. Search position is not BSR; reviews are social proof rather than sales; `100+ bought in past month` is retained verbatim and parsed only as a non-exact lower bound of 100.

Calls require all three controls: `RESEARCH_ALLOW_PAID_PROVIDERS=true`, positive `RESEARCH_MAX_PAID_CALLS`, and positive `RESEARCH_MAX_COST_USD`. The strategy spends zero calls on broad discovery, up to 15 niche searches, roughly 10 gap-directed variants, up to 10 selective product calls, and protects the final five calls. Forty is a local per-run ceiling, not SerpApi account quota or a spending target.

Equivalent requests use a deterministic fingerprint excluding the API key. Responses are cached under `research/cache/serpapi/` for eight hours by default (`SERPAPI_CACHE_TTL_HOURS`); fresh hits consume no call. Cache metadata and reports never contain the key.

After Codex produces a web evidence bundle, augment it rather than replacing it:

```bash
./scripts/serpapi-validate \
  --base-bundle research/raw/<web-evidence>.json \
  --candidate 'niche=buyer intent keyword' \
  --output research/raw/<combined-evidence>.json
./scripts/ingest-research research/raw/<combined-evidence>.json
```

Check without a call, or run the explicit one-call Amazon.ae health test:

```bash
./scripts/research-doctor
./scripts/research-doctor --test-serpapi
```

The health test searches `drawer organizer`, validates domain and organic-result/ASIN parsing, prints no response or secret, and reports that one search was consumed.

#### V1.2.1 relevance and risk-gap closure

Every SerpApi result is reproducibly classified as `EXACT_TARGET`, `CLOSE_VARIANT`, `ACCESSORY`, `WRONG_PRODUCT`, or `AMBIGUOUS`. The classifier stores requested/matched/missing tokens, product anchors, accessory terms, rule version, and reason. Only exact and close results contribute to price, demand, rating/review, or competition aggregates. Reports show separate exact, close, and combined validated price samples; cheap accessories and unrelated expensive products cannot distort the median.

If price, demand, and competition pass but risk is unknown, the ingest step emits an automatic zero-paid risk-gap plan. Codex then checks MoIAT, Dubai Municipality, UAE government, and Amazon UAE official sources, adds explicit risk evidence, and re-runs deterministic scoring. This uses no SerpApi calls. Failure to find a specific restriction leaves risk UNKNOWN rather than inventing LOW risk.

#### V1.2.2 commercial-segment comparability

Semantic relevance does not imply commercial comparability. Each relevant Amazon.ae result now has reproducible segment fields for pack count, size/dimensions, positioning, material/features, subtype, brand tier, and bundle configuration, plus a persisted `COMPARABLE`, `ADJACENT`, `NON_COMPARABLE`, or `UNKNOWN` decision and reasons.

Reports retain the all-relevant price distribution for market context, but price gates and primary competition metrics use only the comparable segment. The default gate requires at least five current comparable Amazon.ae products and either a comparable median inside the requested price band or at least 40% of comparable products inside it. Configure these thresholds in `config/commercial_segments.yaml`. A single premium listing cannot make a predominantly low-priced segment pass; a distinct premium possibility is labeled `PREMIUM_POSITIONING_HYPOTHESIS` instead.

A non-null validated opportunity score means enough evidence exists to calculate it. It does not mean the opportunity is attractive or that inventory should be purchased. Scores below the configured recommendation threshold are labeled `VALIDATED_WEAK_OPPORTUNITY`; recommendation strength and the unchanged 60% sourcing-confidence threshold remain separate.

#### V1.2.3 canonical gates and report semantics

All candidates—including broad/generic commercial profiles—use the same price-gate function: at least five current comparable Amazon.ae prices, then either an in-range median or an in-band ratio of at least 40%. A below-floor core market with an observable in-band premium tail is classified canonically as `PREMIUM_POSITIONING_HYPOTHESIS`; it cannot simultaneously remain a validated core opportunity.

Reports distinguish `TECHNICALLY VALIDATED` (price, demand, competition, risk, and confidence ≥55 all pass) from `QUALIFIED STRONG OPPORTUNITIES` (technical validation plus score ≥65, confidence ≥70, known risk, and adequate economics). Multi-phase SerpApi runs accumulate one persisted complete-run usage record; phase subtotals never replace the report header total.

### Optional provider cost controls

Paid calls are disabled by default even when a key exists:

```dotenv
RESEARCH_ALLOW_PAID_PROVIDERS=false
RESEARCH_MAX_PAID_CALLS=0
RESEARCH_MAX_COST_USD=0
```

To opt in, set `RESEARCH_ALLOW_PAID_PROVIDERS=true` and positive call and cost limits. Every adapter checks both before a call. No provider is required for research mode, and no batch may silently exceed either limit.

### Research-mode limitations

Research mode is real current research, but weaker than authorized SP-API and Brand Analytics: indexed content can be stale or incomplete, search engines may omit products, offer/seller detail is limited, and Amazon-internal query volume is unavailable without an authorized or supported structured source. It is intended to identify evidence-backed validation candidates—not to authorize inventory purchases.

## Example prompts

- “Find me the best 10 products to sell on Amazon UAE.”
- “Research kitchen products between AED 50 and AED 150. Avoid electronics. I want at least 25% margin.”
- “Analyze ASIN B0XXXXXXXX.”
- “Analyze the car phone holder niche on Amazon UAE.”
- “Find opportunities priced AED 70–180 and give me the maximum landed cost to negotiate.”

## Scoring

`config/scoring.yaml` is JSON-compatible YAML loaded by the standard library. V1.4D is demand 30%, competition attractiveness 25%, unchanged V1.3 economics 35%, and risk attractiveness 10%. Demand families are listing activity 35%, review activity 30%, search evidence 20%, and breadth/freshness 15%. Competition families are comparable density 30%, review barrier 25%, market concentration 15%, observed DataForSEO Product Competitors 20%, and observed Ranked Keywords 10%; missing provider evidence contributes zero and is never treated as low competition.

Data confidence is separate and rewards authorized Brand Analytics, pricing, ranks, adequate samples, fee estimates, and recency. Missing inputs get no confidence credit. A score of 88 with confidence 30 is not presented as a confident winner.

Profit calculations require observed/estimated Amazon fees and a user-provided landed cost. When cost is unknown, reports calculate the maximum landed cost for 20%, 25%, and 30% net margin. No BSR-to-sales conversion is implemented.

## Tests

The V1.4B.2 competition utility POC is disabled by default. It is restricted to
ASIN `B0C5WLFKDT`, Amazon UAE location `2784`, Arabic, Ranked Keywords and
Product Competitors, with hard ceilings of two tasks and USD 0.05. Identical
production requests reuse the secret-free DataForSEO cache. It never changes
official scores and does not call Bulk Search Volume or Merchant Sellers.

V1.4C.2 prospective shadow validation consumes a completed current-stack
Amazon.ae evidence bundle. Candidate selection is frozen before the audit-only
V1.4C score is calculated. Optional DataForSEO competition gap calls are capped
at 10 tasks and USD 0.15, prioritize Product Competitors, reuse cache, and never
call Bulk Search Volume by default. Production scoring remains unchanged.

The V1.4C.2A collector creates that bundle from a provenance-bearing discovery
manifest. Discovery remains a Codex/current-research responsibility because
Python does not perform Codex web search or invent product ideas. Each manifest
candidate supplies an ID, name, Amazon keyword, query/source, discovery time,
marketplace, and generation reason. The collector deduplicates and cheaply
screens ideas, uses the existing SerpApi Amazon.ae validation and budget/cache,
then freezes deep finalists using current production gates, confidence, and
scores only. It never imports the shadow scorer or calls DataForSEO.

```bash
./scripts/v14c2-collect-prospective-bundle --dry-run
./scripts/v14c2-collect-prospective-bundle --discovery-manifest research/raw/<prospective-discovery>.json
```

```bash
python3 -m pytest
# dependency-free fallback when pytest is not installed:
PYTHONPATH=src python3 -m unittest discover -s tests
```

The tests cover scoring, profitability, maximum landed costs, normalization, missing metrics, confidence, risks, zero price, missing fees/cost, unavailable Brand Analytics/rank, one competitor, large catalogs, and negative margins. They do not access the network.

## Limitations

- Access and returned fields depend on the authorized seller, roles, API availability, and rate limits.
- Brand Analytics is optional; authorization failure reduces confidence but does not stop a run.
- Catalog result count is not seller count; ASINs, sellers, and offers remain distinct.
- Sales rank is demand evidence, not exact sales. Product Opportunity Explorer terminology may describe analogous analysis only; this project does not claim the complete private POE dataset.
- Fee estimates depend on the ASIN, price, fulfillment facts, and API response. Unknown FBA fees remain unknown.
- Mock recommendations are synthetic demonstrations and must not guide purchasing.
- VAT, import rules, product conformity, trademarks, seasonality, and supplier quality require current UAE-specific validation.

## Troubleshooting

- MCP servers absent: restart Codex in this project, trust it, run `codex mcp list`, then `/mcp`.
- Node error: install Node 20+ and ensure `node`/`npx` are on PATH.
- Package startup error: confirm network/npm access and run the opt-in smoke test. Review the official Amazon package README if a command changed.
- Authorization/role error: verify app roles and re-authorize; record Brand Analytics unavailable and continue if only that source failed.
- Wrong marketplace: stop. Confirm Sellers API returns `A2VIGQ35RCS4UG` and every request is scoped to it.
- Tests cannot import package: run from the project root; `pyproject.toml` adds `src` for pytest, or install editable mode.
- Live mode says credentials are incomplete: populate all three `.env` fields without printing them.

## Source notes

The project follows the official [Amazon SP-API sample repository](https://github.com/amzn/selling-partner-api-samples), [Catalog Items v2022-04-01 reference](https://developer-docs.amazon.com/sp-api/lang-en_US/reference/catalog-items-v2022-04-01), and [OpenAI Codex documentation](https://developers.openai.com/codex/). Verify current endpoint behavior with the MCP reference tools before live calls.
