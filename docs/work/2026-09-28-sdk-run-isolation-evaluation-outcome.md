---
ticket: OME-1071
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-09-29
finished: 2026-09-29
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

- **Actual files:** as planned.
  - `errors.py` — `ExecutionError.__init__(..., partial_report=None)` and the
    `partial_report` attribute.
  - New `_evaluation/outcome.py` — `_Failed`, the private carrier `_CandidatesFailed`,
    `settle`, `failure_code` (fallback `unexpected_error`), `raise_candidates_failed`
    (Partial Report + `candidates_failed`, raised `from` the first failed Candidate in
    the caller's order). 100 % covered.
  - `_evaluation/runner.py` — both twins: `_isolated_sync/_async` settle an ordinary
    `Exception` as `_Failed` (C1b, no sweep) unless the observer tagged it as the caller's
    (C1c); a `BaseException` or a tagged exception sweeps (`_sweep_sync/_async`, note kept),
    cancels the siblings and re-raises. The sync twin waits with `FIRST_EXCEPTION`
    (`_settled_results`) so an abort-class failure is seen at once. The observers record
    the caller's callback exceptions (`raised_by_caller`, identity) and forward
    `candidate_failed` to the built-in progress. `evaluate_*` convert the carrier through
    `_settled_sync/_async`. One-Candidate path unchanged.
  - `_evaluation/progress.py` (terminal line `<name> · run failed (<code>)`),
    `_ui/evaluation_state.py` (`_EvaluationProgress.candidate_failed`),
    `_ui/evaluation_widget.py` (`candidate_failed`).
  - Tests: new `tests/test_evaluation_outcome.py` (12, real transport + `_isolation_engine`
    stub, sync + async) and `tests/test_evaluation_outcome_runner.py` (16).
  - `tests/test_run_resume_reconnect.py` — the approved replacement (below).
  - `tests/public_surface_snapshot.json` — regenerated (below).
  - `packages/screamingface/CHANGELOG.md` — Unreleased / Bug Fixes entry, with the behavior
    change named.
- **Commits:** `266db2b1` docs(screamingface): record owner answers Q1-Q5 and the
  evaluation-outcome design; then `fix(screamingface): let the other Candidates finish when
  one fails; raise candidates_failed with a Partial Report` (this ledger's commit).
- **Gates:** `run_gates.py screamingface --base origin/main --skip-append-only` ALL GREEN —
  ruff, ruff format, pyright (0 errors), pytest 1990 passed / 26 skipped / 26 deselected,
  coverage 96 % (floor 95), notebooks, build, distribution. Without the skip, the
  append-only check fails on exactly the two approved files below and nothing else.
- **Prior tests / artifacts touched (owner approval 2026-09-29, Q1 and Q2):**
  - `packages/screamingface/tests/test_run_resume_reconnect.py::test_abort_sweep_records_note_when_stop_rejected`
    — REPLACED (Q1 (a)) by `test_an_ordinary_candidate_failure_calls_no_sweep` (an
    `ExecutionError` from one Candidate calls `cancel_active()` zero times) and
    `test_owner_abort_sweep_records_note_when_stop_rejected` (a KeyboardInterrupt sweeps
    once and carries the note "Stopping active SF Engine runs also failed"). Async twin of
    the note pin: `test_evaluation_outcome_runner.py::test_async_owner_abort_sweeps_once_and_records_a_rejected_stop`.
  - `packages/screamingface/tests/public_surface_snapshot.json` — regenerated (Q2 (a)) with
    `UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py` (that run fails
    on purpose; the next plain run passes). The only change: `ExecutionError.__init__`
    gains `partial_report: 'Report | None' = None`.
  - Because of these two, the final gate run used `--skip-append-only`. No other prior test
    changed; `_isolation_engine.py` and `_websocket_wire.py` are unchanged.
- **Deviations:**
  - The tests reach the stub through a small wrapper that replaces only the result body of
    a completed Run with a valid Candidate result (the stub's body is not one), and a
    `dict` subclass that finds a plan by the Candidate name inside the compiled URL4. This
    keeps `_isolation_engine.py` unchanged.
  - In the callback-abort tests the raising Run is not held: after its in-band stop the
    transport closes the socket, and the stub answers a close only after a held stream is
    released (stub fidelity, not SDK behavior).
  - `runner.py` was 614 lines before this unit (over the 450-line guideline) and is now 745.
    Moving the observers out is a separate refactor (prior tests import them from
    `runner`); not done here.
  - Consequence recorded in spec §5: in a multi-Candidate Evaluation, `EngineUnavailableError`
    / `AuthenticationError` from a Candidate now arrive as the `__cause__` of
    `candidates_failed` (follows from Q2 (a); in the CHANGELOG).
- **Follow-ups:** none. (Q5 is deferred by the owner; no ticket.) PR-open, the Linear
  close of OME-1071 / OME-1067 and the push are the user's decisions.
