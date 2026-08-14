# Current Task

Task ID: SETUP-001
Status: READY
Owner: Codex implementation / ChatGPT review

## Objective

Verify the ChatGPT ↔ Codex ↔ GitHub repository bridge works end-to-end without changing product logic.

## Instructions

1. Pull/sync the latest `main` safely.
2. Confirm `.agents/CHATGPT_CODEX_WORKFLOW.md` and this file are present.
3. Do not modify product/scoring/research code.
4. Run `python3 -m pytest`.
5. Report the test result.
6. Do not make any SerpApi, DataForSEO, SP-API, or other provider calls.
7. Do not expose `.env` or secrets.
8. No code commit is required for this verification task unless local sync itself requires one.

## Acceptance Criteria

- Repository sync succeeds.
- Shared workflow file is visible to Codex.
- Full test suite completes.
- Provider calls = 0.
- Product code changes = 0.

## Handoff

Return:
- task id
- tests passed/failed
- provider calls
- current branch
- current HEAD SHA
- any blocker
