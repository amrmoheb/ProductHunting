# ProductHunting — Autonomous Hunt Loop

## Purpose

This protocol lets Codex operate as planner + executor + reviewer in one continuous session instead of returning to the user after every hunt or SOURCE task.

The loop starts from the entry hunt recorded in `.agents/PROJECT_STATE.md` and continues until a hard stop is reached.

Do **not** return to the user between normal hunt/source iterations.

## Startup sequence

On `sync and execute current task`:

1. Protect uncommitted user work. Never discard it.
2. Sync the repository safely when possible.
3. Read completely:
   - `AGENTS.md`
   - `.agents/AGENT_MISSION.md`
   - `.agents/AUTONOMOUS_HUNT_LOOP.md`
   - `.agents/PROJECT_STATE.md`
   - `.agents/DECISION_HISTORY.md`
   - `.agents/CURRENT_TASK.md`
4. Read only the production files/tests/reports needed for the current phase.
5. Run task-relevant offline tests before provider calls.
6. Continue autonomously until a hard stop below is reached.

## Persistent operating state

After each completed HUNT or SOURCE phase:

- update `.agents/PROJECT_STATE.md`
- append a concise entry to `.agents/DECISION_HISTORY.md`
- write the normal timestamped report(s) under `reports/`
- preserve enough state that a new Codex session can resume without asking the user to reconstruct history

Use a dedicated working branch such as `codex/autonomous-product-hunt` when repository changes/checkpoints are needed. Do not rewrite shared history. Do not merge to `main` automatically.

## Phase state machine

### HUNT phase

Goal: find a product with a realistic mathematical and evidence path to supplier validation.

For each hunt:

1. Build a genuinely new diversified discovery manifest.
2. Exclude exact previously evaluated commercial segments using prior reports and `.agents/DECISION_HISTORY.md`.
3. Do not evade that exclusion by renaming the same product.
4. Keep canonical BH-002 diversity allocation unchanged.
5. Prefer discovery capacity toward:
   - plausible AED 80–150 selling-price headroom, while still allowing AED 50–79
   - compact/light/simple products
   - low compliance/IP/return complexity
   - private-label-friendly specifications
   - less obvious race-to-bottom commodity structures
6. Cheap-screen offline before provider spending.
7. Use staged Amazon UAE validation, not one blind full-budget batch.
8. Score with frozen V1.4D/V1.3.
9. For each sufficiently evidenced validated candidate run early triage:
   - theoretical V1.4D ceiling with economics raw = 100
   - confidence path to >=70
   - known/non-blocking risk path
10. Reject immediately when:
   - theoretical max score <65 => `NO_PATH_TO_STRONG`
   - confidence has no credible path to >=70 => `NO_CONFIDENCE_PATH`
   - risk/compliance/IP classification blocks sourcing
11. Deep-evaluate only candidates that survive those gates.
12. For survivors, calculate current economics, `MAX LANDED COST @25%`, economics raw needed for score 65, and landed-cost sensitivity.

If no candidate has a real path to STRONG, close that hunt as `NO_SOURCE_CANDIDATE`, record why, adapt **discovery strategy only**, and continue to the next hunt if hard-stop limits permit.

### Failure review between hunts

Do not tune the engine. Classify why the hunt failed, using one or more of:
- `DISCOVERY_WEAK`
- `AMAZON_RELEVANCE_WEAK`
- `DEMAND_WEAK`
- `COMPETITION_TOO_HARD`
- `CONFIDENCE_TOO_LOW`
- `RISK_BLOCKED`
- `ECONOMICS_HEADROOM_WEAK`
- `NO_PATH_TO_STRONG`
- `PROVIDER_BUDGET_LIMITED`

Use that diagnosis only to alter the next hunt's discovery universe, seed mix, category emphasis, validation ordering, or provider-call allocation. Never alter V1.4D/V1.3 weights, thresholds, confidence math, or missing-data rules.

Increment hunt IDs monotonically: `BH-004`, `BH-005`, `BH-006`, ...

### SOURCE phase

When a hunt finds one best candidate with a realistic path to STRONG, do **not** return to the user yet.

Immediately enter a SOURCE phase inside the same autonomous session.

Lock the exact commercial segment and use the completed hunt artifact. Do not regenerate market evidence unless a specific allowed evidence gap truly requires it.

Run offline landed-cost sensitivity using canonical V1.3/V1.4D:
- actual landed cost grid from a low realistic value up to `MAX LANDED COST @25%`
- refine the STRONG boundary to about AED 0.10 where practical
- at each useful boundary calculate actual net margin, economics raw/status/confidence, V1.4D score, and tier

Find the **highest actual landed cost that still satisfies all canonical STRONG requirements**.

Then calculate the corresponding supplier product-cost target using the existing freight/customs/prep assumptions only.

SOURCE outcomes:

- `SUPPLIER_READY`:
  a real nontrivial landed-cost range supports STRONG and the supplier target is calculable.
- `SOURCE_DISCARD`:
  no actual landed-cost value can make the candidate STRONG, or another locked gate blocks it.
- `SOURCE_BLOCKED`:
  a required local artifact/calculation is genuinely unavailable.

If `SOURCE_DISCARD`, record the decision and resume the next HUNT automatically if limits permit.

If `SUPPLIER_READY`, stop and return to the user.

## Provider budget — entire autonomous run

The following is a **total envelope for the complete autonomous run**, not a fresh allowance per hunt:

- SerpApi live calls: maximum **30 total**
- SerpApi maximum recorded/estimated cost: **USD 0.60 total**
- DataForSEO: **0 calls**
- SP-API: **0 calls**

Use fresh cache/fingerprints first.

Do not mechanically spend 30 calls in the first hunt. Stage validation in small batches (for example 6–10 candidates), perform ceiling/confidence triage, then decide whether the next call is better spent expanding the same hunt or opening a materially different hunt.

Every Amazon provider request must explicitly target `amazon_domain=amazon.ae`.

Targeted zero-key/public Codex web research is allowed only for a narrow authoritative UAE risk/regulatory evidence gap on an otherwise promising candidate. It must never substitute for Amazon UAE demand evidence.

## Autonomous-run limits

Hard limits:
- maximum hunts in one autonomous run: **4**
- maximum SerpApi live calls in the entire run: **30**
- maximum SerpApi cost envelope in the entire run: **USD 0.60**
- DataForSEO: 0
- SP-API: 0

The agent may stop earlier when further iterations are unlikely to improve the decision with the remaining evidence/budget.

## Hard-stop conditions

Stop and return to the user only when one of these occurs:

### 1. `SUPPLIER_READY`
Return the single best product and sourcing thresholds/checklist.

### 2. `AUTONOMOUS_BUDGET_EXHAUSTED`
No supplier-ready candidate was found and another meaningful Amazon validation step would exceed the total provider envelope.

### 3. `MAX_HUNTS_REACHED`
Four hunts have been completed in this autonomous run without a supplier-ready candidate.

### 4. `BLOCKED`
A genuine blocker prevents correct execution, such as missing required local artifact, failing canonical tests that cannot safely be repaired, corrupted state, or security/credential exposure risk.

### 5. `NO_NEW_SEARCH_SPACE`
The system cannot create materially new valid segments without merely recycling prior evaluated products.

Do not stop merely because one hunt or one SOURCE candidate failed.

## Final response rules

Do not dump intermediate logs.

Return one compact final summary containing:
- autonomous run ID
- hunts completed
- provider calls/cost used across the whole run
- final stop reason
- if supplier-ready: exact product, score/confidence/tier, Amazon UAE price basis, `MAX LANDED COST @25%`, highest landed cost supporting STRONG, supplier product-cost target, remaining assumptions, supplier quote checklist
- if no winner: strongest candidate encountered, why it failed, and why the hard stop was reached
- reports/state paths
- branch/commit if repository checkpoints were created

No fake winner. A clean no-product result is valid.
