---
ticket: OME-1273
stack: screamingface-engine
status: done
started: 2026-10-02
finished: 2026-10-02
---

# ome-1273-capture-rendering — render Task-replay Cases by running the eval's own solver chain

## Intent

A Task-replay Imported Benchmark's Cases must be byte for byte what inspect sends the model.
Today the image-side child reads `task.dataset` and renders each Sample with our own writer,
which imitates the two solvers it knows (`prompt_template`, `multiple_choice`) from fields on
the declaration. An eval that chains them (sevenllm: `prompt_template(TEMPLATE)` then
`multiple_choice()`) got the second solver only, and both replays agreed because both ran the
same wrong writer. This unit replaces imitation with capture: the child runs the Task's real
`setup` and `solver` on each Sample with a stand-in `generate` that records the messages and
answers nothing. The declaration loses its three template fields. inspect's `eval()`, a model,
a scorer, a Judge, a sandbox and tools still never run. Owner direction, 2026-10-02 (OME-1273
plan step 6).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/capture.py` — NEW: the stand-in
  `generate`, the per-Sample solver run, the message-to-text rule, the named refusals, and
  `captured_case_records(task, spec)`.
- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py` — `TaskReplayCasesSpec`
  loses `prompt_template`, `choice_template`, `system_message`; `case_records` serves the
  Hugging Face path only; the per-Case record builder is shared with capture.
- `apps/screamingface-engine/src/screamingface_engine_inspect/task_replay.py` — the child calls
  `captured_case_records` instead of `case_records`; module docstring says what runs.
- `apps/screamingface-engine/tests/unit/inspect/test_capture.py` — NEW.
- `docs/spec/2026-09-30-OME-1273-task-replay-import.md` — R2, R9 and the Runs / Taken / Never
  runs table amended to capture; two Known limitations added.
- `docs/plan/2026-10-02-OME-1273-capture-rendering.md` — NEW, this unit's plan.
- `docs/tasks/2026-09-23-OME-1273-task-replay-import.md` — mirror note.

## Test plan

- A `prompt_template(T)` then `multiple_choice()` chain yields the Case inspect would send
  (hand-written expected text), with the choices and target as Grading Material.
- `system_message(S)` then `generate()` yields the system text as leading text.
- `prompt_template` substitutes Sample metadata (a field the imitation writer never saw).
- `Task(setup=…)` runs before the solver.
- A Task with no solver (inspect's default `generate()`) yields the raw input, as today.
- Refused by name, each with the Case number: the solver never calls `generate`; it calls it
  twice; it gives the model tools; the Task declares a sandbox; the prompt is multi-turn or
  carries non-text content; the solver reorders the choices; the solver raises.
- The image-side child (`replayed_cases`) renders the chained shape, so both replays capture.
- Every prior Task-replay test stays green unchanged.

## Acceptance

- sevenllm's shape (`prompt_template` → `multiple_choice`) renders byte-identical to inspect's
  own solvers; the test's expected text is a literal, not a call into our code.
- `TaskReplayCasesSpec` has no template field; `grep prompt_template task_replay.py` is empty.
- `uv run .claude/scripts/run_gates.py screamingface-engine` green.
- No Hugging Face-path Benchmark's revision moves (`test_published_revisions.py` unchanged).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. `capture.py` (new, 230 lines), `prepare.py` (declaration
  trimmed, `case_records` narrowed to `CasesSpec`, new shared `prepared_case`),
  `task_replay.py` (child calls `captured_case_records`), `tests/unit/inspect/test_capture.py`
  (new, 22 tests), the spec, this plan, the OME-1273 mirror note.
- **Commits:** see the PR; one `feat(screamingface-engine)` commit carries code, tests and docs.
- **Gates:** `run_gates.py screamingface-engine` ALL GATES GREEN (append-only, ruff, format,
  pyright, layering, pytest with coverage ≥ 80). Two reds on the way: one E501 in a docstring,
  one pyright mismatch with inspect's `Generate` signature (the stand-in now takes
  `tool_calls` and ignores it).
- **Deviations:** none from the plan. One design call made here: the stand-in answers with an
  empty `ModelOutput` instead of stopping the chain at the first `generate`, so a chain that
  asks twice is seen (and refused) rather than hidden; post-answer solver work runs on a blank
  reply, and a solver that raises on it is refused with its error.
- **Review fixes (2026-10-02):** the child's environment sets `INSPECT_EVAL_MODEL=none/none`
  so a solver calling `get_model()` is refused instead of a real model's words landing in a
  Case (reproduced with mockllm before the fix); the stand-in deep-copies the messages it
  records; each Sample gets its own store and active state and a deep-copied Sample, as
  inspect's sample runner does; a one-message list input is accepted; the macOS cache note
  in task_replay.py was wrong at this platformdirs pin and now says so.
- **Owner-verify:** none pending. No paid run, no deploy; main has zero Task-replay Benchmarks,
  so no Case re-seals. PR #1191 rebases onto this branch and drops its template facts next.
