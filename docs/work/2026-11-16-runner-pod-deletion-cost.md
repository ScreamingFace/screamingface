---
ticket: OME-1931
stack: screamingface-engine
status: in_progress
started: 2026-11-16
finished:
---

# runner-pod-deletion-cost — the worker writes its busy slots as `pod-deletion-cost`

## Intent

On a scale-down, Kubernetes can remove a busy runner pod and keep an idle one. The busy pod then
drains for hours and holds its node. The worker now writes its busy slot count to the
`controller.kubernetes.io/pod-deletion-cost` annotation of its own pod, so the ReplicaSet removes
idle pods first. The chart gives the runner its own ServiceAccount, a mounted token and its pod
identity, all behind one switch that is off by default. Spec:
`docs/spec/2026-11-16-runner-pod-deletion-cost.md`. Plan:
`docs/plan/2026-11-16-runner-pod-deletion-cost.md`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/worker/deletion_cost.py` (new)
- `apps/screamingface-engine/src/screamingface_engine/worker/kube_pod.py` (new)
- `apps/screamingface-engine/src/screamingface_engine/worker/metrics.py`
- `apps/screamingface-engine/src/screamingface_engine/worker/loop.py`
- `apps/screamingface-engine/src/screamingface_engine/config.py`
- `apps/screamingface-engine/deploy/helm/values.yaml`, `values.schema.json`, `README.md`
- `apps/screamingface-engine/deploy/helm/templates/_helpers.tpl`, `deployment-runner.yaml`,
  `serviceaccount-runner.yaml` (new)
- `apps/screamingface-engine/tests/unit/test_worker_deletion_cost_publisher.py` (new)
- `apps/screamingface-engine/tests/unit/test_kube_pod_cost_writer.py` (new)
- `apps/screamingface-engine/tests/unit/test_worker_deletion_cost_wiring.py` (new)
- `apps/screamingface-engine/tests/unit/test_chart_render_runner_deletion_cost.py` (new)

## Test plan

- Writer: start write, write on change only, burst coalesces, minimum interval, retry with
  backoff, a newer count replaces a failed one, no exception leaves `run()`.
- HTTP adapter: exact request (method, path, content type, body, bearer), token read again for
  each write, non-2xx raises, builder fail-open cases, token never in a log.
- Worker: notify after a claim and after a run end, no notify after the drain signal, a failing
  writer never changes a run's result.
- Chart: default render unchanged; enabled render has the ServiceAccount, the token mount and the
  three env entries; name override; render guard.
- Invariant protected: a failed annotation write never stops or delays a run.

## Acceptance

- `uv run .claude/scripts/run_gates.py screamingface-engine` is green.
- Kind: with a Role, annotations read the busy counts and a scale-down removes the idle pod.
  Without a Role, 403 is logged and counted, and runs act as today.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
