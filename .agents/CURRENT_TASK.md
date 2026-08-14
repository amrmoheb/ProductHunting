# Current Task

Task ID: V14D-001-R1
Status: REVIEW_FIX_REQUIRED
Owner: Codex implementation / ChatGPT review

## Context

V1.4D activation commit `77776f32dd8210e7c77d0967830ae82ae6633109` passed 295 tests and the core production-scoring integration looks correct. ChatGPT review found two stale production-reporting behaviors in `src/amazon_scout/research_report.py` that must be fixed before merge.

Do not redesign V1.4D. Do not retune any scoring/economics formula. Work on the existing branch `codex/v14d-001`.

## Review finding 1 — stale 20% economics arithmetic in a 35% V1.4D model

V1.4D opportunity weights are:

- demand 30%
- competition 25%
- V1.3 economics 35%
- risk 10%

However `_economics_section()` still calculates/displays the old 20% economics contribution, including logic equivalent to:

- `before = final_score - economics_raw * .20`
- displayed contribution = `economics_raw * .20`
- `required_economics_raw(...)` using its legacy default `weight=.20`
- `score_with_economics(...)` using its legacy default `weight=.20`

This makes the V1.4D report arithmetic misleading even though canonical scoring is 35% economics.

### Required fix

Use the canonical active V1.4D economics opportunity weight (35%) in report-only opportunity arithmetic. Prefer importing/reusing the canonical production weight rather than duplicating a magic `.35` if practical.

Do NOT change the V1.3 helper defaults in `economics_v13.py`; they are historical V1.3 helpers and V1.3 formulas must remain unchanged. Pass the active V1.4D weight explicitly where needed by the report.

The report must reconcile exactly with `score_breakdown` / V1.4D opportunity arithmetic.

## Review finding 2 — economics report is hard-coded to four historical candidates

`_economics_section()` currently filters analyses using a hard-coded set containing the old V1.3 candidates:

- long handle baseboard cleaning tool
- washable ceiling fan blade sleeve duster
- adjustable airplane foot hammock
- wood crochet blocking board

That is not valid for future production / Big Hunt reports. New candidates with legitimate numeric V1.3 economics can be omitted from the economics section.

### Required fix

Make economics reporting candidate-agnostic.

Include candidates from the supplied analyses when they have legitimate economics evidence to report (for example, an economics object with a numeric raw score and/or numeric BASE economics), rather than matching historical names.

Do not fabricate economics for candidates lacking it. Do not promote candidates or change selection/tiering. This is reporting only.

Keep the report bounded to the analyses already supplied to the renderer; do not perform discovery or provider calls.

## Regression requirements

Add focused tests proving:

1. A V1.4D economics raw score contributes at 35% in the rendered economics arithmetic, not 20%.
2. `required_economics_raw` / `score_with_economics` are invoked or represented with the V1.4D 35% opportunity weight while their V1.3 default behavior remains unchanged.
3. A new arbitrary candidate name with valid numeric economics appears in the economics section.
4. A candidate with insufficient/unknown economics is not fabricated into a numeric economics section.
5. Existing V1.3 formulas remain unchanged.
6. Full V1.4D score arithmetic still reconciles.
7. Provider calls = 0.

Run targeted tests plus full `python3 -m pytest`.

## Provider policy

No provider/network calls:
- SerpApi = 0
- DataForSEO = 0
- SP-API = 0
- other paid providers = 0

## Git handoff

Stay on `codex/v14d-001`.

Commit the review fixes and push the branch. Do not merge to `main`. Do not run Big Hunt.

## Handoff response

Return only:

- Task ID
- Root cause fixed
- Files changed
- Exact economics opportunity weight used in report
- Candidate-agnostic economics reporting confirmation
- Targeted tests / full tests
- Provider calls
- Branch
- New commit SHA
- Remaining blocker, if any
