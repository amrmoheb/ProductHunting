# Current Task

Task ID: BH-003
Status: READY
Owner: Codex execution / ChatGPT review

## Objective

Run the next diversified Amazon UAE production hunt after SOURCE-001 discarded Fabric resistance bands.

The goal is not to tune the model or build more framework. The goal is to find a product that has a realistic path to a sourcing decision:

**BUY / DO NOT BUY + maximum landed cost.**

SOURCE-001 outcome is final for Fabric resistance bands: `DISCARD`. Do not reopen it unless new real supplier evidence is explicitly supplied later.

## Integrity — frozen model

Use canonical production logic unchanged:
- V1.4D opportunity scoring unchanged
- V1.3 economics unchanged
- STRONG threshold unchanged
- confidence/tier rules unchanged
- diversity allocation from BH-002 unchanged

Do not retune weights, thresholds, confidence math, economics, or risk logic because previous hunts produced zero STRONG candidates.

Zero STRONG candidates remains an acceptable result.

## Marketplace / business target

- Amazon UAE / `amazon.ae` only
- Marketplace ID: `A2VIGQ35RCS4UG`
- Target selling-price band: AED 50–150
- Target net margin: 25%
- Prefer packaged weight <1.5 kg
- Prefer evergreen, simple, compact, low-breakage, low-compliance products
- Prefer low/moderate competition

Exclude/heavily reject:
- electronics / batteries
- cosmetics / supplements / food
- medicines / medical claims
- hazardous / adult / restricted products
- fragile / oversized products
- obvious IP/counterfeit risk
- high-regulation products

## Diversity — keep BH-002 fix

Do not regress the deterministic diversity allocator.

For this broad hunt:
- generate roughly 450–600 distinct concepts
- aim for >=12 macro categories where practical
- no category >15% generated unless justified
- cheap-screen roughly 90–120 across >=10 categories where available
- Amazon validation target 24–30
- max 3 validated per macro category
- max 1 validated per semantic family
- storage/organization max 2 validated
- deep target 10–14 only when enough candidates justify it
- max 2 deep per macro category
- normally max 1 deep per semantic family
- storage/organization max 1 deep

Diversity controls allocation only. Never alter scores to manufacture diversity.

## Commercial-first funnel

Use the smallest amount of research needed to reach a decision.

1. Generate a NEW diversified manifest. Do not recycle BH-001/BH-002 ordering as the hunt itself.
2. Run deterministic cheap screening.
3. Show category/family distribution before paid validation.
4. Validate Amazon UAE evidence under the provider caps below.
5. Score with frozen V1.4D/V1.3.
6. **Before spending additional deep/manual research effort, run an offline mathematical ceiling audit on every Amazon-validated candidate that has enough evidence:**
   - hold observed demand / competition / risk fixed
   - set economics raw to the theoretical maximum of 100
   - calculate the resulting maximum possible V1.4D opportunity score
   - if maximum possible score is <65, mark the candidate `NO_PATH_TO_STRONG` and do not promote it for supplier research
7. Deep-evaluate only candidates with a mathematical path to STRONG or a clearly documented reason why the ceiling cannot yet be computed.
8. For every deep candidate calculate current MAX LANDED COST @25% and supplier product-cost target under existing assumptions.
9. Do not request supplier quotes yet unless a candidate survives the hunt with a realistic mathematical path to STRONG.

The ceiling audit is triage only. It must not change V1.4D/V1.3 scoring or recommendation rules.

## Provider policy / hard caps

### SerpApi
- fresh cache first
- maximum live calls: **30**
- maximum cost budget: **USD 0.60**
- every Amazon request must explicitly use `amazon_domain=amazon.ae`
- stop before either limit

### DataForSEO
- **0 calls**

### SP-API
- **0 calls**

### Codex web research
Allowed only for targeted zero-key/public validation such as authoritative UAE risk/regulatory evidence when needed. Do not use broad web research to fabricate Amazon demand or replace Amazon UAE market evidence.

Never expose credentials or secrets.

## Selection priority

Among candidates that pass basic risk/price/relevance gates, prefer research capacity for products with:
- credible current Amazon UAE demand evidence
- lower competition barriers
- enough selling-price headroom for fees + 25% margin
- compact/light physical profile
- simple supplier specification
- low compliance/IP risk
- a theoretical V1.4D ceiling >=65

Do not favor a candidate merely because it looks novel or because previous hunts lacked winners.

## Final report

Write timestamped Markdown + JSON under `reports/` if practical.

Report:
- generated / cheap-screened / Amazon-validated / ceiling-eligible / deep / sourcing-finalist counts
- macro-category and semantic-family distribution at each relevant stage
- provider calls/cache hits/cost
- STRONG / VALIDATED / PRELIMINARY / HIGH_RISK counts
- candidates rejected as `NO_PATH_TO_STRONG`
- top cross-category candidates with:
  - exact product segment
  - representative ASINs
  - Amazon UAE current price basis/band
  - demand score/evidence
  - competition attractiveness score/evidence
  - risk
  - economics raw/status/confidence
  - V1.4D score
  - data confidence
  - tier
  - MAX LANDED COST @25%
  - supplier product-cost target @25%
  - theoretical max V1.4D score if economics raw = 100
  - main blocker

## Decision

Final hunt decision must explicitly be one of:

- `SOURCE_CANDIDATE_FOUND` — at least one candidate has a realistic mathematical path to STRONG and deserves a dedicated SOURCE task / supplier quote threshold analysis
- `NO_SOURCE_CANDIDATE` — no candidate deserves supplier work; zero winner is acceptable
- `BLOCKED` — only for a genuine execution/artifact problem

If `SOURCE_CANDIDATE_FOUND`, identify **one best candidate first** for the next SOURCE task. Do not create a long supplier-shopping list.

## Testing

- Run task-relevant tests before provider calls.
- If no code changes are required, do not create code just to satisfy the task.
- If a genuine reusable defect is found, make the smallest production-safe fix and run full `python3 -m pytest`.
- Tests must not unintentionally trigger provider calls.

## Handoff response

Return only:
- Task ID
- code changes, if any
- tests
- funnel counts
- ceiling-eligible count
- top 3 cross-category candidates
- best candidate and its current MAX LANDED COST @25%
- best candidate theoretical max score with economics=100
- decision
- SerpApi live calls/cache hits/cost
- DataForSEO calls (must be 0)
- SP-API calls (must be 0)
- report paths
- blocker, if any
