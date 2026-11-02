---
ticket: OME-1602
stack: screamingface-engine
status: done
started: 2026-10-16
finished: 2026-10-16
---

# OME-1602-pr6-function-scorer-arguments: carry a scorer's function argument by reference, and import drop

## Intent

PR 6 of 6 for OME-1602. drop hands inspect's `f1` its own `extract_answer`, which reads the
reply's "Answer:" line. inspect logs that argument as the string `'extract_answer'`, so PR 1
refuses drop (F1). This unit writes a module-level function argument as a `module:attribute`
reference in a row field of its own, imports it at grading, and imports drop with its three
worked examples, as the eval sends them (owner decision on the ticket).

## Planned changes

- `importer.py`: a module-level function argument is named by reference and kept out of the
  literal kwargs; a lambda or a nested function is still refused.
- `import_replay.py`, `task_replay_rows.py`: the reference reaches the row.
- `benchmarks.py`: `BenchmarkSpec.scorer_function_kwargs`, resolved by the scorer factory,
  checked at assembly by spelling and package, pinned into the revision when set; the drop row.
- `prepare.py`: drop's Cases.
- Tests: `test_function_scorer_arguments.py` (new), `test_importer_named_scores.py`,
  `test_task_replay_rows.py`, the expected-value tables.

## Test plan

- drop grades the Answer line through the eval's reader, through its real hook.
- A module-level function becomes a reference; a lambda and a nested function are refused.
- Assembly refuses a misspelled reference, one outside the eval's package, and a name given
  both ways; the pin moves with the reference and is absent on every other row.

## Acceptance

- drop assembles with 9,535 Cases; no other row's revision moves.
- The named test files, ruff, and both pyright passes are green.

## Outcome

- **Actual files:** as planned.
- **Commits:** one feature commit.
- **Gates:** the inspect unit lane and the row-reading tests outside it; ruff check and
  format, and pyright with and without the extra on the touched files.
- **Deviations:** two PR 1 tests pinned the refusal of a module-level function argument,
  the shape this PR now names by reference, as the ticket planned ("refuse PR 1, resolve
  functions PR 6"). They now pin the refusal of a lambda, still unnameable; a new test pins
  the reference. The licence is CC-BY-SA-4.0 from the original DROP release, though the
  EleutherAI mirror's card says cc-by-4.0 (owner decision on the ticket).
- **Review fixes (2026-10-19):** the package rule now lives in one helper
  (`function_references.py`) that both the importer and assembly call, so the importer refuses
  a function from outside the eval's package (`textwrap:dedent`) instead of writing a row that
  only assembly refuses. The rule narrowed from the top-level package (any `inspect_evals.*`)
  to the package holding the eval's Task or scorer module. A new per-row test builds each
  scorer through `_scorer_factory`, the path grading takes, so a misspelled reference fails
  in CI; assembly and the image build's replay never import the scorer.
- **Owner verify:** none paid; drop needs no judge.
