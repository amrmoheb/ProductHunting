# ChatGPT ↔ Codex Repository Bridge

This repository uses GitHub as the shared bridge between ChatGPT (planner/reviewer) and Codex (local implementer/test runner).

## Codex trigger

When the user says **"sync and execute current task"** (or equivalent):

1. Ensure the working tree is safe. Do not discard uncommitted user work.
2. Fetch/pull the latest repository state from `origin` when safe.
3. Read `.agents/CURRENT_TASK.md` completely.
4. Read and obey root `AGENTS.md` and all repository safety/cost rules.
5. Implement only the current task and its acceptance criteria.
6. Never expose or commit `.env`, API keys, Authorization headers, credentials, or secret cache material.
7. Do not make paid/provider calls unless the current task explicitly authorizes them and states explicit task/cost ceilings.
8. Run the repository test suite (`python3 -m pytest`) and any targeted tests needed.
9. Prefer a dedicated branch named `codex/<task-id>` when the task requests code changes. Do not rewrite shared history.
10. Commit and push the completed changes when the task explicitly asks for a GitHub handoff.
11. Final Codex response must include:
   - task id
   - files changed
   - tests/result
   - provider calls/cost, if any
   - branch
   - commit SHA
   - any blocker or unresolved risk

## Review loop

ChatGPT reviews the pushed branch/commit/PR through GitHub. If fixes are needed, ChatGPT updates `.agents/CURRENT_TASK.md`; Codex then repeats the same trigger. The user should not need to copy long prompts between ChatGPT and Codex.

## Source of truth

- Task instructions: `.agents/CURRENT_TASK.md`
- Repository rules: `AGENTS.md`
- Code/results: Git repository
- Secrets: local environment only
