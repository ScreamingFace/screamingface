---
ticket: OME-1648
stack: screamingface-engine
status: done
started: 2026-10-19
finished: 2026-10-19
---

# contracteval-run-memory-budget — raise the per-run memory budget to 2.5 GiB

## Intent

ContractEval cannot finish any run on prod: every run loads the whole 192 MiB `cases.json`
(4,182 full contracts), and the 1 GiB per-run budget stops it (measured on kind: 1,382 MiB at
1 GiB; completed at 2 GiB with a 1,828 MiB peak). The owner chose option (c) on 2026-10-19:
raise the default budget to 2,560 MiB now (4 slots kept; the owner will increase the node VM
capacity), and remove the fixed case-load cost in a follow-up issue. This unblocks the ContractEval part of OME-1606.

## Planned changes

- `apps/screamingface-engine/deploy/helm/values.yaml` — `perRunCharge.memoryLimitMi: 2560`,
  WHY comments.
- `apps/screamingface-engine/deploy/helm/values.schema.json` — descriptions.
- `apps/screamingface-engine/deploy/helm/README.md` — per-slot memory bullet.
- `apps/screamingface-engine/tests/unit/test_chart_render_runner_memory.py` — new test; change
  the prior test that pins the 1 GiB budget (owner approved 2026-10-19).
- Spec, plan and `docs/tasks` mirror for OME-1648.

## Test plan

- RED: `test_the_default_budget_fits_contracteval_s_measured_case_load` — defaults render a
  budget ≥ 1,828 MiB × 1.25, exactly 2,560 MiB resident / 5 GiB backstop, 4 slots, limit
  10,496 Mi, request 1,540 Mi. Fails on the current defaults.
- The formula tests (`test_chart_render_runner_pool.py:236-246`, the override test) stay
  unchanged and must stay green.

## Acceptance

- Chart lint/template and the engine gates are green.
- On kind with the new defaults, the 3-case ContractEval sample completes.
- After deploy: the 3-case sample completes on prod; full solo and fusion runs record peak RSS
  (OME-1648 acceptance; the fusion needs the `sota_open_only` url4).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `deploy/helm/values.yaml` (`memoryLimitMi: 2560` + WHY/AIDEV-NOTE comments),
  `deploy/helm/README.md`, `tests/unit/test_chart_render_runner_memory.py` (one new test, one
  approved prior-test change), `.claude/test-change-approvals/OME-1648.json`, spec, plan, ledger,
  `docs/tasks` mirror.
- **Commits:** see `git log` on `OME-1648-contracteval-run-memory-budget` (one `fix(chart)` commit).
- **Gates:** `run_gates.py screamingface-engine` ALL GATES GREEN (approved OME-1648 test
  transition); `run_gates.py repo` ALL GATES GREEN; `helm lint` 1 chart, 0 failed.
- **kind:** worktree chart with `memoryLimitMi=2560` (kind keeps its own 2 slots): the 3-case
  ContractEval solo (`gemini-3.8-flash`) completed, `ok=True`, no failures, 6.5 s, all calls
  from the cache ($0); child tree peak 1,870 MiB (73% of the budget). Rolled back afterwards.
- **Deviations:**
  - The owner changed the slot decision during the unit: 4 slots kept (not 2). So
    `test_chart_render_runner_pool.py` needed no change, and the pod limit becomes 10,496 Mi.
  - `values.schema.json` has no default numbers in its descriptions, so it needed no change.
  - The branch was renamed to `OME-1648-…` before PR-open, because the issue already exists
    and the test-change approval manifest is pinned to the branch name.
