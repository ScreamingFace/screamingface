---
ticket: OME-1420
stack: screamingface-engine
status: done
started: 2026-09-30
finished: 2026-09-30
---

# inspect-vocabulary — our words for our concepts, inspect's words only for inspect's objects

## Intent

The inspect plugin borrows inspect_ai's vocabulary (Sample, Target, Solver, Scorer, Task) for our own
concepts, so a reader can't tell whether "the target" is inspect's `Target` object or our Grading
Material. This unit adds an **Inspect** glossary entry that maps each inspect word to ours, and applies
its rule: inspect's words name only inspect's own objects, in the plugin code that calls inspect;
everything else uses our word. Follows the OME-1404 glossary rename (#1139, merged).

## Planned changes

1. `CONTEXT.md`: the Inspect entry (what `inspect`-prefixed names mean, and the word mapping).
2. Identifiers for our own concepts: grading-material names for `target` / `targets_dir` /
   `_validated_target`.
   Kept: inspect's API symbols (`Sample`, `Task`, `TaskState`, `record_to_sample`, `hf_dataset`) and
   references to inspect objects (`task_ref`, `question_filter_task`, `BenchmarkSpec.scorer` /
   `scorer_kwargs`); the on-disk `targets/` asset directory; the hashed revision-pin strings.
3. Prose in comments, docstrings and engine docs: each use of sample / target / solver / scorer
   read by hand and changed only when it names our concept. The engine core's own "scorer" (its
   Candidate-score function) stays: owner decision 2026-09-30.

## Test plan

- A rename adds no behaviour. Proof: the 35-benchmark fingerprint (revision, rendered protocol,
  catalogue fields, bundle id) and the served OpenAPI/AsyncAPI documents stay byte-identical to the
  #1139 base, plus ruff, pyright, layering and the full suite with the inspect extra.

## Acceptance

- `CONTEXT.md` carries the Inspect entry.
- No identifier outside inspect's own objects uses Sample / Target / Solver / Scorer for our concept.
- Fingerprint and API documents byte-identical; full suite green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `CONTEXT.md`, 10 engine source/test files and the imported-benchmark guide, this
  ledger and the task mirror.
- **Commits:** `docs: extend the Inspect entry to map inspect's words onto ours` · the identifier
  renames · the by-hand prose pass.
- **Gates:** ruff, ruff format, pyright 0 errors, layering OK; full suite 4647 passed with the inspect
  extra. 35-benchmark fingerprint and served OpenAPI/AsyncAPI documents byte-identical to `main`.
- **Deviations:**
  - #1139 merged with a short Inspect entry, so the first commit extends it instead of adding it.
  - The prose pass was split across three parallel agents by disjoint files, each given the same rule
    and worked examples; every change was reviewed here before commit. The core-and-guide pass found
    nothing to change (all hits were statistics, temperature sampling, route targets or HealthBench's
    own `grade_sample`).
  - Kept on purpose: the public failure code `missing_target_asset`, the `targets/` directory, and
    judge "tasks" (one judge job per rubric item, not inspect's Task).
  - `CasesSpec.keep_sample_metadata` / `excluded_sample_ids` keep inspect's word (review finding):
    they act on inspect Samples before Case Preparation decides which become Cases, and their values
    are upstream Sample ids, not Case numbers. A first draft renamed them and was reverted.
  - Two wording slips the glossary rename left in the judged-benchmark tests are fixed here.
- **Owner-verify:** merge.
