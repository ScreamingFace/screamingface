---
ticket: OME-1602
stack: screamingface-engine
status: done
started: 2026-10-14
finished: 2026-10-15
---

# OME-1602-pr3-model-read-guards: Cases are never built for a model named "none" or judged inside the solver chain

## Intent

PR 3 of 7 for OME-1602. The replay child sets `INSPECT_EVAL_MODEL=none/none`, and
`get_model()` then returns a model named "none" rather than raising, as the code comment
claimed. A solver or task function that reads the model freezes Cases cut or worded for
"none" (F3): InfiniteBench cuts inputs to about 446k characters, and persistbench writes
"none" into its prompts. Separately, a judge inside the solver chain passes capture and then
fails every Case at grading (F4, air_bench). This unit refuses both by name and adds no
Benchmark.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/capture.py`: record every model
  read during capture and refuse it, with mmlu's max_tokens read exempt by module and function;
  an import-only second "answered" pass refuses a chain that asks for any model after the answer.
- `import_replay.py`: watch the task function and run the answered pass at import.
- `task_replay.py`: watch the task function at image-build replay too; fix the false comment.
- `tests/unit/inspect/test_capture.py`: one test per shape, plus the exemptions and rewrites
  that must still pass.

## Test plan

- A solver reading `get_model().name` or `str(state.model)` is refused; mmlu's read stays exempt.
- A task function reading the model is refused, in the image-build child and in the import child.
- A second generate, a model read after the answer, and a judge fetched by role or by name after
  the answer are refused; post-answer parsing and rewrites still pass; a judge after a real reply
  still passes the blank capture.

## Acceptance

- infinite_bench_math_find and persistbench are refused (F3); air_bench is refused (F4).
- No existing row's Case or Case Digest moves; image-build replay skips the answered pass.
- The named test files, ruff, and both pyright passes are green.

## Outcome

- **Actual files:** as planned.
- **Commits:** one feature commit (F3, F4 and their review fixes), plus this ledger.
- **Gates:** `test_capture.py`, `test_import_replay.py`, `test_task_replay.py`,
  `test_importer_named_scores.py`: 142 passed. ruff check and format, pyright, and extra-less
  pyright on the touched files: clean.
- **Blast radius:** all 65 Task-replay rows captured under the new watch with 0 refusals; mmlu
  (13,937 Samples) and math (5,000) in full; gdpval-text could not be built locally
  (`pdfplumber` missing).
- **Deviations:** the answered pass uses a Python profiling hook so it sees `get_model` calls
  the eval bound by name at import; an independent review asked for role and by-name fetches
  to be caught.
- **Owner verify:** PR 4 needs the owner's call on exempting infinite_bench_math_find, whose
  Cases are identical under every model name (inputs 116,289 to 120,155 characters).
