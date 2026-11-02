---
ticket: OME-1327
stack: screamingface-engine
status: done
started: 2026-10-26
finished: 2026-10-26
---

# lab-bench-figqa-tableqa — import LAB-Bench FigQA and TableQA, the two picture subsets

## Intent

LAB-Bench has eight subsets; the six text ones are Benchmarks since OME-1264. FigQA (a figure
and a question about it) and TableQA (one to three pictures of tables and a question) were left
out because a Case could not carry a picture. OME-1271 PR 2 (#1554) lets the importer save an
eval's pictures inside the Case, so these two are now plain data rows, imported exactly like
their six siblings: same eval, same pinned dataset commit, same policy seeds (7 and 7), same
scorer. Stacked on #1554; it merges after it.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`,
  `.../benchmarks.py` — the two rows the importer writes; the prose, provenance and baselines
  filled by hand from the six siblings and the LAB-Bench paper.
- The per-Benchmark test tables, one row each: `test_benchmark_declaration.py`,
  `test_failure_policy_rows.py` (and its row counts), `test_inspect_imported_benchmarks.py`,
  `test_published_revisions.py`, `test_benchmark_fingerprints.py`.
- `.claude/test-change-approvals/OME-1327.json` for those prior-test edits.
- `docs/tasks/` mirror for OME-1327.

## Test plan

- The shared Benchmark suites register both keys and check their declaration, family, policy,
  published revision and fingerprint (extending the tables is the test change).
- The build-side replay reproduces the Case Digest with every pin forced (the importer's own
  second run).

## Acceptance

- Both rows registered as `inspect-lab_bench_figqa` / `inspect-lab_bench_tableqa`, 181 and 244
  Cases, licence cc-by-sa-4.0 as the siblings, no TODO left, no check surface.
- Relevant inspect-lane tests, ruff and pyright green on the touched files.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `tests/unit/inspect/test_inspect_task_replay_benchmarks.py`:
  its LAB-Bench choice-order test runs over every `lab_bench_` row, so its eight stand-in rows
  gained a `figure` and a `tables` field (a bare JPEG and PNG file start) for the new loaders.
- **Commits:** the one commit on `OME-1327-lab-bench-figqa-tableqa`, stacked on #1554.
- **Import (2026-10-26, real Hub data at `futurehouse/lab-bench` `5c77cec6`):** FigQA 181
  Cases, Case Digest `616aeb49…`, 84 s; TableQA 244 Cases, `9be147a0…`, 59 s; both replays
  agreed. The importer peaked at 4.8 GB (FigQA) and 2.1 GB (TableQA) resident on the laptop;
  that is import time, not a run. Published revisions from `benchmark_bump.py`:
  `7376109d25378310` and `9990079555f06a35`.
- **Gates:** 22 test files that check every Benchmark row (declaration, fingerprints, published
  revisions, failure policy, provenance, task-replay rows and assembly, imported-benchmark
  suites, catalogue activity and others) 1,347 passed with the inspect extra; the extra-less
  catalogue files 73 passed. ruff, ruff format and pyright (with and without the extra) clean on
  the 8 touched Python files.
- **Baselines (read from the sources, not summaries):** humans 0.77 FigQA and 0.84 TableQA
  (LAB-Bench Appendix B, Table 2). FigQA frontier: Claude Mythos 5, 0.889 without tools, same
  181 public questions (its system card, 2026-06). TableQA frontier: Claude 3.5 Sonnet 0.83 (the
  LAB-Bench paper); the system cards checked report FigQA only.
- **Deviations:** tier `medium` for both, not the siblings' `hard`: by the tier rule ("hard" =
  today's best models visibly fail), FigQA's best is 0.889 and TableQA's 0.83. Owner to confirm.
- **Owner verify:** merge after #1554. On the first paid FigQA run, read the run's peak memory
  against the 2,560 MiB budget; loading only the selected Cases (OME-1675) is the fix if over.
