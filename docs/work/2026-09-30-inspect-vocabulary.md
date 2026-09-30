---
ticket: unfiled
stack: screamingface-engine
status: in_progress
started: 2026-09-30
finished:
---

# inspect-vocabulary — our words for our concepts, inspect's words only for inspect's objects

## Intent

The inspect plugin borrows inspect_ai's vocabulary (Sample, Target, Solver, Scorer, Task) for our own
concepts, so a reader can't tell whether "the target" is inspect's `Target` object or our Grading
Material. This unit adds an **Inspect** glossary entry that maps each inspect word to ours, and applies
its rule: inspect's words name only inspect's own objects, in the plugin code that calls inspect;
everything else uses our word. Stacked on the OME-1404 glossary rename (#1139).

## Planned changes

1. `CONTEXT.md`: the Inspect entry (what `inspect`-prefixed names mean, and the word mapping).
2. Identifiers for our own concepts: grading-material names for `target` / `targets_dir` /
   `_validated_target`, and our names for `CasesSpec.keep_sample_metadata` / `excluded_sample_ids`.
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

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
