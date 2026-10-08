---
ticket: OME-1458
stack: screamingface
status: done
started: 2026-10-08
finished: 2026-10-08
---

# attempts-sdk — the SDK reads, bills and shows several Attempts per Case (PR 3 of 7)

## Intent

The SDK side of OME-1458 (plan `docs/plan/2026-10-08-OME-1458-attempts-per-case.md`, PR 3). A
Benchmark that declares N Attempts sends every Attempt in an `attempts` list on the Case Result.
The SDK decoder refuses unknown keys, so it must know the key before any Engine emits it: this
PR releases first (spec F8).

## Planned changes

- `packages/screamingface/src/screamingface/case_result.py` — `CaseAttempt`, `CaseResult.attempts`.
- `.../_evaluation/results.py` — decode `attempts` strictly.
- `.../accounting.py` — bill each Attempt's calls once.
- `.../_ui/report_view.py` — "1 of 2 Attempts matched" and the per-Attempt list.
- `.../_engine/catalog_contract.py`, `_engine/catalog.py`, `discovery.py`, `_ui/cards.py`,
  `_catalogue_vocabulary.py` — `Benchmark.attempts` and "any of N Attempts".
- `.../_report_primitives.py` and `apps/screamingface-engine/.../benchmarks/contract.py` — the
  failure code `attempt_grade_not_pass_fail` on both pinned-equal lists.
- `tests/test_case_attempts.py`, `tests/unit/test_attempt_failure_code.py`, the public-surface
  snapshot, `CHANGELOG.md`.

## Test plan

- Model: absence unchanged; order and grades kept; numbering 1..N with N ≥ 2; a scored Attempt
  without a grade refused; Case-level operations beside Attempts refused.
- Wire: decodes and round-trips; an unknown key inside an Attempt refused; Attempt operations
  round-trip.
- Accounting: two Attempts × one call billed twice, no duplicate-operation refusal; member usage
  sums Attempts.
- Report: matched count; failed count; each Attempt listed; empty fragments without Attempts.
- Catalogue: "any of 2 Attempts" on the row and the card; absent means 1 and shows nothing; a
  malformed value is a catalogue defect.

## Acceptance

- Spec acceptance 7 (SDK half): the code is declared on both lists.
- An Engine payload with `attempts` decodes; one without decodes and exports byte-identically.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, minus `examples/helpers.py` (see Deviations).
- **Commits:** see the PR.
- **Gates:** `uv run ruff check`, `ruff format --check`, `pyright` (0 errors) green; full SDK
  suite `pytest -n auto`: 2286 passed, 26 skipped, the one failure the public-surface snapshot,
  regenerated deliberately; Engine twin `test_failure_code_conformance.py` passed.
- **Deviations:** (1) `examples/helpers.py:load_candidate_result` is unchanged: it already drops
  `operations` and Check detail when rebuilding a submit-ready result, and `attempts` is
  optional, so a report with Attempts still rebuilds. (2) `Benchmark.attempts` is the last
  field, after `saturation`, because the dataclass is positional. (3) The public-surface
  snapshot is a prior-test change (two new fields and constructor keywords); it needs the
  owner's approval manifest before the gate's append-only lane passes.
