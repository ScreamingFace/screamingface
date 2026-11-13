---
ticket: OME-1913
stack: screamingface-engine
status: done
started: 2026-11-13
finished: 2026-11-13
---

# engine-chart-placement — Garage and the migrate Job use the chart placement

## Intent

The App and the runner pool use the chart values `nodeSelector` and `tolerations`. The two
bundled Garage StatefulSets and the migrate Job do not. On a tainted node pool, these pods do not
tolerate the taint, so they stay Pending. This unit makes every pod the chart renders use the same
placement. `affinity` is not applied to them: its labels name the App, and these pods carry other
labels.

Source: https://github.com/ScreamingFace/screamingface/pull/1738#issuecomment-6830194905
Epic: OME-1314.

## Facts

- The prod tenant pool has the taint `workload=tenant:NoSchedule` and the label
  `openmined.org/pool=tenant`.
- The pod templates of `garage.yaml`, `garage-blobs.yaml` and `job-migrate.yaml` had no
  `nodeSelector` and no `tolerations` before this unit.
- A Garage pod uses an Azure Disk PersistentVolume. The disk is zonal. A new node pool needs a node
  in the disk's zone.

## Decisions

- The new blocks copy the exemplar `templates/deployment.yaml`: `with` on the top-level value,
  `toYaml` at `nindent 8`.
- The migrate Job reads the values as `$.Values`, because it runs inside `with
  .Values.database.existingSecret`.
- The test renders every pod kind that embeds a pod template, so a future workload is checked too.

## Planned changes

- `apps/screamingface-engine/deploy/helm/templates/garage.yaml`: placement blocks, WHY comment.
- `apps/screamingface-engine/deploy/helm/templates/garage-blobs.yaml`: placement blocks, WHY comment.
- `apps/screamingface-engine/deploy/helm/templates/job-migrate.yaml`: placement blocks, WHY comment.
- `apps/screamingface-engine/deploy/helm/values.yaml`: comment above `nodeSelector`, `tolerations`
  and `affinity` names each workload, and the zonal volume note.
- `apps/screamingface-engine/deploy/helm/README.md`: placement line names the Garage pods and the
  migrate Job, and the zonal note.
- `apps/screamingface-engine/tests/unit/test_chart_render_placement_all_pods.py` (new).
- `apps/screamingface-engine/CHANGELOG.md`: one bullet under `## Unreleased`.
- `docs/work/2026-11-13-engine-chart-placement.md` (this file).

## Test plan

- Every rendered pod template carries the test `nodeSelector` and `tolerations`. The found set
  must include the App, the runner, both Garages and the migrate Job.
- The Garage and migrate pod specs carry no `affinity`, even when the top-level `affinity` is set.
- With default placement, no pod template has `nodeSelector` or `tolerations`.

## Acceptance

- Targeted pytest for the new file and `test_chart_render_garage_selector.py` passes.
- `ruff check`, `ruff format --check` and `pyright` pass on the changed Python file.
- With default values, `helm template` output is identical to `origin/main` (with a pinned
  `auth.jwtSecret`, because the chart generates a random one).
- Full gates: `run_gates.py screamingface-engine`, `run_gates.py repo`,
  `verify_chart_wiring.py`.

## Outcome

- **Actual files:** as planned, plus this ledger at the repo-root `docs/work/` and the
  `docs/tasks/2026-11-13-OME-1913-engine-chart-placement.md` mirror.
- **Commits:** (rebased on `468474117`, the #1796 merge)
  - `93cbb582e` fix(screamingface-engine): run Garage and the migrate Job on the chart's node
    placement
  - `a559641dd` docs(tasks): add the OME-1913 mirror and link the ledger
  - review fixes (#1797, Sergio): the README and `values.yaml` rewraps, the CHANGELOG says that
    the upgrade alone restarts both Garage pods, the comments say to use `nodeSelector` for
    node placement, and this Outcome.
- **Gates:**
  - Before the rebase: `run_gates.py screamingface-engine` ALL GATES GREEN (append-only, ruff,
    ruff format, pyright, layering, pytest with coverage >= 80); `run_gates.py repo` ALL GATES
    GREEN; `verify_chart_wiring.py` 145/145.
  - After the rebase on `468474117`: the chart tests of #1796 and #1797 together, 36 passed;
    `verify_chart_wiring.py` passed; the pre-push hook passed.
  - Default render identical to `origin/main` with a pinned `auth.jwtSecret` (reviewer check on
    `a559641dd`, helm v3.19.0).
- **Deviations:** Go template comments, not YAML comments, so the default render stays identical.
  The ledger is at the repo root.

## Before the prod sync (rollout check, not a code test)

Prod already sets `nodeSelector` and `tolerations` for the App and the runner pool. So the first
sync of a chart version with this change restarts both Garage pods (`<release>-garage`,
`<release>-garage-blobs`) on the tenant pool.

- Infra facts (OpenMined/infrastructure, read 2026-11-13): the prod cluster is in `eastus`. The
  AKS module (`terraform/modules/azure/aks/main.tf`) and the prod stack
  (`terraform/stacks/azure/aks-platform/prod/main.tf`, `extra_pools.tenant`) set no `zones` on any
  node pool.
- Not checked: the zone label (`topology.disk.csi.azure.com/zone`) on the two Garage
  PersistentVolumes. If a volume carries a zone, the tenant pool must have a node in that zone.
- Action: the platform owner confirms the PersistentVolume zones against the tenant pool before
  the prod sync. Record the answer here.
- Evidence after the sync: both Garage pods are Running on the tenant pool on dev first.
