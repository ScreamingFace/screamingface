# OME-1648 — Plan: raise the per-run memory budget to 2.5 GiB

Spec: `docs/spec/2026-10-19-OME-1648-contracteval-run-memory-budget.md`.
Ledger: `docs/work/2026-10-19-contracteval-run-memory-budget.md`.

## Steps

1. RED — add a new test in `apps/screamingface-engine/tests/unit/test_chart_render_runner_memory.py`:
   `test_the_default_budget_fits_contracteval_s_measured_case_load`. Render the chart defaults and assert:
   - the resident budget is at least 1,828 MiB × 1.25 (the spec INVARIANT);
   - the resident budget is 2,560 MiB and the backstop is 5 GiB;
   - `workerSlots` is 4, the limit is 10,496 Mi and the request is 1,540 Mi.
2. Change the prior test that pins the old budget (owner approved 2026-10-19, rule 5):
   `test_the_per_slot_charge_is_each_run_s_resident_budget_and_sets_its_backstop`: 1024 → 2560.
   `test_the_memory_request_counts_each_warm_child` stays as it is (4 slots, 1,540 Mi).
3. GREEN — `apps/screamingface-engine/deploy/helm/values.yaml`: `perRunCharge.memoryLimitMi: 2560`.
   Update the WHY comments for `memoryLimitMi` and `addressSpaceFactor`.
4. Docs:
   - `deploy/helm/values.schema.json` descriptions (`memoryLimitMi`, `addressSpaceFactor`).
   - `deploy/helm/README.md` (the per-slot memory bullet).
5. Verify:
   - `helm lint` and `helm template` on the chart.
   - `run_gates.py screamingface-engine` and `run_gates.py repo` (the mirror-status gate).
   - kind: `helm upgrade --set` the new defaults and run the 3-case ContractEval solo again
     ($0 from the cache). Then roll back.
6. Ledger outcome, then commit (`fix(chart): …`). PR at the owner's word: rename the branch to
   `OME-1648-contracteval-run-memory-budget`, put `Refs: OME-1648` in the PR body.
7. Follow-up issue for selective case loading: file at PR-open, under epic OME-1314, after the
   owner confirms.
