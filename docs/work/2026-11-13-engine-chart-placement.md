---
ticket: OME-1913
stack: screamingface-engine
status: in_progress
started: 2026-11-13
finished:
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

- **Actual files:** as planned, plus this ledger at the repo-root `docs/work/`.
- **Commits:** pending.
- **Gates:** targeted pytest 6 passed. `ruff check`, `ruff format --check` and `pyright` clean on
  the new test. Default render identical to `origin/main` with a pinned `auth.jwtSecret`. Full
  gates not yet run.
- **Deviations:** Go template comments, not YAML comments, so the default render stays identical.
  The ledger is at the repo root.
