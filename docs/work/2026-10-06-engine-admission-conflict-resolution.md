---
ticket: OME-1163
stack: screamingface-engine
status: done
started: 2026-10-06
finished: 2026-10-06
---

# Engine provider admission — resolve conflicts and review PR #1152

## Intent

Reconcile Engine PR #1152 with current main after Gateway #1153 merged, preserving
both the Gateway internal-error classification and all admission timeout codes.
Review the complete Engine/client delta and determine whether further client work
is needed. Continue the existing OME-1163 scope; no duplicate ticket.

## Planned changes

- Rebase the two PR commits onto main at 8fbacd57971c1bcca65ad23ea505488976fe1b81.
- Resolve the Engine contract, client vocabulary and exact-vocabulary test by retaining
  both main's gateway_internal_error and this PR's four timeout codes.
- Record independent standards/spec reviews and Engine/client validation.

## Test plan

- Run full Engine and client SDK card gates against resolved head f6f2d504.
- Preserve the already documented approved test contract updates from the original PR;
  review the final test diff against main and retain every existing classification.
- Check client report deserialization/conformance and release ordering.

## Acceptance

No unresolved conflicts, both vocabularies agree, component checks pass and review
results plus any required client follow-up are reported to the user.

## Outcome

- **Actual files:** union resolutions in Engine contract, exact-vocabulary test and
  client report primitives; this ledger records the work.
- **Commits:** original commits rebased as 8036c206 and f6f2d504, plus the review ledger.
- **Gates:** complete Engine and client SDK card gates ALL GATES GREEN on Python 3.13.
  Both passed lint, formatting, Pyright and their complete default parallel suites with
  unchanged coverage floors (Engine 80%, SDK 95%). Engine layering and SDK notebooks,
  build and distribution checks passed. Notebook extra installed from the frozen lockfile.
  The previous full-SDK-suite stall did not reproduce in this run.
- **Reviews:** independent standards and spec reviews found no blocking defects;
  46 focused Engine admission/deadline/transport/report-classification tests also passed.
- **Client follow-up:** matching report vocabulary and conformance tests are already in
  this PR, so no separate compatibility code PR is required. Release that SDK before or
  alongside Engine; deploy Gateway first (its #1153 PR has merged). An optional separate
  enhancement could preserve the four timeout labels in notebook activity: the Engine
  activity projection currently normalizes them to internal_error, and the client has a
  matching activity allowlist. This does not affect report classification.
- **Deviations:** none beyond resolving vocabulary overlap. Append-only checks used the
  resolved rebased PR head, retaining the original documented test contract approvals.
  Final range-diff against the two original commits shows only main context changes and
  the preserved gateway_internal_error code. No paid calls or external review comments.

## CI status reconciliation

- The mirror-status check rejected the stale `Backlog` task mirror against this completed
  work ledger. Linear OME-1163 was verified as `In Review` on 2026-10-06.
- Updated only the task mirror's status to match Linear; the issue remains open for review.
- Validation: `python3 .claude/scripts/check_mirror_status.py` passed.
