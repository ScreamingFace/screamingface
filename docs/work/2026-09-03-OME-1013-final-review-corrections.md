---
ticket: OME-1013
stack: screamingface
status: done
started: 2026-09-03
finished: 2026-09-03
---

# OME-1013 — Apply final diagnostic review corrections

## Intent

Correct local Engine classification in diagnostic receipts, remove redundant immutable-JSON
machinery, and explicitly test that direct URL4 input validation participates in OME-1013's
diagnostic boundary without changing the original exception contract.

## Planned changes

- Move the existing IP-aware Engine-origin classifier from the notebook UI package to a neutral
  private Client module and use it from diagnostics and existing UI consumers.
- Reuse `screamingface._immutable_json` for receipt freezing and thawing instead of maintaining a
  second recursive implementation.
- Add regression coverage for unspecified/loopback Engine addresses and public direct-URL4 option
  validation producing a degraded receipt while preserving the original `TypeError`.

## Test plan

- RED: extend Engine capture tests with local address aliases that the current hardcoded set
  misclassifies.
- RED: add direct URL4 misuse coverage that requires the validation error to be retained as a
  diagnostic receipt and re-raised unchanged.
- GREEN: run focused diagnostic tests, then the complete `screamingface` quality gates.

## Acceptance

- Local and unspecified IP Engine addresses are consistently classified as local across Client
  surfaces and diagnostic receipts.
- Direct URL4 option misuse retains a local receipt while the same `TypeError` reaches the caller.
- Diagnostic receipts use the shared immutable JSON implementation with unchanged public JSON.
- All `screamingface` gates pass and the changes are committed but not merged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** moved Engine-origin classification from `_ui/engine_origin.py` to the neutral
  `_engine_origin.py` module and repointed diagnostics plus all existing UI consumers; replaced the
  diagnostic-specific freeze/thaw recursion with `_immutable_json` helpers; added local-address and
  direct-URL4 validation coverage; recorded this ledger.
- **Commits:** this iteration's `fix(screamingface): apply diagnostic review corrections` commit.
- **Gates:** RED confirmed 3 intended locality failures with 28 passes; focused diagnostics and
  connection coverage passed (115 tests); `uv run .claude/scripts/run_gates.py screamingface`
  completed with `ALL GATES GREEN` across append-only protection, Ruff lint/format, Pyright, full
  pytest coverage at the 95% threshold, deterministic notebook validation, build, and distribution
  validation.
- **Deviations:** the new direct-URL4 tests passed during RED because the reviewed behavior was
  already intentional; the locality cases supplied the failing production signal. The user's
  modified quickstart notebook and exported diagnostic JSON were temporarily stashed for the full
  gate, restored unchanged, and excluded from the commit. One initial focused command named a
  nonexistent connection-view test file; it ran no tests and was immediately corrected.
