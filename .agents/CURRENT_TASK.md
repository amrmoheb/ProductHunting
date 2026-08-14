# Current Task

Task ID: BH-004
Status: READY
Owner: Codex execution / ChatGPT review

## Objective

Run the next Amazon UAE production hunt after BH-003 returned `NO_SOURCE_CANDIDATE`.

BH-003 is closed. Its best theoretical ceiling was only 64.95 and no candidate had a sourcing path. Do not reopen or tune around that result.

The business objective remains simple:

**Find one product worth taking to supplier validation, or honestly return no candidate.**

A sourcing-worthy candidate must have a realistic path to:
- V1.4D score >=65
- confidence >=70
- known/acceptable risk
- adequate economics once real landed cost is supplied
- a usable maximum landed-cost threshold

## Integrity — frozen production model

Do not change:
- V1.4D weights or threshold
- V1.3 economics
- confidence math
- tier/gate logic
- BH-002 deterministic diversity allocation

Do not add a new scoring framework just to manufacture better candidates.

Zero winners is valid.

## Marketplace / commercial target

- Amazon UAE / `amazon.ae` only
- Marketplace ID: `A2VIGQ35RCS4UG`
- Allowed selling-price band remains AED 50–150
- For discovery/validation priority, favor the upper half of the band, roughly AED 80–150, because it generally leaves more room for fees, freight, and the 25% target margin. This is a research-priority heuristic only, not a scoring change or hard exclusion of AED 50–79 products.
- Target net margin: 25%
- Prefer packaged weight <1.5 kg
- Prefer compact, simple, low-breakage, low-compliance, non-seasonal or broadly evergreen products
- Prefer generic/private-label-friendly products with a simple supplier specification

Exclude/heavily reject:
- electronics / batteries
- cosmetics / supplements / food
- medicines / medical claims / rehab claims
- hazardous / adult / restricted products
- fragile / oversized products
- obvious IP/counterfeit/licensing risk
- high-regulation products

## Do not recycle old misses

Before generating/validating BH-004, read prior local BH-001/BH-002/BH-003 reports when available and build an offline exclusion list of exact previously validated/deep product segments.

Do not spend a new SerpApi call on an exact segment already evaluated unless there is a materially different commercial configuration that changes the segment economics/competition structure.

Do not merely rename old products.

## Discovery strategy — business-first, not model tuning

Generate a genuinely new diversified manifest, roughly 500–650 concepts across >=12 macro categories where practical.

Keep BH-002 diversity guardrails. In addition, prioritize concepts with these structural traits before paid validation:
- plausible Amazon UAE selling price preferably AED 80–150
- compact/light physical profile
- no obvious commodity race-to-bottom structure
- simple one-piece or simple set/bundle specification
- room for private-label differentiation without inventing an unobserved premium bundle
- low expected compliance/IP burden
- low breakage/return complexity
- not obviously dominated by a few household-name brands

These are discovery priorities only. Do not convert them into a replacement opportunity score.

Cheap-screen roughly 100–140 new concepts. Use the existing deterministic screen and diversity allocator.

## Paid validation allocation

Amazon validation target: up to 30 NEW segments under the provider caps below.

Allocate scarce calls toward candidates that combine:
- higher plausible price headroom
- lower structural risk
- semantic/category diversity
- simple sourcing specification
- no prior exact-segment evaluation

Keep:
- max 3 validated per macro category
- max 1 per semantic family
- storage/organization max 2 validated

## Commercial eligibility triage

After Amazon UAE evidence is collected and canonical V1.4D/V1.3 scoring is run, apply this offline triage before deep research.

For every sufficiently evidenced validated candidate calculate:

### 1. Score ceiling
Hold observed demand / competition / risk fixed and set economics raw to 100.

Calculate theoretical maximum V1.4D score.

- if max score <65 => `NO_PATH_TO_STRONG`
- do not deep-evaluate or source it

### 2. Confidence path
Inspect current canonical confidence without changing its formula.

- if confidence >=70 => confidence gate potentially satisfied
- if confidence <70 only because a specific resolvable evidence gap exists (for example authoritative UAE risk evidence), allow one targeted zero-key/public validation step
- if confidence still <70, or the missing evidence has no credible low-cost path, mark `NO_CONFIDENCE_PATH`

Do not assume economics=100 increases data confidence unless canonical code actually does so.

### 3. Risk gate
UNKNOWN risk cannot be promoted to sourcing.

Use targeted authoritative UAE/public research only when risk is the last realistic blocker for an otherwise ceiling-eligible candidate.

### 4. Economics headroom
For candidates surviving score ceiling + confidence + risk triage, run canonical V1.3 estimated economics and report:
- MAX LANDED COST @25%
- supplier product-cost target @25%
- current economics raw/status/confidence
- economics raw required to reach score 65

Do not claim actual margin/profit without real landed cost.

## Deep stage

Deep-evaluate only candidates that have:
- theoretical max V1.4D >=65
- confidence >=70 after allowed targeted evidence completion
- known/non-blocking risk
- no classification/IP/compliance blocker

Target 1–6 deep candidates, not an arbitrary quota. Zero is acceptable.

For each deep candidate, run the same offline landed-cost sensitivity logic used in SOURCE-001 to determine whether any nontrivial actual landed-cost range could make it STRONG.

If no landed-cost value can make the candidate STRONG, discard it inside BH-004. Do not create a separate SOURCE task for it.

## Source-candidate standard

`SOURCE_CANDIDATE_FOUND` requires at least one candidate for which the BH-004 analysis shows a real mathematical landed-cost range capable of meeting canonical STRONG requirements.

For the best surviving candidate report:
- exact commercial segment
- representative ASINs
- current Amazon UAE comparable price band/basis
- current V1.4D score/confidence/tier
- theoretical max score
- current MAX LANDED COST @25%
- highest modeled landed cost still capable of STRONG (approximately AED 0.10 precision when practical)
- corresponding supplier product-cost target under current assumptions
- main remaining assumption/blocker

If no candidate meets this standard, return `NO_SOURCE_CANDIDATE` and stop. Do not force a winner.

## Provider policy / hard caps

### SerpApi
- fresh cache/fingerprints first
- maximum live calls: 30
- maximum cost budget: USD 0.60
- every Amazon request must explicitly target `amazon_domain=amazon.ae`
- stop before either cap

### DataForSEO
- 0 calls

### SP-API
- 0 calls

### Public/Codex web research
Allowed only for narrow authoritative validation of a specific evidence gap on a candidate that already has a mathematical sourcing path. Do not use broad web research as fake Amazon demand evidence.

Never expose credentials or secrets.

## Testing / code changes

- Run task-relevant offline tests before provider calls.
- Do not create production code unless a genuine reusable correctness defect is found.
- If code changes are required, make the smallest safe change and run full `python3 -m pytest`.
- Tests must not intentionally trigger providers.

## Reports

Write timestamped Markdown + JSON under `reports/` if practical.

Include:
- generated / screened / selected / Amazon-validated counts
- prior-segment exclusions/reuse count
- category/family distribution
- ceiling-eligible count
- confidence-eligible count
- deep count
- sourcing-finalist count
- `NO_PATH_TO_STRONG` count
- `NO_CONFIDENCE_PATH` count
- STRONG / VALIDATED / PRELIMINARY / HIGH_RISK counts
- top cross-category results
- provider calls/cache/cost

## Final decision

Exactly one:
- `SOURCE_CANDIDATE_FOUND`
- `NO_SOURCE_CANDIDATE`
- `BLOCKED`

If `SOURCE_CANDIDATE_FOUND`, return only the single best candidate for supplier follow-up.

## Handoff response

Return only:
- Task ID
- code changes, if any
- tests
- funnel counts
- prior exact segments excluded/reused
- ceiling-eligible count
- confidence-eligible count
- deep count
- top 3 cross-category candidates with score/confidence/theoretical max
- best candidate, if any
- current MAX LANDED COST @25% for best candidate
- highest landed cost still supporting STRONG for best candidate
- corresponding supplier product-cost target
- decision
- SerpApi live calls/cache hits/cost
- DataForSEO calls (must be 0)
- SP-API calls (must be 0)
- report paths
- blocker, if any
