---
ticket: none yet (epic OME-1314; no Linear issue in this unit)
stack: screamingface-engine
status: in-progress
started: 2026-11-13
finished:
---

# keda-217-runner-target — runner autoscaling works on KEDA 2.17

## Goal

The AKS add-on runs KEDA 2.17.2. Its ScaledObject CRD drops `behavior.scaleUp.tolerance`, which
the chart renders since PR #1738. The HPA then uses its default 10 % band, and the runner pool
stalls: 3 pods of 4 slots at demand 13 stay at 3. This unit adds two chart values that work on
KEDA 2.17 without changing the default render.

Source: https://github.com/ScreamingFace/screamingface/pull/1738#issuecomment-6830194905 (U1 of
the platform follow-up plan, 2026-11-12).

## Facts

- AKS KEDA add-on = KEDA v2.17.2. Its ScaledObject CRD has no `behavior.scaleUp.tolerance`
  (KEDA 2.18.0 adds it). The API server prunes the field.
- With the field pruned, the HPA holds 3 pods at demand 13 with 4 slots (13/12 = 1.083).
- With a per-pod target of 3.6, the usage ratio is at least 4 / 3.6 = 1.111 whenever demand is
  above pods × slots. That is above the 1.1 band, so the HPA always scales up.

## Decisions

- `runnerPool.autoscaling.targetPerPod` (new, default `null` = `workerSlots`). The chart refuses a
  value above `workerSlots` and a value of 0 or less (schema `exclusiveMinimum: 0`).
- `runnerPool.autoscaling.scaleDown.enabled` (new, default `true`). `false` renders
  `selectPolicy: Disabled`. The key is not required in the schema, so old values files stay valid.
- Scale-down off is an interim until OME-1871 (idle pods first). It is better than `min = max`:
  the pool starts at `minReplicas` and grows with demand.
- Default render (autoscaling off) stays byte-identical. The only differences in a full
  `helm template` run are the generated `jwt-secret` and its checksum, which change on every run.

## Files

- `apps/screamingface-engine/deploy/helm/values.yaml`
- `apps/screamingface-engine/deploy/helm/values.schema.json`
- `apps/screamingface-engine/deploy/helm/templates/scaledobject-runner.yaml`
- `apps/screamingface-engine/deploy/helm/templates/deployment-runner.yaml`
- `apps/screamingface-engine/deploy/helm/README.md`
- `apps/screamingface-engine/CHANGELOG.md`
- `docs/spec/2026-11-10-runner-pool-autoscaling.md` (new D8, interim note, prerequisite 8)
- `apps/screamingface-engine/tests/unit/test_chart_render_runner_target_and_scaledown.py` (new)

## Gates

Targeted checks (run in this unit):

- `pytest` on the new test file and the two existing chart test files: 30 passed.
- `ruff check` and `ruff format --check` on the new test file: clean.
- `pyright` on the new test file: 0 errors.
- `helm template` default render compared with the origin/main baseline: same, apart from the
  random `jwt-secret` and its checksum.

Not run in this unit (orchestrator to run before commit):

- `run_gates.py screamingface-engine`
- `run_gates.py repo`
- `verify_chart_wiring.py`

## Status

Code, tests and docs are written. The targeted checks pass. The full gates have not run, and the
unit is not committed. No PR and no Linear issue exist yet.
