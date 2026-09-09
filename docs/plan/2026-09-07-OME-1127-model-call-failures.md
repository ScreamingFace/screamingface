# OME-1127 — Proposed implementation sequence

Prerequisite: [failure policy spec](../spec/2026-09-07-OME-1127-model-call-failures.md).

1. Preserve the loopback disconnect checks as Engine regression tests. Add the empty-body classification test first; verify RED.
2. Add the minimal incomplete-response classification in runner/connector.py. Keep complete malformed-body behavior and existing status handling unchanged.
3. Obtain the live provider failure response shape. Add a failing regression for that exact shape before changing runner/model_response.py. Recognize status-bearing provider errors narrowly; retain permanent refusal and token-cap cases.
4. Reproduce COMMIT-stage failure against the actual MedXpert revision. Assert candidate stage for both candidate turns and grading only for checker failure; coordinate with OME-1126 rather than copying its unmerged implementation into main.
5. Extend the fake-gateway end-to-end harness with true incomplete HTTP framing and the verified live response shape. The harness lives under packages/screamingface; follow the repo's separate landing issue requirement if modifying that package.
6. Run Engine gates and the affected SDK e2e suite, including 429/5xx, malformed HTML, refusal, token cap, stage, spend and scoring checks. Review and submit through PR; do not close OME-1127 from a synthetic-only fix.

Completed investigation validation: 73 existing connector, finish-reason and grading-integrity tests passed. Loopback matrix fails on empty completed 200 retryability as intended. No production code changed.

## Implementation revision — 2026-09-09 (supersedes sequence above)

1. Add Engine-owned loopback fake-Gateway integration tests reaching CandidateResult; no SDK/package changes needed.
2. RED: zero-byte complete 200 must become retryable aigateway_empty_response; preserve HTML/whitespace/truncated complete JSON as permanent faults.
3. Minimal _json_or_raise guard, with no additional immediate retry.
4. Check actual framed disconnects for empty/partial delivery, candidate-stage failures in both turns, genuine checker-stage failure, 429/503, reasoning-only permanent model outcome, and retained successful-operation spend.
5. Run Engine quality gates, inspect diff, update ledger and submit PR. OME-1127 remains open for explicitly outstanding acceptance/ownership decisions, so PR references rather than auto-closes it.
