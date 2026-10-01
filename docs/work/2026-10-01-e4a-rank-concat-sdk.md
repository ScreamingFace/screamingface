---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# e4a-rank-concat-sdk — sf.Rank and sf.Concat, the selection reducers (OME-1289, unit 10 SDK)

## Intent

`sf.Rank(k, by=sf.Judge(..., returns="scores") | by_field="score")` keeps the top k original member
texts, and `sf.Concat(separator, label)` joins every member text in author order. Both are Fusion
synthesizers of kind `selection`: their output is a hand-off to the NEXT Pipeline stage and not an
answer. So the compiler must refuse a selection Fusion that ends a candidate, that is a Fusion
member (directly or through a Pipeline that ends in one), or that feeds a corrective loop. The
next stage reads exactly the selection (`$synthesis_N`). Rank by judge reuses the unit 8 seams
(`_ModelSignal`, `judge_from_signals`, `_spec_steps`, `OPERATION_BINDING_PARAM`); this unit adds no
new compiler path for signals. The Engine half (`top_k@1`, `join@1`, `all@1`) is on another branch,
so every test here uses the fixture catalog.

## Planned changes

- SDK src: `selection.py` (new: `Rank`, `Concat`), `_evaluation/candidate.py` (the selection flag
  on `_ResolvedRecipe` and three compile checks), `__init__.py`, `CHANGELOG.md`, `README.md`.
- SDK tests (new): `tests/test_rank_concat_reducers.py`, `tests/test_selection_compile_checks.py`,
  `tests/test_rank_concat_url4_round_trip.py`.
- `tests/public_surface_snapshot.json` regenerated (the one allowed append-only offender).

## Test plan

RED first on a skeleton (`Rank` and `Concat` with no validation and placeholder steps): RK-6 k and
by/by_field bounds, CC-5 separator and label, the three exact spec literals, CC-2 compile (one pure
combine call), RK-1/CC-3 (selection at the end), RK-2 (selection as a Fusion member, directly and
via a Pipeline; corrective loop), RK-4 (next stage context is exactly `$synthesis_1`), url4 round
trip and tampering. CHAR tests pass at once by design: SL-1 (a reducer without signals compiles as
before) is covered by the existing unit 4 and 8 tests; this unit adds a guard that Vote and Judge
keep `selection is None`.

## Acceptance

- `screamingface --base e4a-judge-pick-sdk` with append-only: only `public_surface_snapshot.json`.
- `screamingface --skip-append-only` green, `repo` green.
- SDK to Engine cross-check: Rank (judge scores), Rank (by_field) and Concat specs, contexts and
  params parse and run in the Engine `run_combine` with sample member texts.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned; nothing unlisted. New: `selection.py`, `tests/test_rank_concat_reducers.py`,
  `tests/test_selection_compile_checks.py`, `tests/test_rank_concat_url4_round_trip.py`. Edited:
  `_evaluation/candidate.py` (`_ResolvedRecipe.selection`, `_reject_selection_members`, the end-of-candidate
  and corrective checks), `__init__.py`, `CHANGELOG.md`, `README.md`, `tests/public_surface_snapshot.json`
  (regenerated). `reducer.py`, `judge.py`, `topology.py`, `url4.py` and the other seams are untouched:
  Rank by judge reuses `_signals`, `_rebuild`, `judge_from_signals`, `_spec_steps` and
  `OPERATION_BINDING_PARAM` as they are.
- **RED/GREEN:** RED for the right reason (assertions, DID NOT RAISE) on a skeleton `Rank`/`Concat` with no
  validation, `_kind` "answer" and placeholder steps: 39 of 44 tests failed (k bounds, by/by_field, separator
  and label, the spec literals, `_kind`, repr, the end-of-candidate and member checks, every round trip and
  tamper case). Then GREEN with the real code. These pass at once by design: the guard test (a Rank or
  Concat is only a Fusion synthesizer; the existing guards cover it), the CHAR check that Vote and Judge keep
  ending a candidate (SL-1), the compile-shape tests for a followed selection, and the next-stage context
  test (the Pipeline already feeds `$synthesis_N` to the next stage).
- **Gates:** `screamingface --base e4a-judge-pick-sdk` (append-only): only offender
  `tests/public_surface_snapshot.json` (expected: `Concat` and `Rank`). `--skip-append-only`: ALL GATES GREEN
  (ruff, format, pyright, pytest with coverage >= 95, notebooks, build, distribution). `repo`: ALL GATES
  GREEN. The two known flaky tests did not fail.
- **SDK to Engine cross-check** (not committed): Rank by judge scores (also a tie at the cut), Rank by
  field (also a nested path), and Concat (labels, no labels, an empty member, a separator with `$`, DEL,
  U+2028, quotes and a backslash that collides with a member text) were compiled by the SDK, then the
  emitted intent, context (members and judge reply resolved) and params ran through the Engine's
  `parse_spec`, `parse_context` and `run_combine(BUILTIN_OPERATORS, ...)`. All ran; outputs and evidence
  matched the PRD (selection JSON in rank order, `tie`, `separator_collision`). The Engine catalog ids and
  stages equal `FLOW_OPERATOR_IDS`.
- **Deviations:** none from the behavior spec. Small choices: `Rank._rebuild` and `Concat._from_spec`
  rebuild the reducer from the spec's few free values (k, path, separator, label) and then require the
  decoded steps to equal what that reducer writes (`_require_steps`), so any hand edit is refused with
  "cannot rebuild"; the match helper is local to `selection.py` because the Judge one compares op names
  without versions and Rank pins `numeric@1` exactly. `by` that is not a Judge raises the same
  `ValueError` as a label Judge. Messages: "Rank k must be an integer" (TypeError), "Rank needs exactly one
  of by= or by_field=", "Rank by_field must be a JSON field path ...", "Concat separator must be a string".

## Review round 1 (coordinator, ACCEPT-WITH-FIXES)

Applied: `selection.py` uses the shared `reducer._require_steps` (the local `_require_steps` and
`_step_is` are gone; the shared matcher handles the pinned `numeric@1` and the weights check); one
`reducer._field_path(value, label)` validator (256-char cap) serves Rank `by_field` and Pick `field`
(`fields._check_pick_field` removed, messages unchanged where tests match them; Rank's message now reads
"Rank by_field '...' must be a JSON path ..."); `Rank._rebuild` refuses a hand-edited k above the member
count (new tamper case); README and CHANGELOG name `scores@1` and `top_k@1` for both Rank forms and
`join@1` and `all@1` for Concat; new tests for a corrective-loop judge that is a selection and for a
Fusion member whose Recipe synthesizer ends in a selection; the engine-mirrored limits carry
`# INVARIANT` comments, `_MAX_K` reuses `_MAX_REDUCER_MEMBERS`, `DEFAULT_SEPARATOR` is private; a
non-Judge `by` raises `TypeError` (a label Judge keeps `ValueError`); CHANGELOG is in unit order. Also
added the deferred engine drift guard `test_sdk_flow_catalog_fixture.py` (reads `FLOW_OPERATOR_IDS` as an
`ast.AnnAssign` or `ast.Assign`, no duplicates, equals the built-ins). No deviations.
