---
ticket: OME-1507
stack: screamingface
status: done
started: 2026-10-07
finished: 2026-10-07
---

# retry-after-test-flake — the Retry-After HTTP-date tests stop failing at random

## Intent

Two tests in `packages/screamingface/tests/test_transient_retry.py` fake a server that says
"retry at now + 5s" as an HTTP-date and expect a 5 ± 1s wait. An HTTP-date drops fractions of a
second, so the parsed wait could be 3.9996s and fail. It failed CI on #1258 and #1268 on
2026-10-06. Test-only fix: build the retry time from now rounded down plus 6s.

## Planned changes

- `packages/screamingface/tests/test_transient_retry.py`: a `_retry_at_in_whole_seconds()` helper,
  used by `test_retry_after_http_date_is_honoured` and
  `test_retry_after_naive_http_date_is_treated_as_utc`.
- `.claude/test-change-approvals/OME-1507.json`: pins that prior-test edit.

## Test plan

- The two tests, 15 repeated parallel runs: all pass.
- `run_gates.py screamingface --base <merge-base>` green, no skip flag.

## Acceptance

- The two tests' wait lands in (5, 6] minus the SDK's own run time; the 4–6s window holds unless
  a run stalls a full second.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** `test(screamingface): stop the Retry-After HTTP-date tests flaking under 4 seconds`,
  plus the docs commit.
- **Gates:** `run_gates.py screamingface --base <merge-base>` green (see PR).
- **Deviations:** none.
