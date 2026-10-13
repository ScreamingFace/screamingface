---
ticket: OME-1476
stack: screamingface-engine
status: done
started: 2026-10-12
finished: 2026-10-12
---

# OME-1476-pr1-arc-agi-2-local-task — ARC-AGI-2 public eval as a local inspect Task

## Intent

Serve ARC-AGI-2's public evaluation set (120 tasks, 167 test grids) as the second local inspect
Task, after MuSiQue. One Case is one test grid; the Candidate gets two Attempts per Case
(OME-1458) and the Case is solved if either reply's grid matches exactly. The headline averages
per ARC task, not per grid, through the Task's own whole-run metric (OME-1527), so a task with
two grids and one solved scores 0.5, as the ARC Prize scorer does. The prompt and reply parser
are copied verbatim from the ARC Prize harness (`arcprize/arc-agi-benchmarking@9e2828fb`, MIT);
the task files are fetched at Case Preparation from `arcprize/ARC-AGI-2@f3283f72` and
sha256-checked.

Owner decisions (2026-10-12): Case = one test grid; harness prompt + parser verbatim; download
from the pinned commit, nothing committed; one code PR, then a golden PR, then the owner's paid run.

Spec `docs/spec/2026-10-12-OME-1476-arc-agi-2.md` (D1–D7, approved 2026-10-12); plan
`docs/plan/2026-10-12-OME-1476-arc-agi-2.md`. D7 (2026-10-12): a partly failed task divides by
all its grids (`grids_in_task`); a fully failed task still drops out. `arc_per_task_accuracy`
RESTATES the harness's scoring rule (`scoring.py:122-127`, `:160-234`); it is not vendored.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/arc_agi_2/`:
  `__init__.py`, `arc_agi_2.py`, `README.md`, `schemas.py` (the one-class stand-in for the
  harness's `ARCPair`), `vendor/{__init__.py, LICENSE, system_prompt.txt, prompt_manager.py,
  parsing.py}` from `arcprize/arc-agi-benchmarking@9e2828fb`
- `apps/screamingface-engine/pyproject.toml` — vendor fences
- `src/screamingface_engine_inspect/benchmarks.py`, `prepare.py` — importer-written rows
- `tests/unit/inspect/test_local_task_arc_agi_2.py`, `test_local_task_arc_agi_2_vendor.py` — new
- `tests/unit/inspect/test_benchmark_declaration.py`, `test_inspect_imported_benchmarks.py`,
  `test_published_revisions.py` — one row each
- `tests/unit/inspect/test_whole_run_metric.py` — prior guard amended (approval file
  `.claude/test-change-approvals/OME-1476.json`)
- `tests/unit/test_attempt_egress.py` — append the `derive_attempt_seed` literal pin
- `apps/screamingface-engine/docs/adding-an-imported-benchmark.md` — raw-URL fetch + Attempts note
- `docs/tasks/2026-10-12-OME-1476-arc-agi-2.md` — mirror at PR-open

## Test plan

- RED per plan §RED tests 1–11: Sample shape + task order; prompt bytes = harness template;
  parser table; scorer exact / one-cell-off / no grid; conservation vs the harness rule incl. a
  failed grid; fully failed task drops out; missing metadata = plain mean; row declares
  attempts 2 / max / honour; url4 hash pin; seed literal pin; loader on a fake zip + wrong count.
- Vendor: header links + upstream code sha256 + the single import edit + licence.

## Acceptance

- Spec §7 items 1–6.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `test_task_replay_assembly.py` and
  `test_imported_catalogue_activity.py` (owner-approved generalisations), the notebook
  (`packages/screamingface/scripts/build_notebooks.py`, `examples/16_arc_agi_2.ipynb`) and
  `.claude/test-change-approvals/OME-1476.json`; minus `schemas.py`, `vendor/prompt_manager.py`
  and `vendor/system_prompt.txt` (prompt builder restated, see Deviations).
- **Commits:** `feat(screamingface-engine): serve ARC-AGI-2's public eval as a local Task with
  two Attempts (OME-1476, PR 1 of 2)` — sha in the PR.
- **Gates:** the relevant test files only (owner rule): the 2 new ARC files, the 7 edited test
  files, and the 16 catalogue-wide files that iterate every row — 1,260 passed; SDK notebook
  tests (`test_example_notebooks.py`, `test_notebook_version_provenance.py`,
  `test_default_client_evaluate_passthrough.py`) — 33 passed; ruff check + format and pyright
  on every touched file — clean; extra-less pyright on the touched Engine files and extra-less
  pytest on the 3 new/edited ARC files — clean (28 passed, 1 skipped). Full suites: pre-push
  hook + CI.
- **Deviations:**
  1. The prompt builder is restated in `arc_agi_2.py`, not vendored: `system_prompt.txt` ends
     with no newline and `prompt_manager.py` has a whitespace-only line, both rewritten by the
     repo's whitespace hooks. Pinned instead by the template's sha256 (= upstream file) and a
     fixture prompt's sha256 (= upstream builder output, computed from the harness at 9e2828fb).
  2. A failed Candidate Invocation fails the whole Case (OME-1458 limitation), found while
     building: one capped Attempt zeroes the grid even if the other was right. Spec F4, §4, the
     row description and the README now say so; the comparability rule is "no failed Case and
     no 'no grid found' Attempt".
  3. Notebook folded into PR 1 (the provenance conformance test requires the row's notebook to
     exist); the stack is 2 PRs, not 3 (owner, 2026-10-12).
  4. Two more catalogue-wide tests generalised (pin count skips local Tasks; activity counts
     scale by Attempts), owner-approved 2026-10-12.
- **Owner-verify:** the Frontier Score (0.925, GPT-5.6 Sol, semi-private, 2026-08) came from a
  secondary source because arcprize.org/leaderboard renders client-side; confirm it on the live
  leaderboard. The Case licence `apache-2.0` is the data repo's LICENSE; confirm. The paid run
  (set `max_tokens` ≥ 32,768) is the ticket's acceptance 4 and is still owed; this PR closes
  OME-1476 regardless (owner, 2026-10-12). Revisit when that run's cache dump exists: file the
  golden recording as its own ticket under OME-1457.
