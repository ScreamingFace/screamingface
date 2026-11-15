---
ticket: OME-1816
stack: screamingface-engine
status: done
started: 2026-10-31
finished: 2026-10-31
---

# run-rss-logging — log a run's resident memory (current + peak) at start, Cases load, end

## Intent

A FigQA run on fusion.dev was killed at 2,862 MiB; measurement explains ~2.1 GiB of it, leaving
~0.7 GiB unexplained (probably idle process size plus the supervisor's 2 s sampling). Log the
run process's own resident memory — current and peak — at run start, right after the Cases
load, and at run end, so the next such run states its baseline and its Cases cost directly.
Diagnostics only: standard library, no prompt or Case content in any line.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/process_memory.py` (new): current RSS
  from `/proc/self/statm` (None where absent — macOS), peak from `resource.getrusage`
  (KiB on Linux, bytes on macOS), and one `log_process_memory(point, **counts)` line.
- `apps/screamingface-engine/src/screamingface_engine/runner/main.py`: `run_start` before
  `run(...)`, `run_end` in the `finally` of `_run_and_log` (inside `run_scope`, so the line
  carries topic + trace id).
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/case_selection.py`:
  `cases_loaded` (with the Case count only) right after the shared Cases route validates.
- Tests: `apps/screamingface-engine/tests/unit/test_process_memory.py` (new).

## Test plan

- statm parsing: resident pages x page size; missing/garbled file -> None.
- peak: Linux KiB -> bytes; macOS bytes kept.
- log line: point, rss/peak MiB, `unknown` when current RSS is unreadable; never raises.
- wiring: `_run_and_log` logs `run_start` then `run_end` (also on a failed run);
  `cases_handler` logs `cases_loaded cases=N` and no Case input text; a bad selection logs
  nothing.

## Acceptance

- Three INFO lines per run on the `screamingface_engine.process_memory` logger, no content.
- `run_gates.py screamingface-engine --base origin/main` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `process_memory.py` (new), `runner/main.py`,
  `benchmarks/case_selection.py`, `tests/unit/test_process_memory.py` (new, 15 tests).
- **Commits:** see branch `run-rss-logging` — `feat(engine): log the run's resident memory at
  start, after the Cases load, and at end`.
- **Gates:** `run_gates.py screamingface-engine --base origin/main` — ALL GATES GREEN
  (append-only, ruff, format, pyright, layering, pytest+coverage; 6264 passed, 157 skipped).
- **Deviations:** no span attributes — the engine has no in-process spans; spans are built
  from stream frames by `tracing.relay`, so adding them means a new frame/attribute contract
  (out of scope). macOS "fallback" is `rss_mib=unknown` (stdlib has no current-RSS call
  there); peak works on both (ru_maxrss unit normalised). Measures this process only, not
  the process tree the worker budgets.
- **2026-11-03 PR prep:** merged `origin/main` (normal merge; one import-only conflict in
  `case_selection.py`, resolved as the union). Main had since added `board_cases_handler`
  (OME-1790), the route Imported Boards — FigQA included — load Cases through, so
  `cases_loaded` would never have fired for FigQA; added the same line there (selected count
  only) plus 2 appended tests in `test_process_memory.py`. Checked #1622/#1628/#1629: they
  reduce memory, none logs process RSS (`worker.memory_watch` samples the tree, unchanged), so
  no duplication. Gates re-run: `run_gates.py screamingface-engine --base origin/main` — ALL
  GATES GREEN.
- **Merged:** PR #1656, squash `27fc73f9a`, 2026-11-04. Merging main (#1636) dropped the `count` local, so `cases_loaded` now logs `cases=selection.count` in `board_cases_handler` (merge `f31c32e1a`).
