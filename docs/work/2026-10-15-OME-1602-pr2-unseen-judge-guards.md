---
ticket: OME-1602
stack: screamingface-engine
status: done
started: 2026-10-14
finished: 2026-10-15
---

# OME-1602-pr2-unseen-judge-guards: the importer sees judges a scorer reaches without naming them

## Intent

PR 2 of 7 for OME-1602. Before this PR, a scorer that reaches a judge without naming it in its
arguments was read as judge-free. Its row then graded with a judge nobody pinned: on run pods,
which have no internet, every Case fails; on preview pods the call goes out unmetered. This
unit makes each such shape a named outcome (F2) and adds no Benchmark.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/judge_shape.py` (new): reads a
  scorer's source, plus every helper and re-export inside its root package, for judge
  parameters, `get_model(role=…)`, a bare `get_model()`, and a role held in a variable. What
  it cannot follow is reported unread, and unread counts as reaching a judge.
- `importer.py`: a grader role takes the judged path with a TODO judge; a panel, or the model
  under test, is refused; a judged extra scorer is dropped by name.
- `import_replay.py`, `task_replay_rows.py`: the child carries the role back, and the row
  renders a TODO judge with `model_role="grader"`.
- `benchmarks.py` `_check_judge_declaration`: refuses a panel kwarg, and a judge-free row whose
  scorer, or any extra scorer, reaches a judge.
- Tests: `test_judge_shape.py` (new), `test_importer_named_scores.py`,
  `test_judged_benchmark_assembly.py`.

## Test plan

- Each shape is read correctly: grader role, role one helper down, role held in a variable,
  model under test, panel, and `get_model(model)` not read as a judge.
- At import: grader role → TODO judge row; panel and model under test refused; a judged extra
  scorer dropped by name.
- At assembly: panel kwarg refused; judge-free row refused for a judge parameter, a grader role
  or an extra scorer reaching a judge; a judge-free scorer still assembles.
- The older judge-kwarg lists stay inside the new judge parameters.

## Acceptance

- simpleqa's scorer reads as judged by the grader role; fortress's panel is refused.
- Assembly refuses none of the 65 existing BenchmarkSpec rows.
- The named test files, ruff, and both pyright passes are green.

## Outcome

- **Actual files:** as planned.
- **Commits:** one feature commit (F2 plus its review fix), plus this ledger.
- **Gates:** `test_importer_named_scores.py`, `test_judge_shape.py`,
  `test_judged_benchmark_assembly.py`, `test_judge_grader_role.py`, `test_task_replay_rows.py`,
  `test_import_replay.py`: 179 passed. ruff check and format, pyright, and extra-less pyright
  on the touched files: clean.
- **Blast radius:** assembly over all 65 BenchmarkSpec rows refuses none; the judged rows it
  reads (frontierscience, gdpval-text, draco ×2) already pin a judge through `judge_model`, and
  their scorers ask for no role, so a re-import writes the same row.
- **Deviations:** the static reader moved out of `importer.py` into its own module during the
  build. An independent review found two missed shapes (a default judge on an extra scorer, a
  role held in a variable); both are fixed here, the variable case failing closed.
- **Second review (2026-10-15):** the reader still read "could not follow" as "judge-free".
  Fixed: a scorer it cannot find, a judge passed as a value (sciknoweval's lookup table), a
  judge named in the code, or one passed through a parameter no judge check reads is now
  unread, and refused. Helpers are followed to any depth (cti_realm's judge is two down),
  through `module.fn()` and an aliased `get_model`, and re-exports anywhere in the root package
  (aime2024 and aime2025 are now found, and read as judge-free). Roles are kept once each; the
  importer refuses a second role or any role but `grader`, and assembly re-reads a role-judged
  row's scorer for any other role. A judge parameter left at its default now gets the TODO
  judge at import. Over all 227 inspect_evals 0.20.0 scorers, 3 more now reach a judge
  (cti_realm ×2, sciknoweval); the 65 rows keep their judged/judge-free split. Two older
  assembly tests pointed at scorer modules that do not exist; they now name real judge-free
  scorers (contracteval, ifeval).
- **Gates after the second review:** the 38 test files that call the reader, the importer or
  assembly: 1256 passed. ruff check and format and pyright on the touched files: clean, apart
  from two unresolved imports that also fail on the unchanged files (`url4.peer.server` in
  benchmarks.py, `pytest` in test_judge_shape.py).
- **Owner verify:** none; nothing paid, no Benchmark changes.
