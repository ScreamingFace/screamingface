---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-12
finished: 2026-10-12
---

# empty-answer-key — let a Benchmark's own scorer read an empty answer key as "no answer here"

## Intent

OME-1527 requirement R5, Work order #6. contracteval (CUAD clauses) moves to a local Task next:
1,244 of its 4,182 Cases carry the clause spans a reply must quote, and the other 2,938 carry
none, where the right reply declines ("no related clause"). Its own scorer reads that empty
key as a fact. Case Preparation's trust boundary refuses an empty key unless the row says the
Benchmark has no key at all (`has_answer_key=False`), and a judge-free row may say that only
alongside `scorer_reads_answer_key=False`. Both claims are false for contracteval, so it could
not be served. This unit adds a row-level opt-in for "some Cases' empty key is their answer",
accepted only beside the eval's own judge-free scorer.

## Planned changes

- `prepare.py`: `TaskReplayCasesSpec.empty_answer_key_allowed: bool = False`; the trust boundary
  accepts an empty `""`/`[]` target (no choices) under it, frozen in the Sample's own shape.
- `benchmarks.py`: `_check_empty_answer_key_claim` refuses the opt-in beside a judge, inspect's
  built-in scorers, `has_answer_key=False`, `scorer_reads_answer_key=False`, or a check surface.
- `task_replay_rows.py`: the generated row writes `empty_answer_key_allowed=True` only when set.
- `import_replay.py` / `importer.py`: `--empty-answer-key-allowed` threaded to both replays and
  the sealed declaration; mutually exclusive with `--no-answer-key`.

## Test plan

- Prepare: an empty key accepted only on a flagged row; non-empty keys still validated; an
  empty key beside choices still refused; the Target the scorer gets back after the JSON round
  trip equals the Target inspect builds from the Sample (`[]` stays `[]`).
- Assembly: each of the five refusals; the opt-in moves no revision.
- Importer: flag reaches the import; the two key flags are mutually exclusive; a stand-in
  contracteval-shaped eval is refused without the flag and sealed with it.
- Row writer: the line is written when set and absent otherwise.

## Acceptance

- No existing row sets the opt-in; `test_published_revisions.py` stays green untouched.
- The frozen empty key gives the scorer the same Target inspect would.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus new tests appended to `test_list_target.py`,
  `test_judged_benchmark_assembly.py`, `test_task_replay_rows.py`, `test_import_replay.py`,
  `test_importer_command.py`. No pre-existing test edited (append-only).
- **Commits:** feat(screamingface-engine): let a Benchmark's own scorer read an empty answer key
- **Gates:** relevant files only: 299 passed (the five files above plus
  `test_inspect_task_replay_benchmarks.py`, `test_published_revisions.py`); ruff check + format
  clean; extra-less pyright 0 errors on touched files. Full gate runs in the pre-push hook + CI.
- **Deviations:** the frozen value for an empty list is `[]`, not `""`: inspect's `Target([])`
  holds no answers while `Target("")` holds one blank one, which an all-of scorer finds in
  every reply. The key-less (`has_answer_key=False`) path still freezes `""`, unchanged.
