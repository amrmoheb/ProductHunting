# ProductHunting — Persistent Project State

Updated: 2026-08-14 UAE (+04:00)

## Autonomous mode

- autonomous_mode: `ACTIVE`
- autonomous_run_id: `AUTO-001`
- entry_hunt: `BH-004`
- current_phase: `HUNT`
- current_hunt_id: `BH-004`
- next_hunt_id_if_needed: `BH-005`
- source_phase_id_if_needed: allocate sequentially as `SOURCE-002`, `SOURCE-003`, ...
- final_stop_reason: `NONE`
- supplier_ready_candidate: `NONE`

## Last completed commercial results

- `BH-001`: discarded all; storage/organization discovery bias identified
- `BH-002`: diversity fix succeeded; Fabric resistance bands was the only candidate with a realistic score-ceiling path
- `SOURCE-001`: Fabric resistance bands => `DISCARD`; no landed-cost value supported canonical STRONG
- `BH-003`: `NO_SOURCE_CANDIDATE`; 0 ceiling-eligible candidates; highest theoretical max was Radiator cleaning brush at 64.95

Do not reopen those decisions without materially new real evidence.

## Frozen production state

- production model: `V1.4D`
- economics model: `V1.3`
- STRONG score threshold: `65`
- STRONG confidence requirement: `>=70`
- target net margin: `25%`
- marketplace: `Amazon UAE / amazon.ae`
- marketplace ID: `A2VIGQ35RCS4UG`
- diversity allocator: `BH-002 deterministic allocation — frozen`

## Autonomous-run provider envelope

This is the total envelope for `AUTO-001` across all hunts/source phases:

- SerpApi live calls allowed total: `30`
- SerpApi live calls used in AUTO-001: `0`
- SerpApi live calls remaining: `30`
- SerpApi max cost envelope total: `USD 0.60`
- SerpApi recorded/estimated cost used in AUTO-001: `USD 0.00`
- DataForSEO calls allowed: `0`
- SP-API calls allowed: `0`

Historical calls from BH-001/BH-002/BH-003 are historical and do not increase this new envelope; however they must be reused from cache/fingerprints when still valid rather than repeated unnecessarily.

Never increase these limits without explicit user authorization recorded in the repository/current task.

## Autonomous-run hard limits

- maximum hunts this run: `4`
- hunts completed this run: `0`
- hunts remaining: `4`
- do not return to user after an ordinary failed hunt or SOURCE discard

## Current BH-004 discovery direction

BH-004 starts as a margin/headroom-oriented diversified hunt, without changing scoring:

- genuinely new segments, excluding exact prior evaluated segments
- favor plausible AED 80–150 products while retaining allowed AED 50–79 products
- compact/light/simple supplier specification
- low compliance/IP/fragility/return complexity
- avoid obvious race-to-bottom commodities where practical
- keep category/semantic diversity
- staged provider validation rather than spending the entire envelope blindly

## State update contract

After every completed HUNT or SOURCE phase, Codex must update this file with:

- current/next phase and ID
- hunts completed/remaining
- provider calls/cost used and remaining
- latest decision
- best surviving candidate if any
- stop reason if reached
- latest report paths

Do not reset counters when moving from one hunt to the next inside the same autonomous run.
