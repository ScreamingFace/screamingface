# Plan — task-route bake (OME-1269, PR 1 of 3)

Spec: `docs/spec/2026-09-29-inspect-task-route-bake.md`. Ledger:
`docs/work/2026-09-29-inspect-task-route-bake.md`. Paths are relative to
`apps/screamingface-engine/`.

## Step 1 — RED: bake tests (`tests/unit/inspect/test_inspect_snapshots.py`)

A fake eval module in `sys.modules` with `hf_dataset`, a row rule and a task that keeps
even ids.
- The bake keeps exactly the even-id cases, in pinned order; `case_count` is the kept count.
- The kept count is enforced (a wrong count refuses with "pinned case count").
- `task_args` reach the task (a `parity` arg picks odd instead of even).
- Refusals by name: a task that raises, a task that loads twice, a task that reorders.

## Step 2 — GREEN: `src/screamingface_engine_inspect/prepare.py`

- `SnapshotSpec.task: str | None`, `SnapshotSpec.task_args: dict[str, Any] | None`.
- `task_kept_samples(spec, samples)`: swap the task module's `hf_dataset`, call the task,
  check one load and the in-order subset, return the kept samples.
- `emit_snapshot`: the raw-row count check runs only without `task`; new Stage 3b runs the
  route and checks the kept count.
- `count_kept_cases(spec)`: load, convert, route, count (for the importer).

## Step 3 — `src/screamingface_engine_inspect/boards.py`

`_revision_pins`: add `task=` and `task_args=` pins only when `task` is set. Test: a spec with
`task` has different pins; `test_published_revisions.py` stays green (R4).

## Step 4 — RED then GREEN: importer (`tests/unit/inspect/test_inspect_importer.py`, `importer.py`)

- The stub records `filter` predicates and keeps the dummy.
- `_exam_dataset_kwargs` also returns the exam stub, so only its filters count.
- `TaskFacts.task_route`, `TaskFacts.task_args`; refusals for more than one load and for an
  upstream-seeded choice shuffle.
- `render_fragments` emits `task=` and `task_args=`; the injection guard covers the
  task_args strings.
- `_hub_count_rows` counts kept cases on a route (via `count_kept_cases`).
- Tests: toy filtered task gives a route row (not a `ValueError`); dedupe-only task stays on
  today's path; a filter on the fewshot load is ignored; filter plus two loads refuses by name.

## Step 5 — verify

- Gates: `ruff check`, `ruff format --check`, `pyright`, the inspect lane
  (`uv run --extra inspect pytest -q tests/unit/inspect`), and the extra-less suite.
- Free local check (public data, no token): run the route over the real onet_m6 and
  pubmedqa tasks and compare with inspect's own load (397 and 500).
- Byte-identical live boards: `_revision_pins` and `emit_snapshot` run the old code path
  when `task` is None (every live row). `test_published_revisions.py` and the existing
  snapshot tests pin this.
