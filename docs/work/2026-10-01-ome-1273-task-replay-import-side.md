---
ticket: OME-1273
stack: screamingface-engine
status: in_progress
started: 2026-10-01
finished:
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

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
