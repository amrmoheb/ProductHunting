# ProductHunting — Decision History

This file is append-only in spirit. Preserve closed commercial decisions so autonomous sessions do not recycle failures or retune around them.

## BH-001 — CLOSED

Decision: `DISCARD_ALL_AND_RUN_BH002`

Key result:
- 320 generated -> 77 cheap-screened -> 20 Amazon-validated -> 8 deep -> 0 sourcing finalists
- no STRONG candidates
- discovery collapsed heavily into storage/organizer products

Important conclusion:
- this was a discovery/selection diversity defect, not a V1.4D scoring defect
- offline economics ceiling audit showed no BH-001 product deserved supplier spend

Do not reopen exact BH-001 segments merely because a later hunt has no winner.

## BH-002 — CLOSED

Decision: `NO_FINALIST`; continue only with Fabric resistance bands for SOURCE analysis.

Key result:
- 450 generated -> 90 cheap-screened -> 30 validated -> 6 deep -> 0 finalists
- validated distribution: 2 candidates in each of 15 macro categories
- diversity fix worked
- no STRONG candidates

Leading candidate:
- Fabric resistance bands
- V1.4D score 47.13
- confidence 73.53%
- VALIDATED
- MAX LANDED COST @25% AED 19.40
- economics raw required for score 65: 83.31

Engineering decision:
- deterministic diversity allocation is production-correct and frozen
- do not regress or use diversity to alter score math

## SOURCE-001 — CLOSED

Product:
- wide non-slip textile/fabric closed-loop resistance-band set
- modeled as five bands / multiple resistance levels

Decision: `DISCARD`

Result:
- current score/confidence/tier: 47.13 / 73.53% / VALIDATED
- MAX LANDED COST @25%: AED 19.40
- economics raw required for 65: 83.31
- highest landed cost supporting canonical STRONG: NONE
- supplier target: N/A
- provider calls: 0

Commercial conclusion:
- do not request supplier quotes for this product
- even favorable landed-cost sensitivity could not satisfy the canonical STRONG requirements

Do not reopen without materially new real evidence that changes a locked input/gate.

## BH-003 — CLOSED

Decision: `NO_SOURCE_CANDIDATE`

Result:
- 450 generated -> 90 screened -> 30 selected -> 25 validated -> 0 deep -> 0 finalists
- ceiling-eligible: 0
- SerpApi: 25 live calls / 0 cache hits / recorded estimated cost USD 0.00
- DataForSEO: 0
- SP-API: 0

Highest theoretical ceilings with economics raw forced to 100 for triage only:
1. Radiator cleaning brush — current 29.95, confidence 51.96%, theoretical max 64.95
2. Wool dryer balls set — current 29.30, confidence 52.64%, theoretical max 64.30
3. Rotary cheese grater — current 29.12, confidence 52.64%, theoretical max 64.12

Commercial conclusion:
- none had a mathematical path to V1.4D score 65
- do not tune around Radiator cleaning brush being 0.05 below threshold
- no supplier work justified

## AUTO-001 — OPEN

Entry point: `BH-004`

Mission:
- autonomously continue HUNT -> review -> SOURCE -> discard/next HUNT until a supplier-ready candidate or hard stop
- do not return to user after normal intermediate failures
- preserve V1.4D/V1.3 and all correctness rules
- total provider envelope and run limits live in `.agents/PROJECT_STATE.md` and `.agents/AUTONOMOUS_HUNT_LOOP.md`

Future Codex phases must append concise entries below this point.
