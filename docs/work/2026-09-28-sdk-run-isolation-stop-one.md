---
ticket: unfiled   # OME-1071 (epic OME-1016) — backfill at PR-open
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-09-28
finished: 2026-09-28
---

# sdk-run-isolation-stop-one — stop one Run instead of every Run (transport half)

Ticket: **OME-1071** (epic OME-1016). Spec: `docs/spec/2026-09-28-sdk-run-isolation.md`.
Plan: `docs/plan/2026-09-28-sdk-run-isolation.md`, unit 1.

## Intent

A fatal handshake refusal on ONE started Run (non-Access 401/403, or the re-login cap)
stops every Run the Client owns (`cancel_active()`). Add a per-Run stop and use it on that
path (spec C2). Also fix B1: `_aborted` never resets, so after one sweep every later Run on
the same Client neither reconnects nor stops its own Run. The runner change (spec C1) waits
for owner answers Q1-Q3 (unit 4).

## Planned changes

- `packages/screamingface/src/screamingface/_engine/transport.py` — `_stop_own_run` (sync +
  async); `_on_handshake_rejection` calls it; `run()` clears `_aborted` when no Run is
  active.
- New test stub `packages/screamingface/tests/_isolation_engine.py` (several Runs per stub).
- New tests `packages/screamingface/tests/test_run_isolation.py`.
- Spec + plan (first commit).

## Test plan

- Two Runs on one transport; A's reconnect refused 401; B healthy and held open until A
  fails → A `websocket_disconnected`, B completes, only A's capability deleted. Sync + async.
- B1: after `cancel_active()`, a new Run whose first stream drops (1012) reconnects and
  completes, with no `DELETE /`. Sync + async.
- Prior tests unchanged and green (single-Run handshake tests still see exactly one
  `DELETE /`).

## Acceptance

- New tests pass; all prior tests pass unmodified; `run_gates.py screamingface` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `_engine/transport.py` (`_stop_own_run`, `_end_finished_abort`,
  both twins; C2 now stops one Run), new `tests/_isolation_engine.py` (multi-Run stub with
  per-Run plans; it already carries the admission, drop and artifact knobs units 2-3 use),
  new `tests/test_run_isolation.py` (8 tests), spec + plan (commit `ba8ead2d`).
- **Commits:** `ba8ead2d docs(screamingface): spec and plan for SDK run isolation`;
  `fix(screamingface): stop only the failed Run on a fatal reconnect refusal` (this unit).
- **Gates:** `run_gates.py screamingface --base origin/main` ALL GREEN — append-only ✓, ruff ✓,
  format ✓, pyright ✓, pytest 1910 passed / 26 skipped, coverage 96 % (floor 95), notebooks ✓,
  build ✓, distribution ✓. Local env note: the venv needs `uv sync --extra notebook` (as CI)
  or pyright cannot resolve `ipywidgets`.
- **Deviations:** the runner change (spec C1) and the Partial Report moved to unit 4. They
  need owner answers Q1-Q3 (spec §7): the prior test
  `tests/test_run_resume_reconnect.py::test_abort_sweep_records_note_when_stop_rejected`
  pins "one Candidate's ExecutionError → `cancel_active()`", and the Partial Report changes
  the public surface. Until unit 4, a multi-Candidate Evaluation still sweeps on C1.
- **Follow-ups / owner questions:** spec §7 Q1-Q5. Bug B1 (sticky `_aborted`) fixed here.
