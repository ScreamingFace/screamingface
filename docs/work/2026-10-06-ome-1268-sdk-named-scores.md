---
ticket: OME-1268
stack: screamingface
status: done
started: 2026-10-06
finished: 2026-10-06
---

# ome-1268-sdk-named-scores — the SDK decodes, reports and shows Named Scores (PR 2 of 5)

## Intent

The second slice of the OME-1268 stack, and the first code slice. A Benchmark with several
scorers will send every score by name in a `scores` field on each Case Grade and on the
Candidate Result (PR 3). The SDK's decoder refuses any key it does not know, so this slice
teaches the SDK the key BEFORE any Engine emits it, carries it on `sf.CaseGrade` and
`sf.CandidateResult`, writes it into report.json as a stable key (`{}` when absent), exposes
`result.scores`, and shows a `scores` block on the report card. Releases before PR 3 deploys.

## Planned changes

- `packages/screamingface/src/screamingface/_catalogue_vocabulary.py`: `SCORES_KEY`
- `packages/screamingface/src/screamingface/case_result.py`: `CaseGrade.scores`
- `packages/screamingface/src/screamingface/report.py`: `CandidateResult.scores` + `to_dict`
- `packages/screamingface/src/screamingface/_evaluation/results.py`: optional `scores` on the
  Case Grade and Candidate result decoders
- `packages/screamingface/examples/helpers.py`: `load_candidate_result` rebuilds `scores`
- `packages/screamingface/src/screamingface/_ui/report_view.py`: the `scores` block
- `packages/screamingface/tests/public_surface_snapshot.json`: regenerated (owner
  `--skip-append-only`)
- prior report.json equality tests that now need `"scores": {}` (owner `--skip-append-only`)

## Test plan

- `tests/test_case_results.py`: named scores on a Case Grade, frozen, finite-or-None, `{}` default
- `tests/test_report.py`: named scores on a Candidate Result; unscored result refuses them;
  `to_dict` emits `scores` always; round trip through `load_candidate_result`
- `tests/test_case_result_contract_boundaries.py`: optional `scores` key decodes; absent → `{}`;
  a non-mapping is refused
- `tests/test_report_panel.py`: the block renders one row per named score with the `headline`
  tag on the ranked row only; absent for a single-score Candidate (HTML unchanged)

## Acceptance

- Spec §8 items 3 (SDK side), 5 (single-scorer run result byte-identical; report.json differs
  only by the stable key) and 6 (prior tests untouched except the two named edits).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, except that every new test lives in one file,
  `packages/screamingface/tests/test_named_scores.py` (17 tests), and no prior report.json
  test needed an edit. Changed: `_catalogue_vocabulary.py` (`SCORES_KEY`), `case_result.py`
  (`CaseGrade.scores`, `named_scores`), `report.py` (`CandidateResult.scores`),
  `_evaluation/results.py` (optional key on both decoders, `_wire_scores`),
  `_ui/report_view.py` (`_scores_html`, `_score_row`), `examples/helpers.py`,
  `tests/public_surface_snapshot.json` (regenerated: two constructors, two properties).
- **Commits:** 1fefaac4c — feat(screamingface): decode, export and show a Benchmark's Named
  Scores
- **Gates:** `run_gates.py screamingface` stops at the append-only lane on the regenerated
  snapshot (the owner's `--skip-append-only`, asked for by name in the PR body); every other
  lane run by hand and green: ruff check, ruff format --check, pyright (0 errors), pytest
  `-n auto --cov=screamingface` 2088 passed / 2 skipped, TOTAL 95% (floor 95),
  `check_notebooks.py`, `uv build`, `check_distribution.py`.
- **Deviations:** (1) `CaseGrade.to_dict` writes `scores` only when set, not always: the Case
  Grade dict is pinned one-to-one to the Engine's wire by three exact-contract round-trip tests,
  so the stable `{}` key lives on the Candidate Result only (plan D7 narrowed; as-built note in
  the plan). (2) Plan Task 2.5 (prior report.json equality edits) was not needed. (3) The
  report-card block tags the FIRST Named Score as the headline (plan D2: the Engine writes
  headline first); PR 3 pins that order in the Engine's validator.
