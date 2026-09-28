---
ticket: OME-1197
stack: screamingface
status: done
started: 2026-09-24
finished: 2026-09-24
---
# OME-1197 — Refresh corrected IFEval failure attribution

## Intent
Reconcile the replay expectation with explicit model-call origin in draft #1060.

## Planned changes
Refresh only IFEval case 1069's failure stage from grading to candidate using the guarded committed-snapshot replay tool. Owner explicitly approved the fixture migration.

## Test plan
CI reproduces the failure-code mismatch. Run guarded refresh and IFEval replay; inspect the diff for unchanged expression, statuses, counts and score.

## Acceptance
Only the intended attribution changes; replay passes. Push to existing draft, no merge or new ticket.

## Outcome
Guarded refresh passed: only case 1069 stage changes from grading to candidate; score 0.9184, expression, statuses and counters unchanged. Real IFEval replay passed. git diff --check passed. No production code changed; existing URL4 and Engine gates passed in the preceding iteration. Initial replay invocations skipped until prepared-assets path and opt-in were explicitly supplied; skipped runs were not counted as validation. Commit: test(client): refresh IFEval model-call failure attribution.
