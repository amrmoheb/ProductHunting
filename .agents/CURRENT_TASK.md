# Current Task

Task ID: V14D-001
Status: READY
Owner: Codex implementation / ChatGPT review

## Objective

Activate the validated V1.4C scoring model as the production scoring model (**V1.4D**) without running a Big Hunt or making provider calls. The model has completed calibration, holdout review, and prospective shadow validation; the latest prospective rerun produced numeric V1.3 economics for 5/5 frozen finalists and returned `READY_FOR_V14D`.

This task is code activation + tests + Git handoff only.

## Validated production model to activate

### Demand score families

- listing activity: 35%
- review activity: 30%
- search evidence: 20%
- breadth/freshness: 15%

### Competition attractiveness families

Higher score = more attractive / less difficult competition.

- comparable density: 30%
- review barrier: 25%
- market concentration: 15%
- DataForSEO Product Competitors: 20% when observed
- DataForSEO Ranked Keywords: 10% when observed

### Opportunity score

- demand: 30%
- competition attractiveness: 25%
- unchanged V1.3 economics: 35%
- risk attractiveness: 10%

### Evidence/confidence principles

- Missing/UNKNOWN/null/not-run/unsupported evidence must never improve a score.
- Missing component contribution uses the fixed denominator strategy already validated by V1.4C; do not redistribute missing weight favorably.
- Score and confidence remain separate.
- Do not multiply score by confidence.
- Duplicate ASINs must not inflate statistics.
- Null is not zero.

### Production eligibility/tier policy

Use the validated confidence policy:

- confidence >= 70: potentially `STRONG` / strong-eligible only if score threshold passes, risk is known, and economics support is adequate.
- confidence 55–69: maximum `VALIDATED`.
- confidence <55: maximum `PRELIMINARY_NEEDS_EVIDENCE` (or the closest existing production terminology without weakening the rule).
- UNKNOWN risk cannot become STRONG.
- Low-confidence PARTIAL economics cannot by itself create STRONG eligibility.
- Do not force a Top 10 or STRONG candidate when evidence does not support one.

## DataForSEO production role

Persist the experimentally validated role decisions:

- Amazon UAE Bulk Search Volume: `SUPPLEMENTAL_ONLY`; Arabic (`ar`) coverage is partial and must never represent total UAE demand.
- Amazon UAE English DataForSEO Labs coverage: `NOT_CONFIRMED`.
- Product Competitors: usable competition-intelligence signal when actually observed.
- Ranked Keywords: supplemental competition/keyword signal when actually observed.
- Missing DataForSEO evidence must reduce confidence / remain missing; it must never imply low competition.
- Scoring itself must not automatically trigger DataForSEO calls.

Correct stale documentation/rules that still state DataForSEO Amazon Labs is US/English-only for UAE. Runtime/POC evidence established UAE location 2784 with Amazon source for Arabic; English Amazon source remains unconfirmed.

## Instructions

1. Sync latest `main` safely and inspect current production scoring paths before editing.
2. Identify every production path that calculates or reports demand, competition, opportunity score, confidence, recommendation tier, and gating (including `score-products`, research pipeline/reporting, and any persisted normalized analysis fields).
3. Promote/reuse the validated V1.4C implementation rather than reimplementing equivalent arithmetic in multiple places. Keep one canonical production scoring path where practical.
4. Set production scoring version metadata to a clear V1.4D identifier so reports/evidence make the active model explicit.
5. Activate the exact validated formulas/weights above. Do not retune them in this task.
6. Preserve canonical V1.3 economics formulas unchanged. Production scoring consumes V1.3 economics; it does not fork economics logic.
7. Keep existing price, relevance, risk, freshness, marketplace, commercial-segment, and evidence-correctness protections unless a minimal adaptation is required to integrate V1.4D.
8. Preserve `MAX LANDED COST @25%` and economics confidence/status in production outputs when available.
9. Apply the confidence/tier policy consistently in production reports and persisted analysis.
10. Update configuration/docs/tests that still describe the previous six-component production score (Demand 30 / Competition 20 / Margin 20 / Price 10 / Risk 10 / Differentiation 10) as active. Historical/audit reports may retain historical values; do not rewrite old artifacts.
11. Update `AGENTS.md` and `README.md` where their production rules are stale, including DataForSEO UAE coverage/role wording and V1.4D scoring/tier rules.
12. Keep DataForSEO provider calls optional/gap-directed. V1.4D scoring must work deterministically with no DataForSEO evidence present and must not reward absence.
13. Maintain backward compatibility with existing evidence bundles where reasonable. If a legacy field cannot be removed safely, retain it but make the V1.4D canonical fields/version unambiguous.
14. Add a migration/adapter only if needed for persisted legacy analyses; do not silently mutate historical report files.
15. No discovery, prospective hunt, validation hunt, or Big Hunt in this task.
16. **All provider network calls are forbidden during implementation/tests:** SerpApi=0, DataForSEO=0, SP-API=0, other paid providers=0.
17. Run targeted scoring/report/pipeline tests and full `python3 -m pytest`.
18. Run an OFFLINE regression/backtest using existing fixtures/cached bundles only to prove:
    - old 86.25 demand saturation is not the active production behavior;
    - missing evidence does not improve score;
    - null != zero;
    - confidence/tier caps work;
    - V1.3 economics unchanged;
    - score arithmetic reconciles exactly.
19. Do not run paid/local live provider commands after implementation.

## Acceptance Criteria

- V1.4D is the single active production scoring model in normal research scoring/reporting paths.
- Demand, competition, opportunity weights exactly match the validated model.
- V1.3 economics formulas unchanged.
- Missing/unknown evidence never rewards attractiveness.
- DataForSEO Arabic search volume remains supplemental and capped/non-dominant; English Amazon Labs coverage remains NOT_CONFIRMED.
- Product Competitors/Ranked Keywords affect competition only when evidence is observed.
- Production scoring does not make provider calls.
- Confidence is separate from score.
- Tier caps/strong blockers are enforced.
- `MAX LANDED COST @25%` remains visible when economics is numeric.
- Production reports/evidence include scoring version `V1.4D` (or equivalent explicit identifier).
- Existing frozen V1.4C/V1.4C.2 audit code can remain for historical comparison, but it must not be the only place where the new model exists.
- Full tests pass.
- Provider calls during task = 0.

## Git Handoff

1. Create branch `codex/v14d-001` from latest `main`.
2. Implement and test there.
3. Commit all intended code/config/docs/test changes with a clear commit message.
4. Push `codex/v14d-001` to `origin`.
5. Do NOT merge to `main`.
6. Do NOT run a Big Hunt.

## Handoff Response

Return a concise engineering summary only:

- Task ID
- Production activation approach / canonical scoring path
- Files changed
- Exact active production weights
- Confidence/tier policy implemented
- DataForSEO role implemented
- Targeted tests + full-suite tests
- Offline regression result
- Provider calls (must be 0)
- Branch
- Commit SHA
- Any compatibility note
- Any blocker
