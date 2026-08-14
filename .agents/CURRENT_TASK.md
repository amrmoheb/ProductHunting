# Current Task

Task ID: BH-002
Status: READY
Owner: Codex execution / ChatGPT review

## Objective

Run the second Amazon UAE production Big Hunt, but fix the **discovery/selection diversity bias** exposed by BH-001 before spending provider calls.

BH-001 generated 320 ideas but all 8 deep candidates collapsed into the same broad storage/organization theme. The post-hunt ceiling audit concluded all should be discarded. This is not a V1.4D scoring failure; it is a funnel diversity failure.

Do not retune V1.4D or V1.3 economics.

## Confirmed bias to correct

The current prospective collector can validate the first survivors in manifest order and the deep shortlist can rank purely by confidence/score without any category-diversity guardrail. A front-loaded discovery manifest can therefore consume most validation capacity on one semantic family.

Before live validation, make the smallest reusable production-safe change necessary so Amazon-validation candidate selection is **diversity-aware and deterministic**.

Do not alter candidate scores to create diversity. Diversity applies to which candidates receive scarce validation/deep-evaluation slots, not to the final score formula.

## Required diversity model

Every generated candidate must have a normalized `macro_category` and `semantic_family` (derive deterministically when missing, or require/normalize them in the discovery manifest).

Broad discovery should span at least these kinds of low-compliance families when plausible:

- kitchen tools / food-prep accessories (non-electric, non-food)
- home cleaning tools
- laundry / clothing-care accessories
- travel accessories
- automotive accessories (non-electronic, non-safety-critical)
- office / desk accessories
- crafts / hobby tools
- small DIY / hardware helpers
- garden / balcony accessories
- pet accessories (non-food, non-medical)
- fitness / mobility accessories (non-medical)
- personal accessories (non-cosmetic)
- bathroom accessories
- outdoor / picnic accessories
- household utility / maintenance

Do not force a category if no valid concepts survive the business/risk filters.

### Diversity guardrails

For an unconstrained broad hunt:

1. Generate **400–600 distinct concepts** across at least **12 macro categories**.
2. No single macro category should exceed **15% of generated concepts** unless fewer than 12 valid categories are realistically available; report any exception.
3. Semantic deduplication must treat near-identical organizer/storage variants as one family where practical.
4. Cheap-screen target: **80–120 survivors** across at least **10 macro categories** when enough valid ideas survive.
5. Amazon.ae validation target: **24–30 candidates** with:
   - maximum **3 candidates per macro category**;
   - maximum **1 candidate per semantic family**;
   - storage/organization as a broad theme capped at **2 validation candidates total**.
6. Deep-evaluation target: **10–14** with:
   - maximum **2 per macro category**;
   - normally maximum **1 per semantic family**;
   - storage/organization capped at **1 deep candidate** unless an independently validated candidate is already STRONG-eligible before the diversity cap is applied.
7. Diversity must never change V1.4D score, confidence, economics, risk, or recommendation-tier math.
8. A genuinely superior candidate must still be reported even if another candidate from its category exists; the cap is primarily a scarce-validation-slot allocation rule, not a reason to falsify or hide final evidence.

Add funnel/report fields showing category distribution at generated, cheap-screened, Amazon-validated, and deep stages.

## Marketplace / business constraints

- Amazon UAE / amazon.ae only (`A2VIGQ35RCS4UG`).
- Current selling-price target: AED 50–150.
- Target net margin: 25%.
- Prefer packaged weight <1.5 kg.
- Evergreen, simple, compact, low-breakage, low-compliance preferred.
- Exclude/heavily reject electronics, batteries, cosmetics, supplements, food, medicines/medical claims, hazardous goods, fragile/oversized items, obvious IP/counterfeit risk, and high-regulation products.

## Production scoring

Use canonical V1.4D unchanged:

- demand 30%
- competition attractiveness 25%
- V1.3 economics 35%
- risk attractiveness 10%

Tier rules unchanged:

- confidence <55 => PRELIMINARY_NEEDS_EVIDENCE
- 55–69 => maximum VALIDATED
- >=70 => potentially STRONG only when score >=65, risk known, economics adequate, and all required gates pass

Do not lower the STRONG threshold because BH-001 produced zero winners.

## Provider policy

### DataForSEO

0 calls. Do not use it in BH-002.

### SerpApi

Use fresh cache first. Hard limits for BH-002:

- maximum live/provider calls: **30**
- maximum cost budget: **USD 0.60**
- every Amazon request must explicitly target `amazon_domain=amazon.ae`
- stop before either cap

Do not spend a call on two candidates from the same semantic family when an unvalidated family is available and otherwise competitive at the cheap-screen stage.

### SP-API

0 calls unless already configured and safely available through the existing read-only route; do not require it and do not attempt onboarding.

## Execution order

1. Inspect and minimally fix reusable diversity allocation in the discovery/collector path. Add regression tests proving manifest order cannot cause one category to monopolize validation slots.
2. Run full offline tests before any provider call.
3. Generate a NEW diversified discovery manifest; do not reuse BH-001's storage-heavy ordering.
4. Run the diversified cheap screen.
5. Print/report category distribution before live validation and verify the guardrails.
6. Only then perform Amazon.ae validation under the SerpApi caps.
7. Deep-evaluate and run unchanged V1.3 economics for justified candidates.
8. Run BH-001-style economics ceiling sanity on deep candidates before recommending extra manual supplier research.

## Final decision report

Write timestamped Markdown + JSON. Include:

- generated / cheap-screened / Amazon-validated / deep / sourcing-finalist counts
- category distribution at each stage
- semantic-family diversity metrics
- STRONG / VALIDATED / PRELIMINARY counts
- top candidates from different categories with V1.4D score, confidence, demand, competition, risk, economics, MAX LANDED COST @25%, supplier target @25%
- current comparable Amazon UAE price band and representative ASINs
- primary reason for/against sourcing
- mathematical max score if economics=100 for each deep candidate
- SerpApi live calls, cache hits, cost
- DataForSEO calls = 0
- explicit statement if no STRONG candidate exists

Do not force winners. Zero STRONG is acceptable, but a second category-collapse is not.

## Testing

Add focused tests for:

- manifest-order independence of validation allocation
- macro-category cap
- semantic-family cap
- storage/organization cap
- diversity metadata/reporting
- scoring values remain unchanged by diversity allocation

Run targeted tests and full `python3 -m pytest` before live calls and again after any code changes.

## Git behavior

If reusable code changes are required, create/push branch `codex/bh-002-diversity`; do not merge to main. Generated research reports may remain gitignored/local.

## Handoff response

Return concise engineering/research summary:

- Task ID
- diversity root cause and fix
- code files changed / branch / commit if any
- tests
- generated / cheap-screened / validated / deep / finalist funnel
- macro-category counts at validated/deep stages
- STRONG / VALIDATED / PRELIMINARY counts
- top cross-category candidates with score/confidence/tier/MAX LANDED COST @25%
- SerpApi live calls/cache hits/cost
- DataForSEO calls (must be 0)
- report paths
- blocker/major limitation
