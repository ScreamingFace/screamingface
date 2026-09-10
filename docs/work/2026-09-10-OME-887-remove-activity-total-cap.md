---
ticket: OME-887
stack: repo
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-887 — Remove the lifetime activity record cap

## Intent

Owner requested removal of the proposed 20,000-record per-run emission cutoff from PR #885. Long evaluations should remain eligible to emit activity throughout execution; a total cutoff can be reconsidered if evidence warrants it.

## Planned changes

- Update the activity spec to remove the total cap and run_limit suppression field while retaining rate, size, bridge and Client retention bounds.
- Update the implementation plan and task mirror to match.

## Test plan

Review the documentation diff, search for stale total-cap references, and run git diff --check. No product code changes or runtime tests are required.

## Acceptance

The proposed contract has no lifetime emitted-record maximum or run_limit counter; the plan tests continued admission after more than 20,000 records within rate limits.

## Outcome

- **Actual files:** spec, plan, task mirror and this ledger.
- **Commits:** docs: remove lifetime activity record cap; Refs: OME-887.
- **Gates:** documentation diff reviewed; stale cap/counter search and git diff --check passed. No runtime tests needed for this docs-only refinement.
- **Deviations:** none. Issue remains open for delivery; this approves only removal of the lifetime cap.
