---
ticket: OME-1020
stack: repo
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1020 — SDK reconnect state machine — resume runs from the stream cursor

## Intent

A Run survives an Engine restart: the SDK backs off (full jitter, 90 s budget), re-attaches
on a new socket with `attach(from_sequence = last accepted + 1)`, replays missed frames,
and returns the normal Report. The 60-second-forever `websocket_disconnected` of the
2026-08-26 incident becomes recoverable; only budget exhaustion or a typed
`stream_reclaimed` ends the Run.

## Planned changes

- `_engine/contract.py` — `stream_reclaimed` error frame raises
  `ExecutionError(code="run_result_lost", permanent=True)`; `last_sequence` property
- `_engine/run_lifecycle.py` — `resume_attach()`: cursor attach for a new socket
- `_engine/transport.py` (both twins) — `_run_reconnecting` loop: first connection attaches
  fresh + starts; reconnects resume, never re-start (topic single-shot); full-jitter
  backoff 0.5 s doubling to 15 s cap, 90 s cumulative budget (inside the reaper's 120 s
  grace); handshake 401/403 non-Access → FATAL (no probe, D5); budget exhausted →
  `cancel_active()` sweep then `websocket_disconnected`; `cancel_active` sets an abort
  flag so owner-aborted Runs stop reconnecting immediately
- test-only seams: `reconnect_budget_s`, `reconnect_base_delay_s` constructor params

## Test plan

- restart → resume from cursor 3 → completes (sync + async twins)
- reclaim-after-restart → `run_result_lost`, permanent
- persistent 1012 → reconnects (≥2 handshakes), sweeps on budget exhaustion
- OME-1017's fatal-1012 pin flipped deliberately
- existing interrupt test stays green (abort flag: workers exit the loop once swept)

## Acceptance

Full SDK suite green (1198 passed / 17 skipped); no test may spend the default 90 s
budget (disconnect-diagnosis tests use the 0.2 s seam).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (3 SDK source files + tests; disconnect-diagnosis tests
  got the 0.2 s budget seam so they keep testing DIAGNOSIS, not pacing).
- **Commits:** (added by commit step)
- **Gates:** SDK 1198 passed / 17 skipped; engine + url4 suites re-run at epic end
- **Deviations:** (1) the reconnect notice is a log line, not a widget event — the Event
  set is closed and versioned; a widget line would be a public API addition (out of
  scope, noted for a follow-up). (2) The abort-flag (`_aborted`) was added beyond the
  plan: without it, a SIGINT abort left worker threads reconnecting for the whole 90 s
  budget after the sweep had already stopped their Runs (found via
  `test_concurrent_interrupt_deletes_every_active_engine_capability`).
