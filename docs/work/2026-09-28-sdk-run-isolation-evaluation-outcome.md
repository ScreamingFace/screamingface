---
ticket: OME-1071
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-09-29
finished:
---

# sdk-run-isolation-evaluation-outcome — one failed Candidate does not stop its siblings

Ticket: **OME-1071** (epic OME-1016), runner half. This unit also completes the
multi-Candidate part of **OME-1067** (epic OME-1064) and is relevant to **OME-1066** (a
Candidate whose start is never admitted no longer stops its siblings). Spec:
`docs/spec/2026-09-28-sdk-run-isolation.md` §4.1 (C1a/C1b/C1c), §5, §5.1. Plan: unit 4.
Branch `OME-1071-sdk-evaluation-outcome` from `origin/main` (units 1-3 are merged: #1105,
#1109, #1115).

## Intent

Today the runner stops every Run of the Client when one Candidate's `transport.run()`
raises. After units 1-3, that Run's transport has already stopped its own Run, so the sweep
only destroys healthy siblings (incident 2026-09-01). The owner answered Q1-Q3 on
2026-09-29: an ordinary Candidate failure stops nothing, the siblings run to their end, and
the Evaluation then raises `ExecutionError(code="candidates_failed")` with a Partial Report
of the Candidates that succeeded (ADR-0002). An owner abort and an exception from the
caller's own `on_event` callback still stop everything.

## Planned changes

- `packages/screamingface/src/screamingface/errors.py` — `ExecutionError.partial_report`.
- New `packages/screamingface/src/screamingface/_evaluation/outcome.py` — the failure
  record, the private carrier exception, the failure-code fallback, the Partial Report and
  the `candidates_failed` error (shared by both twins).
- `packages/screamingface/src/screamingface/_evaluation/runner.py` — C1a/C1b/C1c split in
  `_run_candidates_sync/_async`; observers tag the caller's callback exceptions and forward
  a per-Candidate failure to the progress output; `evaluate_sync/_async` raise
  `candidates_failed`.
- `packages/screamingface/src/screamingface/_evaluation/progress.py`,
  `_ui/evaluation_state.py`, `_ui/evaluation_widget.py` — show the failed row at once.
- `packages/screamingface/tests/public_surface_snapshot.json` — regenerated (owner Q2).
- `packages/screamingface/tests/test_run_resume_reconnect.py` — replace
  `test_abort_sweep_records_note_when_stop_rejected` (owner Q1).
- New tests `packages/screamingface/tests/test_evaluation_outcome.py` (+ a second file if
  one passes 450 lines).
- `packages/screamingface/CHANGELOG.md` — Unreleased entry.
- Spec + plan update (first commit).

## Test plan

- Real transport + `_isolation_engine` stub, sync and async: one Candidate's reconnect is
  refused (401) or never admitted (503 until the budget ends) while a sibling is held
  open → the sibling completes; the only `DELETE /` is the failed Run's; the Evaluation
  raises `candidates_failed` with `details={"failed": {name: code}}`, `__cause__` = the
  first failure, and a Partial Report with the sibling only.
- All Candidates fail → `partial_report is None`.
- A failure without a code → the fallback code `unexpected_error`.
- A result that the SDK cannot decode for a Candidate whose Run succeeded → that
  Candidate is named in `failed`; it is not in the Partial Report.
- One-Candidate Evaluation → the error itself, `partial_report is None` (today's behavior).
- `on_event` raises → that exception itself is re-raised (identity), the sibling is swept,
  no `candidates_failed`.
- Replacement pin (owner Q1): an ordinary Candidate failure calls no `cancel_active()`;
  a KeyboardInterrupt (sync) / an outer cancellation (async) sweeps once and records the
  note "Stopping active SF Engine runs also failed".
- Progress: the failed row changes to `run_failed` while a sibling still runs; terminal
  line; the final abort keeps the successful row and the failed row.
- Async: no task is left pending after `candidates_failed`.

## Acceptance

- New tests pass sync and async; every other prior test is unmodified and green.
- `run_gates.py screamingface --base origin/main --skip-append-only` green (coverage ≥ 95 %).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
