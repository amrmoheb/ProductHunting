# Current Task

Task ID: `AUTO-001`
Mode: `AUTONOMOUS`
Status: `READY`
Entry phase: `BH-004`
Owner: `Codex autonomous planner/executor/reviewer`

## Objective

Start at BH-004 and continue the ProductHunting commercial loop **inside the same Codex session** until either:

1. one product becomes genuinely `SUPPLIER_READY`, or
2. an explicit hard-stop condition in `.agents/AUTONOMOUS_HUNT_LOOP.md` is reached.

Do not return to the user between ordinary HUNT/SOURCE phases.

The user should not need to relay summaries to ChatGPT and then bring a new prompt back to Codex.

## Required reading before execution

Read completely:

1. `AGENTS.md`
2. `.agents/AGENT_MISSION.md`
3. `.agents/AUTONOMOUS_HUNT_LOOP.md`
4. `.agents/PROJECT_STATE.md`
5. `.agents/DECISION_HISTORY.md`
6. relevant production files/tests/reports only as needed

Those files are the durable operating context for this autonomous run.

## Start with BH-004

BH-004 is a new margin/headroom-oriented diversified Amazon UAE hunt.

Do not reopen BH-001/BH-002/SOURCE-001/BH-003 decisions unless materially new real evidence exists.

Discovery priorities, without changing scoring:
- Amazon UAE only
- allowed selling-price band AED 50–150
- prefer roughly AED 80–150 when otherwise comparable
- compact/light/simple supplier specification
- low compliance, IP, fragility, breakage and return complexity
- avoid obvious race-to-bottom commodity structures where practical
- preserve BH-002 deterministic category/semantic diversity
- exclude exact previously evaluated commercial segments

## Early commercial triage

Before deep research, reject candidates that cannot realistically satisfy the existing engine:

- theoretical V1.4D max with economics raw = 100 is <65 => `NO_PATH_TO_STRONG`
- confidence has no credible path to >=70 => `NO_CONFIDENCE_PATH`
- risk/compliance/IP gate blocks sourcing

Do not modify V1.4D/V1.3/confidence/risk math to improve results.

Deep-evaluate only candidates surviving the above.

## Same-session SOURCE transition

If a HUNT produces a best candidate with a realistic path to STRONG, immediately run the SOURCE analysis in the same Codex session.

Determine:
- exact commercial segment
- current `MAX LANDED COST @25%`
- highest actual landed cost still satisfying all canonical STRONG requirements
- corresponding supplier product-cost target under current freight/customs/prep assumptions

If SOURCE says `SOURCE_DISCARD`, record it and continue the next HUNT automatically when run limits/budget permit.

If SOURCE says `SUPPLIER_READY`, stop and return the commercial package to the user.

## Total autonomous-run limits

These are shared across the entire `AUTO-001` run, not refreshed per hunt:

- maximum HUNT phases: `4`
- SerpApi live calls: `30 total`
- SerpApi cost envelope: `USD 0.60 total`
- DataForSEO: `0`
- SP-API: `0`

Use cache/fingerprints first.

Stage provider validation in small batches and run score-ceiling/confidence triage before spending additional calls. Do not blindly consume the entire budget in BH-004 if a different next hunt would make better use of remaining calls.

Never increase the provider envelope without explicit user authorization.

## Persistence

After each completed HUNT or SOURCE phase:

- write the normal report(s)
- update `.agents/PROJECT_STATE.md`
- append `.agents/DECISION_HISTORY.md`
- update provider counters cumulatively
- preserve current/next phase so another Codex session can resume if interrupted

Use a dedicated branch such as `codex/autonomous-product-hunt` for checkpoint commits when useful. Do not merge to `main` automatically.

## Stop conditions

Return to the user only for:

- `SUPPLIER_READY`
- `AUTONOMOUS_BUDGET_EXHAUSTED`
- `MAX_HUNTS_REACHED`
- `BLOCKED`
- `NO_NEW_SEARCH_SPACE`

A single failed hunt or discarded SOURCE candidate is **not** a stop condition.

## Final response

Return only a concise end-of-run decision.

If `SUPPLIER_READY`, include:
- autonomous run ID
- hunts completed
- exact product/configuration
- representative Amazon UAE ASINs
- current comparable price basis/band
- V1.4D score / confidence / tier
- `MAX LANDED COST @25%`
- highest landed cost supporting STRONG
- supplier product-cost target
- remaining estimated assumptions
- supplier quote checklist
- provider calls/cost used across the whole run
- report/state paths
- branch/commit if checkpoints were pushed

If stopped without a product, include:
- autonomous run ID
- hunts completed
- hard-stop reason
- provider calls/cost used across the whole run
- strongest candidate encountered and why it failed
- report/state paths
- branch/commit if checkpoints were pushed

Do not fabricate a winner.
