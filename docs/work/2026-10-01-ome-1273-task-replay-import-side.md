---
ticket: OME-1273
stack: screamingface-engine
status: done
started: 2026-10-01
finished: 2026-10-01
---

# ome-1273-task-replay-import-side — the importer imports an eval by Task replay

## Intent

Teach the importer to import an eval by Task replay: call its task function in a clean child,
record every Case Source, seal the Cases with a Case Digest that two runs agree on (the second
run through the image-side path), and write the `TaskReplayCasesSpec` declaration plus its
`BenchmarkSpec` row. This is PR 3 of the OME-1273 stack; the plan is
`docs/plan/2026-10-01-OME-1273-task-replay-import-side.md` (Tasks 0–8, decisions D1–D13).

## Planned changes

- `apps/screamingface-engine/tests/unit/inspect/conftest.py` (new: `no_network` fixture)
- `apps/screamingface-engine/src/screamingface_engine_inspect/case_sources.py` (new: the Case Source recorder)
- `apps/screamingface-engine/src/screamingface_engine_inspect/import_replay.py` (new: the import child and the double run)
- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py` (`TaskReplayRoute`, Task-replay renderers, CLI path, license lookup)
- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py` (`license` field, `LICENSE_TODO`, registry anchor)
- `CONTEXT.md` (glossary: Task replay)
- `docs/spec/2026-09-30-OME-1273-task-replay-import.md` (amendments from recon)
- Tests: `test_no_network_fixture.py`, `test_case_sources.py`, `test_import_replay.py` (new);
  `test_inspect_importer.py`, `test_inspect_imported_benchmarks.py` (append only)

## Test plan

- `no_network` refuses outbound connections and DNS, keeps loopback.
- Recorder: one Case Source per top-level fetch; names bound before install are rebound; a
  read from the replay cache is not a Case Source; uninstall puts every primitive back.
- Import child: Cases, Case Sources, facts; both MCQ witnesses; an eval's own scorer keeps
  Sample metadata; the import and image children render the same Cases.
- Double run: each R4 refusal by name; id-less Samples are not duplicates; run 2 takes the
  image-side path.
- Rendering: task args render as Python that evaluates back to the same value; a Hugging Face
  source renders a web `dataset_url`; the Hugging Face rows stay byte-identical.
- CLI: the four routes and `--task-replay` take the Task-replay path; an uncleared card
  license is written as TODO.

## Acceptance

- Spec Acceptance 1 (PR 3's part), 2 and 4.
- `tests/unit/inspect/test_published_revisions.py` passes unchanged; no published Benchmark
  Revision moves.
- Gates green: `uv run .claude/scripts/run_gates.py screamingface-engine`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `src/screamingface_engine_inspect/task_replay_rows.py` and
  `tests/unit/inspect/test_task_replay_rows.py` (the renderers and the license lookup, moved out
  of `importer.py`); `CONTEXT.md` gains **Task replay**.
- **Commits:** 4b7ace92 no_network fixture · 68ab82c6 Case Source recorder · e01cac1f import
  child · 8537ef33 the four routes · 5b3f8c4d double run and R4 refusals · 4f332443 generated
  declaration · 9f140152 CLI path and license rule · then the docs commit (spec amendments,
  glossary, mirror progress, this outcome).
- **Gates:** `run_gates.py screamingface-engine` → ALL GATES GREEN (append-only, ruff, format,
  pyright, layering, pytest with coverage ≥ 80); `tests/unit/inspect` 603 passed;
  `test_published_revisions.py` unchanged and green.
- **Deviations:**
  - Amended 2026-10-02 after PR #1219 (capture rendering): the import child renders by
    `captured_case_records`, not the imitation writer; `TaskReplayFacts` lost its three
    template references and the "unreproduced solver" flags; the declaration row writes no
    template field; the MCQ witness is a solver walk of its own (`_uses_multiple_choice`),
    because the Hugging Face reader's walk also refuses chains capture renders fine.
  - Plan review folded in first (8e8b0bbb): D11 `keep_sample_metadata` for an eval's own scorer,
    D12 `--task-replay`, D13 uncleared card license → TODO; task args render as Python, not
    JSON (Review Focus 6); both MCQ witnesses (7); web `dataset_url` (8); recorder
    `uninstall()`; id-less Samples never collide.
  - Renderers in `task_replay_rows.py`, not `importer.py` (size, and no import cycle).
  - Case Source comments are two lines (`comment_lines`) so generated files pass the
    100-column gate; `as_comment()` is the one-line form the CLI prints.
  - The recorder binds calls to each primitive's signature (`_download_remote` takes
    `remote_url`, not `url` as the plan assumed).
  - A `file`-only source writes `dataset_url="TODO"` (the field is required), not an omitted line.
  - The plan's stand-in eval had two bugs, both fixed in the tests: inspect's `FieldSpec`
    reads `choices` and `id` columns by default; MCQ targets must be letters.
  - "No Samples": inspect's `Task` refuses an empty dataset first; its reason reaches the
    importer intact, and our own check stays as a backstop.
  - Gates ran once on the finished branch, not before each task's commit; each commit ran
    ruff, format and pyright on its files plus its tests.
  - The branch is ~2,570 lines (≈1,000 source, ≈1,500 tests), over the spec's ~500-line PR cap;
    the owner chose one PR anyway (2026-10-01), with no review-agent pass.
  - After PR-open, two fixes from PR 4's first real import (b357437b): a Task-replay refusal
    from `python -m …importer` escaped as a traceback (`__main__` held a second ImporterError
    class), and our own solver-flag wording was refused as code; plus two write tests moved
    off the sample key `agieval_lsat_ar`, which PR 4 makes a real Benchmark (owner granted
    `--skip-append-only` for that commit, 2026-10-01).
  - CI typechecks without the `inspect` extra (`uv sync --dev`), where `inspect_evals.__file__`
    types as `str | None`; the recorder now guards it, and one test line changed with the
    owner's `--skip-append-only` grant. Reproduce with an extra-less venv:
    `UV_PROJECT_ENVIRONMENT=<tmp> uv sync --dev --frozen && … uv run pyright`.
- **Owner-verify:** run the importer for `agieval_lsat_ar` locally before PR 4 (the first real
  fetch; nothing here touched the network).
