---
ticket: OME-1527
stack: screamingface
status: done
started: 2026-10-15
finished: 2026-10-15
---

# paid-provenance-own-bundle — the paid lane's label-copy test reads each Benchmark's own bundle

## Intent

OME-1527 row 21 (PR 21 of 21, a review fix after the stack merged). The 2026-10-15 paid press
(run 38701565473) failed one free test: `test_each_picked_benchmarks_label_is_copied_for_the_debug_bundle`
still expected draco-3pass to read draco's prepared bundle. The draco (#1395) and healthbench
(#1403) moves removed that shared-bundle map from `_case_provenance.py` and deleted its own test,
but missed this one. Merge CI never collects `tests/paid`, so the paid press was the first run
to see it.

## Planned changes

- `packages/screamingface/tests/paid/test_case_provenance.py`: seed draco-3pass's label in its
  own bundle; the docstring says each Benchmark reads its own bundle.
- `.claude/test-change-approvals/OME-1527.json`: approve that one edit of a prior test.

## Test plan

- The edited test itself, run inside the paid fence (`SCREAMINGFACE_TEST_PAID=1`), plus every
  free test in `tests/paid` with no OpenRouter key (the paid smoke skips).

## Acceptance

- The edited test passes against main's `copy_labels`; no other paid-lane test changes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger.
- **Commits:** 7f663c7e2 — test(screamingface): read draco-3pass's provenance label from its own
  bundle (OME-1527).
- **Gates:** `SCREAMINGFACE_TEST_PAID=1 pytest tests/paid` with no key: 74 passed, 1 skipped (the
  paid smoke). ruff check and format clean. Append-only check by hand (OME-1575) against
  upstream/main: passes through `OME-1527.json`.
- **Deviations:** none.
- **Owner verify:** the same press also failed at setup because the AI Gateway's live key check
  answered 422 (`api_key_invalid` or `api_key_expired`) for the `OPENROUTER_API_KEY` repo secret;
  reset the secret, then press the paid smoke again.
