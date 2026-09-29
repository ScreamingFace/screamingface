# Spec — bake the exact questions an inspect eval keeps after loading (task route)

- Status: approved for build (user, 2026-09-29: "implement OME-1269").
- Component: `apps/screamingface-engine` (`screamingface_engine_inspect`).
- Ticket: OME-1269 (absorbs OME-1270). Parent epic: OME-1299.
- Ledger: `docs/work/2026-09-29-inspect-task-route-bake.md`. Plan:
  `docs/plan/2026-09-29-inspect-task-route-bake.md`.
- Scope of THIS unit: PR 1 of the ticket's 3-PR stack. It adds the mechanism only, with no new
  board. PR 2 adds the `onet_m6` and `pubmedqa` boards. PR 3 adds the CI token and the two
  `xstest` boards.

## 1. Problem

Some inspect evals drop questions AFTER they load the dataset: the task function calls
`dataset.filter(...)` with a lambda. The importer probes a task with one dummy question. The
dummy has no id and no metadata, so every keep-test drops it, and inspect then raises
`ValueError: The specified dataset is empty` before the importer can read the task. The bake
also has no step that runs such a filter, so a hand-written row would bake every raw row: a
different exam from the one inspect runs.

Evidence (spike 2026-09-29, inspect-evals 0.20.0): onet_m6 435 → 397, pubmedqa 1000 → 500,
xstest safe 450 → 250, xstest unsafe 450 → 200. The route below reproduces the same ids and
the same input, target and choices for all four.

## 2. Requirements

- R1. A `SnapshotSpec` row can name the eval's task function (`task`, a `"module:attr"`
  reference) and its arguments (`task_args`). The bake then gives the task this board's
  pinned, converted, seed-ordered samples in place of its `hf_dataset` load, calls the task,
  and keeps exactly the samples the Task holds. The eval's filter runs; we never copy it.
- R2. On a task-route row, `case_count` is the KEPT count, and the bake enforces it after the
  route step. The raw-row check does not apply to that row.
- R3. The route step refuses by name (never bakes) when:
  the task module has no `hf_dataset` binding; the task raises; the task calls `hf_dataset`
  a number of times other than one; or the kept samples are not an in-order subset of the
  samples we gave it (the task added, reordered or duplicated a sample).
- R4. `task` and `task_args` join the board's revision pins only when `task` is set. Every
  live board keeps its revision and its baked assets byte for byte.
- R5. The importer detects a filter on the exam load. The probe's stub records each
  `filter` predicate and keeps the dummy, so the task still builds. A filter that is not
  inspect_evals' duplicate-id remover
  (`inspect_evals.utils.deps_utils:filter_duplicate_ids.<locals>.is_unique_id`) marks the
  import as a task route. A filter on a different load (a fewshot load) is ignored.
- R6. A task-route import emits `task=` and, when not empty, `task_args=` on the
  `SnapshotSpec` row. Its case count is the kept count: the importer downloads the pinned
  rows, converts them, and runs the route step.
- R7. The importer refuses by name a task-route import that also (a) loads more than one
  dataset (the route hands the same samples to every load), or (b) has an upstream-seeded
  choice shuffle (upstream draws each case's choice order over all rows before the filter,
  the bake over the kept rows).
- R8. Dedupe-only tasks (wmdp_bio, wmdp_chem, wmdp_cyber, mmlu, race_h, winogrande with
  `fewshot=0`) import exactly as today, with no `task=` field.

## 3. Out of scope (this unit)

- New boards (PR 2, PR 3). The CI token and the `Dockerfile.benchmark` secret (PR 3).
- Post-load trims other than `.filter()` (slicing, sort then truncate). The ticket lists
  this as a known limitation.
