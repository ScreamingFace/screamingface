---
ticket: OME-1872
stack: screamingface-engine
status: done
started: 2026-11-11
finished: 2026-11-11
---

# candidate-call-retry — retry a Candidate model call when the gateway fails for a moment

## Intent

A Case's score must reflect the model's answer, never a short infrastructure failure. Today a
Candidate model call the AI gateway answers with 429 or 5xx is marked temporary, but nothing asks
it again, so the Case fails (paid run 2026-10-15: one Case lost on each of 2 Benchmarks). Judge
calls already get 2 re-asks. This unit makes the Engine's connector wait and ask a Candidate call
again, 2 times, before the failure stands.

Owner decisions (2026-11-11, design session on the ticket):

- Home: the connector, per call, inside one round trip (below the frozen-copy call key), only
  while `in_candidate_invocation()` is on. Not url4's guard (it would re-run a whole Fusion).
- 2 extra tries; waits ~10 s then ~30 s (+ jitter), raised to the gateway's `Retry-After`,
  capped at 120 s; a retry that does not fit the request deadline is not started.
- Candidate calls only: judges keep their own 2 re-asks (no 3 x 3 = 9).
- Statuses: 429 and every 5xx. A retry after a 5xx is marked possibly billed; after a 429 not.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/world/candidate_call_retry.py` (new): the
  policy — which statuses, how many tries, how long to wait.
- `apps/screamingface-engine/src/screamingface_engine/world/connector.py`: `_fetch_completion`
  posts through a new `_post_answered` loop; `_CaptureProbe` tracks "read a 2xx" instead of a
  response count, so a call that failed on every try is not `ambiguous`.
- `apps/screamingface-engine/tests/unit/test_candidate_call_retry.py` (new).

## Test plan

- Candidate call: 429 then 200 → answered, 2 identical requests (same body, same capture key).
- 502 then 200 → the outcome says possibly billed; 429 then 200 → it does not.
- 429 on every try → 3 requests, then the temporary failure (permanent false) as today.
- Judge call (no Candidate scope): 429 → 1 request, fails as today.
- Permanent 400 → 1 request.
- Waits: 10 s / 30 s schedule; Retry-After raises it; capped at 120 s; garbage ignored.
- Deadline: a retry that does not fit → no second request.
- Capture: 429 then 200 → `stored`, not ambiguous; 429 on every try → not ambiguous.
- Replay: a captured 429 → 1 request, no retry (a retry would read the same entry again).

## Acceptance

- A Candidate call that fails for a moment is answered; a failure that outlasts 2 retries still
  fails the Case as a temporary infrastructure failure.
- Judge, replay and every non-Candidate request is byte-identical to main.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `tests/integration/test_gateway_failure_report.py`: its 429
  and 503 rows pinned "a Candidate call is sent once", the exact behaviour this unit changes;
  now `CANDIDATE_CALL_RETRIES + 1` sends, waits stubbed (owner approved the prior-test edit,
  2026-11-11). Every other row and assertion is unchanged.
- **Commits:** the one commit on branch `OME-1872-candidate-call-retry`.
- **Gates:** relevant tests only (owner rule): `test_candidate_call_retry.py` 30 passed; the 109
  test files that import the connector or the frozen-copy support, 1299 passed + 9 skipped
  (the inspect files among them, 100 passed with the `inspect` extra); 6 more files that script a
  429/5xx, 156 passed. Mutation checks: dropping the Candidate-only gate, the possibly-billed
  mark, or the deadline check each turns a new test red. ruff + format + pyright clean on the
  touched files.
- **Deviations:** `_CaptureProbe` now tracks "a 2xx was read" instead of a response count. The
  old count made a capture call that failed on every retry `ambiguous`, though the copy holds only
  errors and replay serves the last one. Equivalent for every pre-existing path (a second response
  only ever followed a 2xx).
- **Owner-verify:** none paid; the next long leaderboard run shows the retry warnings in the
  runtime log (`candidate model call temporary gateway failure`).
