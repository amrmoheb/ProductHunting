# Current Task

Task ID: ECON-001
Status: READY
Owner: Codex implementation / ChatGPT review

## Objective

Resolve the **only remaining V1.4C.2 activation blocker**: the prospective shadow validation reported `economics validated = 0` for the five frozen finalists. Verify whether the latest code already contains the intended V1.3 economics enrichment; fix only what is still missing, then rerun the economics/shadow validation **without any new provider network calls**.

Frozen prospective bundle:

`research/normalized/2026-08-14-045804-v1.4c2-prospective-evidence-bundle.json`

Frozen finalists must remain exactly:

1. watch organizer box with drawer
2. three-slot travel watch roll
3. adjustable under-sink shelf around pipes
4. cabinet pull-out storage basket
5. two-tier under-sink pull-out organizer

Previous shadow report:

`reports/2026-08-14-045952-v1.4c2-prospective-shadow-validation.md`

Previous result:
- DataForSEO validation worked.
- Demand saturation fixed.
- Competition direction correct.
- Sensitivity stable.
- All five economics were `UNKNOWN (INSUFFICIENT)`.
- `economics validated = 0`.
- Activation recommendation: `NEEDS_MINOR_CALIBRATION` only because economics was not testable.

## Instructions

1. Sync latest `main` safely and inspect the current implementation **before editing**. The latest code may already include partial economics fixes; do not duplicate them.
2. Trace the same frozen bundle through `prospective_shadow_v14c2` and the canonical `economics_v13` implementation.
3. Reuse the existing V1.3 economics calculator. **Do not create a new economics formula.**
4. Do not change frozen V1.4C demand, competition, opportunity weights, gates, tiers, or V1.3 formulas.
5. Do not change the frozen shortlist.
6. Use already collected bundle evidence. Estimated physical profiles are allowed only under the existing V1.3 policy and must remain explicitly `ESTIMATED`/`PARTIAL`; never relabel estimates as observed.
7. For each finalist, attempt to persist/report:
   - selling-price basis
   - referral fee
   - FBA/fulfilment estimate
   - storage
   - VAT treatment
   - ads/returns/inbound/prep/freight/customs assumptions
   - economics raw score
   - economics confidence/status
   - max landed cost @25%
   - supplier product cost target
8. If evidence is genuinely insufficient, keep it insufficient; never fabricate inputs.
9. Fix the funnel-report inconsistency if still present: collector produced `Cheap-screened: 64` but old shadow report said `screened 0`. Reporting fix only; selection must not change.
10. **Provider network calls are forbidden for this task:**
    - SerpApi = 0
    - DataForSEO = 0
    - SP-API = 0
    - any paid provider = 0
11. Existing cached DataForSEO evidence may be reused only if it can be read locally without network access. If the current runner cannot rerun without network, add a narrowly scoped cache-only/offline path rather than contacting the provider.
12. Run `python3 -m pytest` plus targeted tests.
13. Produce an updated offline validation report using the same frozen shortlist if possible.
14. Do not activate V1.4D in this task. Only report whether the updated validation would now satisfy the existing activation checks.

## Acceptance Criteria

- Same five frozen finalists.
- V1.3 formulas unchanged.
- V1.4C formulas/weights unchanged.
- No provider network calls.
- Numeric V1.3 economics produced for at least 3/5 finalists if the existing evidence/approved estimated profiles legitimately support it; otherwise explain the exact blocker.
- Estimated inputs stay explicitly estimated/partial.
- Max landed cost @25% is persisted when numeric economics is valid.
- Funnel reporting is consistent with the frozen bundle.
- Full tests pass.
- Production scoring remains unchanged.

## Git Handoff

If code changes are required:

1. Create branch `codex/econ-001` from latest `main`.
2. Implement/test there.
3. Commit with a clear message.
4. Push the branch to `origin`.
5. Do not merge to `main`.

If no code change is required, do not create a pointless commit; just run the offline validation and report the result.

## Handoff Response

Return only the concise engineering summary:

- Task ID
- Root cause / whether latest code already contained the fix
- Numeric economics count out of 5
- Updated activation recommendation (`READY_FOR_V14D`, `NEEDS_MINOR_CALIBRATION`, or `NOT_READY`)
- Tests
- Provider calls (must be 0)
- Files changed
- Branch
- Commit SHA if any
- Updated report path
- Any remaining blocker
