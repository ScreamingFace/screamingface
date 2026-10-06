---
ticket: OME-1500
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-06
finished: 2026-10-06
---

# paid-benchmark-smoke — run the paid smoke over every Benchmark, not only the imported ones

## Intent

The owner-pressed paid smoke today runs only Imported Benchmarks (`origin == "inspect_evals"`).
The 8 hand-built Benchmarks (draco, draco-3pass, ifeval, healthbench-worst30,
healthbench-professional, gdpval-text, medxpert, contracteval) are never re-proven live after a
gateway or route refactor. This unit widens the smoke to every Benchmark the live Engine lists,
adds a `scope` choice to the button (`all` / `imported` / `hand-built`) so a press after an
inspect import need not pay the pro-tier Judges, raises the job timeout, and renames the lane
from "inspect" to "benchmark" (workflow, just recipe, test). Spec:
`docs/spec/2026-10-06-paid-benchmark-smoke.md`; plan: `docs/plan/2026-10-06-paid-benchmark-smoke.md`.

## Planned changes

- `.github/workflows/screamingface-paid-inspect-smoke.yml` → `screamingface-paid-benchmark-smoke.yml`
  (git mv): `scope` input, timeout 120 → 180, prepare every bundle, cache key covers the
  hand-built preparers, step names.
- `packages/screamingface/justfile`: `test-paid-inspect` → `test-paid-benchmarks scope="all"`,
  prepare every bundle, pass the scope.
- `packages/screamingface/tests/paid/_scope.py` (new): scope → origins, the shelf picker.
- `packages/screamingface/tests/paid/test_scope.py` (new): free tests of the picker.
- `packages/screamingface/tests/paid/test_imported_board_smoke.py`: picks Benchmarks through
  `_scope`; test renamed `test_every_benchmark_runs_end_to_end`.
- `packages/screamingface/tests/paid/conftest.py`: assets guard accepts any prepared bundle;
  wording.
- `packages/screamingface/tests/test_paid_lane_isolation.py`, `tests/conftest.py`: the renamed
  test/recipe names (prior-test edit, owner-approved with the plan).

## Test plan

- RED first, free (no spend): `test_scope.py`
  - unset scope means `all` (both origins);
  - `imported` keeps only `inspect_evals`, `hand-built` only `screamingface`;
  - an unknown scope value fails loudly naming the allowed values (a typo never runs an
    empty shelf green);
  - a selected origin with zero listed Benchmarks is reported as a problem (an engine booted
    without the inspect extra must not pass on the hand-built ones alone);
  - the picked ids keep the engine's listing order.
- `test_paid_lane_isolation.py` still proves the fence, with the new test name.
- The paid press itself is the owner's (never run by the agent).

## Acceptance

- One press with `scope=all` runs 8 hand-built + every imported Benchmark; `imported` and
  `hand-built` run only their own origin.
- A typo in the scope fails before any spend.
- All free tests in `tests/paid` + `tests/test_paid_lane_isolation.py` pass under
  `SCREAMINGFACE_TEST_PAID=1` with no key (gate tests only).
- `run_gates.py screamingface` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus one docstring line in `tests/paid/_board_summary.py` and
  `.claude/test-change-approvals/OME-1500.json` (the prior-test edits, pinned by blob).
- **Commits:** see PR; the feature commit is `feat(screamingface): run the paid smoke over every
  Benchmark, with a scope choice`.
- **Gates:** `run_gates.py screamingface --base <merge-base>` ALL GREEN (ruff, format, pyright,
  pytest with coverage ≥ 95, notebooks, build, distribution); the append-only check passes through
  the OME-1500 approvals file. Free paid-lane tests: all pass under `SCREAMINGFACE_TEST_PAID=1`
  with no key.
- **Deviations:**
  - The test module keeps its file name `test_imported_board_smoke.py`: the approvals mechanism
    pins edits to a file, never a rename (this also spared the four sibling import edits).
  - The 2026-10-06 press's one failure (`inspect-lab_bench_cloning_scenarios`, 0/2 graded: qwen
    spent all 32,768 tokens thinking on both Cases) is NOT fixed here. A teammate's PR #1256
    (OME-1496) already caps qwen at `reasoning_effort: "low"`; this PR leaves `_panel.py` alone so
    the two never conflict.
- **Owner-verify:** one `scope=all` press after #1256 merges. Check (a) the 8 hand-built + every
  imported Benchmark in the progress lines, (b) the total cost line, the first measurement of a
  full press, (c) the hand-built rows finish inside the 180-minute cap.
