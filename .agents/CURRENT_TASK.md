# Current Task

Task ID: SOURCE-001
Status: READY
Owner: Codex execution / ChatGPT review

## Objective

Turn the only BH-002 candidate with a realistic mathematical path to STRONG — **Fabric resistance bands** — into a supplier-ready decision target using the completed BH-002 local report and canonical V1.4D/V1.3 arithmetic.

This is **not a new hunt** and must make **ZERO provider/network calls**.

BH-002 baseline:
- candidate: Fabric resistance bands
- V1.4D score: 47.13
- confidence: 73.53%
- tier: VALIDATED
- current MAX LANDED COST @25%: AED 19.40
- economics raw required to reach score 65: 83.31

Important model behavior: V1.3 economics sets the `actual_margin` subscore to zero while actual landed cost is unknown. Therefore public/estimated evidence alone cannot prove sourcing economics. A real supplier/landed-cost input is required.

## Source artifacts

Use the completed BH-002 local JSON/Markdown, locating it by BH-002 metadata if the timestamp differs. Expected paths include:
- `reports/2026-08-14-075059-bh-002-diversified-production-big-hunt.json`
- `reports/2026-08-14-075059-bh-002-diversified-production-big-hunt.md`

Do not regenerate market evidence.

## Required output

1. Lock the exact commercial segment represented by the BH-002 evidence (fabric resistance bands, pack/configuration, representative ASINs, price basis). Do not silently mix latex loop bands, tube bands, rehab/medical products, or materially different bundles.
2. Report current demand, competition, risk, price basis, V1.3 economics, confidence, and all current gates.
3. Report the current V1.3 economics components and contributions, including the zero `actual_margin` behavior.
4. Using the existing V1.3 `actual_landed_cost_aed` input and unchanged V1.4D scoring, calculate a deterministic landed-cost sensitivity grid from AED 5.00 up to the current AED 19.40 maximum (reasonable increments such as AED 1.00, plus exact boundary refinement).
5. For each grid point calculate:
   - actual net margin
   - V1.3 economics raw score
   - economics status/confidence
   - resulting V1.4D opportunity score
   - resulting recommendation tier
6. Find the **highest actual landed cost that can still produce V1.4D score >=65 and STRONG eligibility**, holding demand/competition/risk evidence unchanged. Refine to approximately AED 0.10 precision where practical.
7. Separately report:
   - MAX LANDED COST @25% (current 25% margin threshold)
   - maximum landed cost required for STRONG under the scoring model
   - supplier product-cost target @25% from the current BASE scenario
   - supplier product-cost target corresponding to the STRONG landed-cost threshold, using existing freight/customs/prep assumptions only
8. Make assumptions explicit. Physical profile, freight, prep, FBA category/tier, and reserves remain estimates unless the BH-002 artifact already contains observed values.
9. Produce a one-page **supplier quote checklist** for the user containing only the fields needed to replace estimates later: unit price, MOQ, exact pack configuration, packaged weight/dimensions, shipping term (EXW/FOB/DDP), freight to UAE per unit, customs/duty, prep/labeling, inbound-to-Amazon, and any material/quality certification relevant to the exact product.
10. Final decision must be one of:
   - `READY_TO_REQUEST_SUPPLIER_QUOTES` if a nontrivial landed-cost range can mathematically support STRONG;
   - `DISCARD` if even very low realistic landed cost cannot support STRONG;
   - `BLOCKED_BY_ARTIFACT` only if the BH-002 local evidence needed for the calculation is missing.

## Integrity

- V1.4D weights unchanged.
- V1.3 economics unchanged.
- No provider calls: SerpApi=0, DataForSEO=0, SP-API=0, web/provider collection=0.
- Do not invent supplier prices or actual landed costs.
- Do not claim actual profit until a real supplier quote is supplied.
- No production code changes unless a genuine reusable arithmetic defect is discovered.

## Output

Write timestamped Markdown + JSON under `reports/` if practical.

Return only:
- Task ID
- exact product segment
- current score/confidence/tier
- current MAX LANDED COST @25%
- economics raw required for 65
- highest landed cost that still supports STRONG
- corresponding supplier product-cost target under current assumptions
- decision
- provider calls (must be 0)
- report paths
- blocker, if any
