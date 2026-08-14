# ChatGPT ↔ Codex Repository Bridge

GitHub is the durable bridge for this project, but Codex can now operate autonomously across multiple hunt/source phases in one session.

## Codex trigger

When the user says:

`sync and execute current task`

Codex must:

1. Protect uncommitted user work. Never discard it.
2. Sync the latest repository state from `origin` when safe.
3. Read completely, in this order:
   - root `AGENTS.md`
   - `.agents/AGENT_MISSION.md`
   - `.agents/AUTONOMOUS_HUNT_LOOP.md`
   - `.agents/PROJECT_STATE.md`
   - `.agents/DECISION_HISTORY.md`
   - `.agents/CURRENT_TASK.md`
4. Follow the mode declared by `CURRENT_TASK.md`.
5. Never expose or commit `.env`, API keys, credentials, cookies, Authorization headers, or secret cache material.
6. Never make provider/paid calls beyond the explicit total envelope in `PROJECT_STATE.md` / `AUTONOMOUS_HUNT_LOOP.md`.
7. Run task-relevant tests before provider calls.
8. Use canonical production code/config as the scoring truth; do not manually overwrite scores.

## Autonomous mode

When `CURRENT_TASK.md` declares `Mode: AUTONOMOUS`:

- Codex is planner + executor + reviewer for the duration of the run.
- Do **not** return to the user after an ordinary completed HUNT.
- Do **not** return to the user after an ordinary SOURCE discard.
- Review the result internally using the frozen business/model rules.
- Update `.agents/PROJECT_STATE.md` and append `.agents/DECISION_HISTORY.md` after each completed phase.
- Transition automatically to the next HUNT or SOURCE phase according to `.agents/AUTONOMOUS_HUNT_LOOP.md`.
- Continue until an explicit hard-stop condition is reached.

Normal autonomous sequence:

`HUNT -> review -> (next HUNT | SOURCE) -> review -> ... -> hard stop`

The user must not act as a message relay between phases.

### Autonomous hard-stop response

Only return when one of these is reached:
- `SUPPLIER_READY`
- `AUTONOMOUS_BUDGET_EXHAUSTED`
- `MAX_HUNTS_REACHED`
- `BLOCKED`
- `NO_NEW_SEARCH_SPACE`

The final response should be compact and commercial, not a dump of internal logs.

## Persistence / checkpointing

Use a dedicated branch such as `codex/autonomous-product-hunt` if state/code changes need commits.

After each completed phase, persist enough local/repository state that a later Codex session can continue safely:
- state counters
- provider spend/calls
- decision outcome
- exact segments rejected
- report paths
- current/next phase

Checkpoint commits/pushes are allowed when useful. Do not merge to `main` automatically and do not rewrite shared history.

## Legacy single-task mode

If `CURRENT_TASK.md` explicitly declares `Mode: SINGLE_TASK`, execute only that task and return the normal short handoff summary.

## Source of truth

- Business/behavioral mission: `.agents/AGENT_MISSION.md`
- Autonomous state machine: `.agents/AUTONOMOUS_HUNT_LOOP.md`
- Persistent current state/budgets: `.agents/PROJECT_STATE.md`
- Closed decisions/history: `.agents/DECISION_HISTORY.md`
- Entry instruction: `.agents/CURRENT_TASK.md`
- Repository safety/model rules: `AGENTS.md`
- Code/results: Git repository + completed reports
- Secrets: local environment only
