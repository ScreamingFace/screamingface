---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo
status: in_progress
started: 2026-11-21
finished:
---

# url4-peer-paid-execution — at-most-once paid execution for C6, as its own spec

## Intent

Split §5.9 out of the node-to-node auth spec (#1647, OME-1599) in its seventh review round (owner
decision, 2026-11-21), so authentication can be approved on its own and the at-most-once paid
execution design gets its own ticket and review. C6 stays refused until this spec is approved.

## Planned changes

- `docs/spec/2026-11-21-url4-peer-paid-execution.md`: §5.9 and its tests as of #1647 round six
  (8877e38b8), plus HupBaHa's round-seven findings as the open list.

## Test plan

- Spec only; the tests are written into §3 of the spec. Golden vectors were recomputed and verified by
  the reviewer on #1647.

## Acceptance

- The spec is approved by the url4 owner and HupBaHa; the round-seven findings are resolved in it.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the spec and this ledger (spec skeleton carried over; round-seven items open)
- **Commits:** see branch `url4-peer-paid-execution`
- **Gates:** pre-commit hooks
- **Deviations:** none so far
