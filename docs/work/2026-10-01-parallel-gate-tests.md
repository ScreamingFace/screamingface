---
ticket: OME-1444
stack: screamingface + screamingface-engine
status: done
started: 2026-10-01
finished: 2026-10-01
---

# parallel-gate-tests — the Engine and SDK gate test steps spread across every core

## Intent

The pre-push hook runs the Engine gate on every push of an Engine branch, and the SDK gate is
run by hand before an SDK push. Both test steps run every test one after another on a single
core, so a developer waits on the full serial suite every push, once per branch in a stack and
again after every rebase. This unit adds `pytest-xdist` to both dev groups and runs both gate
test steps with `-n auto`: the same tests, the same coverage floors, spread across the cores.

## Planned changes

- `apps/screamingface-engine/pyproject.toml` + `uv.lock`: `pytest-xdist` in the `dev` group.
- `packages/screamingface/pyproject.toml` + `uv.lock`: same.
- `.claude/sdlc.local.md`: the Engine and SDK `pytest --cov…` gate lines gain `-n auto`.
- Any test that fails only in parallel: fixed, or pinned to one worker with `xdist_group` —
  never skipped or deleted.

## Test plan

- Baseline: both gate test steps serial, on main's tree, same machine — record wall time,
  passed/skipped counts, coverage total.
- After: the same commands with `-n auto` — same passed/skipped counts, coverage at or above
  the floors (80 Engine, 95 SDK), wall time recorded.
- Run the parallel suites more than once to flush out order-dependent flakes.

## Acceptance

- Engine and SDK gates green with `-n auto`, same test count as the serial run, same floors.
- Before/after wall time for each gate test step in the PR body.
- No test skipped or deleted to make the parallel run pass.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, no test changes. Both gate lines also take
  `--dist worksteal` (see Deviations). Owner-approved mid-review: the same flags on the CI test
  steps of `.github/workflows/screamingface-engine-tests.yml` and `screamingface-tests.yml`.
- **Commits:** `chore(repo): run the Engine and SDK gate tests across every core`;
  `ci: run the Engine and SDK CI test steps across every runner core`.
- **Gates:** measured on a 16-core Mac, same tree, test step only (`/usr/bin/time` real):

  | Suite | Serial | `-n auto` (load) | `-n auto --dist worksteal` | Counts (every run) | Coverage |
  |---|---|---|---|---|---|
  | Engine | 103.6s | 22.1s | 18.2 / 18.9 / 18.7s | 4367 passed, 66 skipped | 93.89% (one run 93.90%) |
  | SDK | 330.2s | 207.7s | 109.6s | 2083 passed, 26 skipped | 96.20% |

  `run_gates.py screamingface` all green (test step on worksteal); `run_gates.py repo` green
  once this ledger closed (its only blocker was this unit's own open ledger vs done mirror).
  The Engine gate runs from the pre-push hook on push.
- **Deviations:** `--dist worksteal` added. Under the default `load` scheduler the SDK's two
  ~95s disconnect tests (`tests/test_client_protocol.py`) queued on one worker, so the step
  took 208s; worksteal lets an idle worker take the second, bringing it to ~110s, about the
  slowest single test. Those two tests are now the SDK gate's floor; making them faster is
  test-side work outside this unit.
- **CI** (push-event runs, same base, pytest's own time, py3.12 / py3.13): Engine 237s / 143s →
  127s / 93s on 4 workers; SDK 387s / 314s → 234s / 263s on 2 workers. Counts identical
  (Engine 4368 passed, 65 skipped; SDK 2083 passed, 26 skipped). The SDK runners get 2 cores, so
  its gain is smaller.
