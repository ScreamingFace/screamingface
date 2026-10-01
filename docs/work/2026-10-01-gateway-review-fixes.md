---
ticket: OME-1162
stack: aigateway
status: done
started: 2026-10-01
finished: 2026-10-01
---

# gateway-review-fixes

## Intent

Fix both findings in Sergey's review of PR #1153: expected disconnects must not
produce ASGI ERROR tracebacks, and operators need a Helm queue-timeout setting.

## Planned changes

- `core/admission.py`: identify the cancellation issued by the disconnect watcher.
- `routes/chat_dispatch.py`: handle only disconnect-owned cancellation at HTTP edge.
- Append regression tests for real-socket disconnect logging and external cancellation.
- Chart values/ConfigMap and rendered-chart tests for optional queue timeout.
- Provider admission contract and existing specification/plan review follow-ups.

## Test plan

- Reproduce ASGI ERROR on actual socket disconnects at ERROR log level before fixing.
- Verify no stale dispatch, capacity recovery, INFO cancellation logs, uncancelled
  request tasks, and propagation of shutdown/concurrent cancellation.
- Render unset and configured chart values; verify Settings receives queue timeout
  and queued requests return 503 before a longer caller transport budget expires.
- Run append-only checks, lint, format, typecheck, enterprise import guard, full
  offline coverage suite, chart wiring verifier and production chart rendering.

## Acceptance

Expected disconnects are quiet, genuine cancellations propagate, operators can
configure queue timeout through Helm, and PR #1153 contains the tested fixes.

## Outcome

- **Actual files:** Admission watcher, HTTP dispatch boundary, Helm values/ConfigMap,
  provider admission contract, append-only unit/socket/chart tests, specification/plan.
- **Commit:** `fix(gateway): handle disconnects quietly and expose queue timeout`.
- **RED:** All four ERROR-level socket cases reproduced `Exception in ASGI application`;
  disconnect ownership and concurrent-cancellation tests failed; the chart test failed
  because its configured queue environment variable was absent.
- **Fix:** The watcher marks its cancellation before cancelling the request task. The
  HTTP edge consumes exactly that cancellation and raises a safe 499; any remaining
  cancellation propagates. Existing INFO phase logs and immediate cancellation remain.
  Helm exposes optional `config.providerQueueTimeoutS`, default unset, with a shorter
  queue allowance documented for existing Engine clients.
- **Gates:** `PYTEST_ADDOPTS='-m "not live and not needs_postgres"' uv run
  .claude/scripts/run_gates.py aigateway --base 24442c77`: ALL GATES GREEN; append-only,
  Ruff lint/format, Pyright, enterprise import guard, full offline suite, 93% coverage.
  All 46 focused admission/accounting/socket/chart cases passed on Python 3.12 and 3.13.
  Chart wiring: 113/113 passed; Helm lint and production-values rendering passed.
- **Deviations:** Live-provider/Postgres tests excluded per offline CI. Python 3.13
  socket tests needed unsandboxed loopback access; the temporary second environment
  was moved out of the application tree so the enterprise scanner checks project code.
  No existing tests changed, dependencies added, or production deployment performed.
- **Wisdom:** Disconnect provenance is explicit; external cancellation is never
  swallowed. HTTP 499 prevents successful response conversion/cache writes after a
  disconnect. Operator defaults stay intact; the shorter queue limit is opt-in.

## CI follow-up: synchronize ticket mirror status

The Mirror status workflow reported `ledger-done-mirror-not-started` for OME-1162:
this completed work ledger was paired with a stale Backlog task mirror. Linear MCP
confirmed the issue is In Review (since 2026-09-30), with no completion date. Updated
the existing mirror to In Review. The current CI checker reproduced the failure
before the correction and passes afterward; no runtime code or tests changed.
