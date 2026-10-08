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
2026-10-06. First cut (test-only): build the retry time from now rounded down plus 6s, which
leaves 1s of headroom but still reads the wall clock twice. Review finding on the PR: make it
deterministic instead — give the parser a clock seam (`now=`) so the test and the SDK read
ONE clock, and assert an exact wait. The same seam fixes the third test of this shape,
`test_an_http_date_retry_after_is_obeyed` in `test_admission_retry.py` (now + 10s, 8–10 window).

## Planned changes

- `packages/screamingface/src/screamingface/_core/retry.py`: `_utc_now()` as the default clock;
  `_retry_after_seconds(response, *, now=)`; `_RetryPlan`, `RetryingTransport` and
  `RetryingAsyncTransport` take `now=` beside `sleep=` / `jitter=`. Defaults unchanged.
- `packages/screamingface/src/screamingface/_engine/admission.py`: `_AdmissionWait.wall_clock`
  (default `_utc_now`), handed to the parser.
- `packages/screamingface/tests/test_transient_retry.py`: `_rig(now=)`; the two HTTP-date tests
  build the header from a fixed clock and assert exactly `[5.0]`; a test pins the default clock.
- `packages/screamingface/tests/test_admission_retry.py`: `_policy(wall_clock=)`; the HTTP-date
  test asserts exactly `10.0`.
- `.claude/test-change-approvals/OME-1507.json`: pins both prior-test edits.

## Test plan

- RED: the three HTTP-date tests fail on the pushed head (no `now=` seam yet).
- GREEN: the three tests assert exact waits (`[5.0]`, `[5.0]`, `10.0`) with no tolerance.
- `run_gates.py screamingface --base <merge-base>` green, no skip flag.

## Acceptance

- The three HTTP-date tests no longer read the wall clock at all: the header and the parser
  share one injected clock, so the asserted wait is exact and timing cannot move it.
- Production behaviour unchanged: every default is still real UTC wall time.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `test_the_default_wall_clock_is_real_utc_time` in
  `test_admission_retry.py` (pins `_AdmissionWait`'s default clock, the twin of the transport pin).
- **Commits:** `test(screamingface): stop the Retry-After HTTP-date tests flaking under 4 seconds`
  (first cut, rounded-down now + 6s), the docs commit, then
  `fix(screamingface): measure an HTTP-date Retry-After against an injectable clock` (the seam).
- **Gates:** `run_gates.py screamingface --base 4d81004e` ALL GATES GREEN, no skip flag; both
  prior-test transitions approved via `.claude/test-change-approvals/OME-1507.json`.
- **Checks:** mutation — with the parser reading `datetime.now(UTC)` instead of the injected
  clock, all three HTTP-date tests fail (`0.5 == 10.0`, the backoff fallback); restored, 72/72 pass.
- **Deviations:** scope grew from "test-only" to a private seam in `_core/retry.py` and
  `_engine/admission.py` (review finding on the PR, owner-approved). Defaults unchanged, so no
  production behaviour moves; the public surface snapshot is untouched.
