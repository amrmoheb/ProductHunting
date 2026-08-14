# Current Task

Task ID: BH-001-AUDIT
Status: READY
Owner: Codex execution / ChatGPT review

## Objective

Perform a **strict offline post-hunt ceiling audit** on the completed `BH-001` deep candidates before any new provider spend or sourcing work.

BH-001 result summary:

- 320 generated
- 77 cheap-screened
- 20 Amazon-validated
- 8 deep-evaluated
- 0 canonical sourcing finalists
- 0 STRONG / 8 VALIDATED / 0 PRELIMINARY among the deep candidates
- Top current scores were approximately 48.36, 46.29, and 42.62 with confidence above 72%
- V1.3 economics were PARTIAL/estimated

The purpose of this task is to answer one decision question:

> **Can any of the 8 deep candidates mathematically reach V1.4D STRONG (score >=65) through better economics/evidence, or are they structurally too weak and should be discarded before spending more money/time?**

This is not a new hunt and not a model-tuning task.

## Source artifacts

Use the latest BH-001 local outputs if present:

- `reports/2026-08-14-072822-bh-001-production-big-hunt.json`
- `reports/2026-08-14-072822-bh-001-production-big-hunt.md`

If timestamp differs locally, locate the completed BH-001 report by task/run metadata. Do not regenerate market evidence.

## Provider policy

**ZERO network/provider calls.**

- SerpApi: 0
- DataForSEO: 0
- SP-API: 0
- web/provider collection from Python: 0

Use only persisted BH-001 evidence and deterministic local calculations.

## Canonical model

Do not modify formulas.

V1.4D opportunity weights remain exactly:

- demand: 30%
- competition attractiveness: 25%
- unchanged V1.3 economics: 35%
- risk attractiveness: 10%

STRONG still requires score >=65, confidence >=70, known risk, adequate economics, and all existing gates.

## Required audit for all 8 deep candidates

For each candidate, report:

1. Current V1.4D opportunity score.
2. Current overall evidence confidence.
3. Demand score and contribution.
4. Competition attractiveness score and contribution.
5. Risk attractiveness score/contribution and risk status.
6. Current V1.3 economics raw score, contribution, confidence/status.
7. **Pre-economics score** = current score minus current economics contribution.
8. **Economics raw required to reach 65** using the active 35% weight.
9. **Mathematical maximum score if economics raw = 100**, holding demand/competition/risk unchanged.
10. Classification:
   - `STRUCTURALLY_CANNOT_REACH_STRONG` if max score <65.
   - `THEORETICALLY_REACHABLE_BUT_REQUIRES_UNREALISTIC_ECONOMICS` if required economics raw is >85 or otherwise clearly implausible under V1.3 semantics.
   - `ECONOMICS_VALIDATION_WORTHWHILE` if required economics raw <=85 and all non-economics blockers are realistically resolvable.
   - `OTHER_EVIDENCE_BLOCKER` if score ceiling is reachable but known risk/gates/confidence prevent STRONG.
11. Current `MAX LANDED COST @25%` and supplier product-cost target if available.
12. Exact blocker to sourcing.

Do not assume improving economics also improves demand, competition, or risk. Do not reward missing evidence.

## Decision output

Produce a concise ranked decision table for all eight and a final recommendation:

- `DISCARD_ALL_AND_RUN_BH002` if none are realistically capable of STRONG.
- `DEEPEN_TOP_N` only for candidates with a mathematically realistic path to >=65 and no structural non-economics blocker.

If `DEEPEN_TOP_N`, name only the candidates that deserve additional validation and specify exactly which missing evidence would materially change the decision.

Do **not** lower the 65 STRONG threshold and do not retune weights because BH-001 produced zero winners.

## Testing / integrity

- Use existing canonical V1.4D/V1.3 helpers where practical.
- If code already exposes the required arithmetic, prefer a one-off offline report/script or direct deterministic calculation rather than production code changes.
- Do not create a code commit unless an actual reusable defect is found.
- Run only relevant offline tests if code is touched.

## Output

Write a small timestamped Markdown + JSON audit under `reports/` if practical.

## Handoff response

Return only:

- Task ID
- provider calls (must be 0)
- table/list of all 8 candidates with current score, required economics raw for 65, max score at economics=100, classification
- candidates worth deeper validation, if any
- final decision: `DISCARD_ALL_AND_RUN_BH002` or `DEEPEN_TOP_N`
- report path(s)
- any blocker
