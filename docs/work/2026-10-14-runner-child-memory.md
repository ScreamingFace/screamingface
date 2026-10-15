---
ticket: OME-1607
stack: screamingface-engine
status: in_progress
started: 2026-10-14
finished:
---

# runner-child-memory — large judged runs survive the runner child, and a dead child ends the client run

## Intent

A large judged benchmark run (`draco-3pass`) must finish inside one runner slot with the chart
defaults, and a run whose child dies must end on the client with an error instead of "waiting".
Today both fail on aks-dev and aks-prod. Evidence (local kind, exact replay of a failing run,
2026-10-14):

- Per-child `RLIMIT_AS` is 2 GiB (`config.py:24`, `worker/exec_wrapper.py:25`). At run start VSZ
  goes 218 → 1,884 MiB while RSS is about 300 MiB: one 1,024 MiB anonymous mapping (pyarrow
  default pool = mimalloc arena) + one 192 MiB mapping (numpy/OpenBLAS, about 32 MiB per CPU).
  The run died at VSZ 2,045 MiB / RSS 459 MiB.
- `ARROW_DEFAULT_MEMORY_POOL=system` + `OPENBLAS_NUM_THREADS=1` on the runner: the same run
  succeeded (peak VSZ about 915 MiB, RSS about 550 MiB).
- RSS grows linearly, about 35 KB per model call, through judging. Attributed: the aggregate
  keeps one asyncio Task per Case (`benchmark_aggregation.py:427`); each Task's Context keeps an
  inspect Transcript with every judge `ModelEvent` (full prompt). Proof and method in the spec.
- The supervisor's terminal frame uses `source_for(topic)` = `/trace/<topic>`
  (`worker/supervisor.py:1143`); the SDK ends only on the root node's source
  `/trace/<topic>/node/root` (`packages/screamingface/.../_engine/contract.py:295-296`).

## Planned changes

Spec: `docs/spec/2026-10-14-OME-1607-run-scheduling-memory.md` (scheduling map, evidence, edge
cases E1–E13, requirements R1–R7). Plan: `docs/plan/2026-10-14-OME-1607-runner-child-memory.md`
(units U1–U7 in three stacked PRs). Owner review of both before code.

## Test plan

- Supervisor: a child that exits non-zero yields a terminal frame whose source equals the root
  source the SDK tracks (test against the SDK's contract rule, not a string literal).
- Chart: `helm template` renders the env and the budget; schema rejects an invalid budget.
- Child: under the exec wrapper's `RLIMIT_AS`, importing pyarrow + numpy and allocating an Arrow
  table stays far below the budget with the runner environment set (Linux-only, like the existing
  cap test).

## Acceptance

- `draco-3pass` replay completes on the kind cluster with the chart defaults.
- A child death ends the client run with an error.
- `screamingface-engine` gates pass.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `worker/supervisor.py`, `worker/memory_watch.py` (new), `worker/loop.py`,
  `worker/metrics.py`, `config.py`, `subjects.py`, `runner/main.py`, `adapters/inprocess.py`,
  `benchmarks/shared_grading/benchmark_aggregation.py`, `screamingface_engine_inspect/scorer_adapter.py`;
  chart `values.yaml`, `values.schema.json`, `templates/configmap-runner-env.yaml`,
  `templates/deployment-runner.yaml`, `README.md`; tests `test_supervisor_terminal_root_source.py`,
  `test_worker_resident_memory_budget.py`, `test_concurrent_case_grading_memory.py`,
  `inspect/test_case_transcript_scope.py`, `test_chart_render_runner_memory.py`; docs: this ledger,
  the spec, the plan, the measurement, the task mirror. U6 dropped, U4 kept (plan §6).
- **Commits:** 04dac3392 fix(engine): worker terminal frames end the client run; per-run resident
  memory budget · cbaf6e0cf fix(engine): judged grading holds only the Cases near the clerk ·
  0d9dc57ef feat(chart): one per-slot memory value; runner children reserve no unused address
  space · d47a272c3 fix(engine): review fixes · (docs commit)
- **Gates:** `run_gates.py screamingface-engine --base origin/main` → ALL GATES GREEN (ruff,
  format, pyright, layering; 5,660 passed, 109 skipped, coverage 95.10%). inspect lane with the extra:
  1,737 passed. Chart rendered with the dev/staging/prod values of OpenMined/infrastructure.
- **Verification (kind):** `draco-3pass` replay succeeded, peak 444 MiB RSS / 849 MiB VSZ (was:
  `MemoryError` at 459 / 2,045); owner evaluation with 4 runs at once: children 300–463 MiB, pods
  ≤ 787 of 2,304 MiB. Measurement doc under `uniform-executor/measurements/`.
- **Deviations:** filed at work start at the owner's request (not at PR-open). One branch instead
  of three stacked PRs (owner). U3 redesigned after review (release-on-finish instead of a window).
  U6 dropped (SDK admission budget 900 s < draco run time). Owner-approved append-only exception
  for tests created earlier on this branch.
