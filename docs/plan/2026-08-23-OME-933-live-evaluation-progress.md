# OME-933 — Live Evaluation progress (implementation plan)

- **Spec:** `docs/spec/2026-08-23-OME-933-live-evaluation-progress.md`
- **Linear:** https://linear.app/openmined/issue/OME-933/redesign-live-evaluation-progress
- **Stack:** `screamingface` (`sdlc-python`)
- **Dependency:** `OME-950`

Implementation starts only after explicit approval of the spec and this plan.

## 1. RED — pin Candidate-scoped state and exact terminal Case counting

Add state tests before production changes for:

- all Candidate rows existing in input order before an Event arrives
- independent `completed / case_count` for interleaved Candidate Runs
- the exact `operation == "RelUrlNode"` and `name == "/benchmarks/case-execution"` match
- successful and error terminal Case spans both counting
- RemoteFetchNode, model, and unrelated structural spans not counting
- a 10 Candidate × 100 Case fold reaching 100 independently per row
- early termination freezing the observed numerator below the denominator
- per-Candidate usage, cache provenance, model activity, elapsed time, and terminal evidence
- final CandidateResult reconciliation for score, usage, and Finished qualifiers

Run the focused tests and record RED failures caused by the current aggregate Candidate counter and
unscoped observer.

The existing progress-panel suite contains assertions for the aggregate panel OME-933 intentionally
replaces. Revise only those superseded presentation/state assertions; retain unaffected cache,
Event, escaping, formatter, paid-disclosure, and fail-open coverage. This is the approved contract
replacement, not a legacy compatibility layer. Add every new invariant append-only.

## 2. GREEN — bind each Run observer to its Candidate

In `_evaluation/runner.py` and `_evaluation/progress.py`:

- define a private built-in Evaluation observer port that accepts `(Candidate, Event)` and has
  terminal reconciliation/abort methods
- let the sync and async combined observers bind a small Candidate-scoped callback for each
  `transport.run`
- keep one shared lock per Evaluation so interleaved callbacks remain serialized
- continue passing the original Event alone to the public callback exactly once
- keep the text observer behavior unchanged while ignoring its bound Candidate context
- reconcile the built-in observer only after `report_from_outcomes` returns a valid Report
- on workflow failure, freeze the built-in observer without emitting a synthetic public Event

Cover both the single-Candidate fast path and the multi-Candidate sync/async paths. Pin the existing
eight-Run concurrency gate and queued Candidates that never start.

## 3. GREEN — replace the aggregate fold with ordered Candidate rows

In `_ui/evaluation_state.py`:

- introduce one Evaluation fold owning ordered per-Candidate row state plus aggregate evidence
- bind root Started/Terminated evidence to its already-known Candidate rather than matching URLs or
  models
- count the exact terminal Case span before filtering structural spans from model-call statistics
- preserve Run-keyed cache-summary replacement and bypass-reason reconciliation
- preserve self-scoped Usage accounting without subtree double-counting
- derive only the approved lifecycle statuses and final qualifiers
- keep bounded real activity evidence; add no inferred phase or Case identity
- reconcile final fields from the matching CandidateResult by Candidate identity and validate that
  every expected Candidate appears once

The fold remains independent of ipywidgets and wall-clock reads so its transitions are deterministic
and directly testable.

## 4. GREEN — build the SFDS v2 Candidate table and render scheduler

In `_ui/evaluation_view.py`:

- replace the aggregate progress bar with the six-column semantic Candidate table
- add the sticky header/Candidate column and an internal horizontal-scroll shell; do not add a
  responsive card/stack alternative
- show truthful unavailable/final wording and a progress element for each known denominator
- preserve the paid-check disclosure, aggregate calls/tokens/cost, cache-provenance band, collapsed
  activity, and conditional global error in the specified order
- replace whole-panel `aria-live` with a dedicated limited announcement region
- apply SFDS v2 app-register typography, square/hairline geometry, readable text roles, solid blue
  activity, semantic status colors, light/dark parity, and reduced-motion behavior
- remove the old gradient/sweep and small-screen stacked-stat treatment
- fold Events immediately, coalesce dirty renders around 100 ms, retain the one-second silent clock,
  and force a final visible render before stopping the scheduler

Render tests must assert structure and semantics rather than brittle full HTML snapshots.

## 5. Regression and contract verification

Add integration tests around the runner and built-in observer for:

- sync and async Candidate scoping under concurrent interleaving
- public callbacks receiving the same Events once and in their existing accepted order
- successful Report reconciliation occurring after result decoding
- invalid result decoding freezing a truthful failed panel while preserving the raised public error
- user interruption, timeout, Engine terminal failure, and never-started Candidate handling
- renderer/comm exceptions remaining outside the paid Evaluation failure boundary
- progress disabled and non-notebook text fallback behavior remaining unchanged

Run the focused progress and Evaluation suites throughout.

## 6. Full gate and delivery

From the repository root run:

```text
python3 .claude/scripts/run_gates.py screamingface
```

This covers Ruff, formatting, Pyright, at least 95% package coverage, deterministic notebook checks,
the package build, and distribution verification.

Then:

- inspect the final diff against the approved spec and the SFDS v2 skill
- complete the work ledger with exact tests, deviations, and visual owner verification
- commit with a conventional message and `Refs: OME-933`
- push the branch and open a draft PR
- after `OME-950` lands, rebase the branch onto `origin/main` before requesting merge review

Temporary ancestry is a branch-management detail and does not alter the Linear product contract.
