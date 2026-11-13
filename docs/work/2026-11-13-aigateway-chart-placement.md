---
ticket: none yet (epic OME-1314; unit ticket not filed)
stack: aigateway
status: verified
started: 2026-11-13
finished:
---

# aigateway chart placement for the migrate Job and Garage

## Intent

The aigateway chart sets `nodeSelector` and `tolerations` in values. The gateway Deployment reads
them. The migrate Job and the bundled Garage StatefulSet do not. On a cluster with a tainted
tenant pool, these two pods cannot land on the pool that the gateway uses.

This unit makes both templates read the same placement values. It follows the Engine fix for the
same gap (plan U2).

Source: Stephen follow-up on PR #1738 (https://github.com/ScreamingFace/screamingface/pull/1738#issuecomment-6830194905), epic OME-1314.

## Changes

- `apps/aigateway/charts/aigateway/templates/job-migrate.yaml`: the pod spec gets `nodeSelector`
  and `tolerations`. No `affinity`.
- `apps/aigateway/charts/aigateway/templates/garage.yaml`: the Garage pod spec gets `nodeSelector`
  and `tolerations`. No `affinity`.
- `apps/aigateway/charts/aigateway/values.yaml`: the comment above `nodeSelector`, `tolerations`
  and `affinity` names each workload that reads them. It also states the zone rule for the Garage
  volume.
- `apps/aigateway/tests/unit/test_chart_render_placement_all_pods.py`: new file. It renders every
  workload with placement set and checks each pod template.

## Decisions

- `affinity` is not copied. An affinity names pod labels. The gateway affinity selects gateway
  pods. The migrate Job and Garage do not carry those labels.
- The `helm test` Pod (`templates/test-connection.yaml`) is not changed. It is a test hook, not a
  workload.
- `apps/aigateway/charts/aigateway/README.md` has no placement section. It is not changed.
- `apps/aigateway/CHANGELOG.md` is not changed. Release-please owns that file.
- The zone rule (Azure Disk is zonal, so the new pool needs a node in that zone) is written in the
  values comment. A Garage pod restarts when placement changes.

## Test plan

- The new test shows that the gateway Deployment, the migrate Job and the Garage StatefulSet each
  carry the placement.
- The test sets `affinity`. It checks that the gateway Deployment carries it and that the migrate Job and the Garage StatefulSet do not.
- The test checks that default values add no placement.
- Before the template change, the placement test fails with `assert None == {...}`. After the
  change, all four tests pass.

## Verification

- `uv run pytest tests/unit/test_chart_render_placement_all_pods.py -q`: 4 passed.
- `uv run ruff check`, `uv run ruff format --check` and `uv run pyright` on the new test file:
  clean.
- Full gates (`run_gates.py aigateway`, `run_gates.py repo`, `verify_chart_wiring.py`): all green
  (145/145 chart wiring checks). The default `helm template` render differs from origin/main only
  in random secret values.

## Status

Code, tests and gates are done. One local commit. Not pushed.
