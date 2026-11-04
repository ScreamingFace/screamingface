---
ticket: OME-1813
stack: screamingface-engine
status: done
started: 2026-11-03
finished: 2026-11-03
---

# ws-nack-tests-tolerate-heartbeat — the websocket nack tests stop racing the heartbeat

## Intent

Three tests in `tests/unit/test_ws.py` open a websocket with a 50 ms heartbeat, send one bad
inbound frame, and assert that the *first* frame back is the error reply (the "nack"). The
bridge writes from one queue: the inbound task parses the frame and queues the nack, while the
writer sends a heartbeat whenever that queue has been idle for 50 ms. On a slow CI runner the
heartbeat wins, the first frame is `ai.url4.heartbeat`, and the test fails although the bridge
did exactly what it should. It failed that way on #1631's CI on 2026-11-03 (job 125711669203:
`assert 'ai.url4.heartbeat' == 'ai.url4.error'`, log line `frames=1 heartbeats=1`), and passed on
the rerun of the same commit. The tests should assert the contract (a nack arrives, the stream
survives), not the ordering of an unrelated liveness frame.

## Planned changes

- `apps/screamingface-engine/tests/unit/test_ws.py`: one helper that reads frames until the
  first frame that is not a heartbeat (bounded); the three nack tests read their nack through
  it. Assertions unchanged.
- `.claude/test-change-approvals/OME-1813.json`: pins the edit to the existing tests.
- One new test pins the CI ordering: the socket hands the bridge the bad frame only after the
  heartbeat has gone out, and the nack is still found.

## Test plan

- Reproduce first: with the socket's inbound delivery delayed past the heartbeat (0.12 s against
  50 ms, the ordering CI produced) the three tests on `main` fail with CI's exact message; with
  the helper they pass after skipping two heartbeats each.
- With the fix at the real 50 ms: the whole `test_ws.py` file passes, 20 runs in a row.

## Acceptance

- The three nack tests pass whether a heartbeat lands before or after the nack; a missing nack
  still fails (the helper gives up after a bounded number of heartbeats).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the new pinning test in the same file, this ledger and the
  `docs/tasks` mirror.
- **Commits:** see the PR.
- **Gates:** `tests/unit/test_ws.py` 15 passed (14 prior + 1 new); the three nack tests 20 runs
  in a row, 0 failures; ruff check, ruff format and pyright clean on the file. On `main`'s
  version with the inbound delivery delayed: 3 failed, `assert 'ai.url4.heartbeat' ==
  'ai.url4.error'`; same delay on the fixed file: 3 passed, 2 heartbeats skipped before each nack.
- **Deviations:** forcing `ws_heartbeat_s=0.0` was the first reproduction attempt; it floods the
  socket with heartbeats faster than the inbound task runs, so the fixed tests then fail on the
  20-heartbeat bound. That is the bound working, not the race, so the delayed-delivery
  reproduction replaced it. Bridge code untouched.
