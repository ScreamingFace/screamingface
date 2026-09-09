---
ticket: OME-1141
stack: screamingface
status: done
started: 2026-09-09
finished: 2026-09-09
---

# OME-1141 — Give late disconnects their recovery budget

## Intent

Fix the SDK recovery deadline so healthy Evaluation runtime cannot exhaust reconnect
attempts before a connection fails. User approved implementation and opening a PR.

## Planned changes

- SDK transport and a private recovery-window helper shared by sync/async loops.
- New deterministic transport regression tests; preserve all existing tests.
- Spec, plan, task mirror, and this ledger.

## Test plan

Simulate the actual reconnect loops with a controllable clock and scripted sockets:
late keepalive close, cursor/token reuse, first-failure budget, repeated connection
failures, flapping sockets, a stable recovered connection, zero budget, and cancellation.
Run the full screamingface gate runner including 95% coverage and packaging checks.

## Acceptance

A disconnect after 1085 seconds gets retries and resumes. Repeated failed attempts
remain bounded. A stable connection restores a fresh budget and backoff. Both clients
behave identically. No heartbeat, Engine, or public API changes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** transport.py; new _engine/reconnect.py and test_reconnect_recovery_window.py; matching spec, plan, task mirror, and ledger.
- **Commits:** planned `fix(screamingface): give disconnects a fresh recovery budget` (Refs: OME-1141).
- **Gates:** final regression harness against original transport: 14 failed / 4 passed; fixed transport: 18 passed in 0.27s. Existing reconnect suite: 6 passed. `uv run .claude/scripts/run_gates.py screamingface`: ALL GATES GREEN (append-only, lint, format, pyright, full pytest with 95% minimum coverage, notebooks, build, distribution). Pre-commit hooks all passed.
- **Deviations:** none

## Wisdom and confidence review

- A 26-line private state object shares the policy between both clients; no dependency,
  public interface, schema, or Engine change. Existing transport file is already over
  450 lines; unrelated extraction is outside this focused fix.
- Tests retain the real lifecycle and stream parser, scripting only I/O and time. They
  assert saved cursor/capability reuse, no duplicate start, bounded retries, cleanup,
  stable reset at the threshold, and abort. Existing tests remain unchanged.
- Resetting on every handshake would allow infinite flapping. A connection must last
  the existing recovery-window duration before its next failure starts a fresh outage.
- No credentials are exposed and no authentication or terminal-error behavior changes.
- Runtime cause of the missed Pong remains unconfirmed; this PR fixes recovery only.
