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

- **Actual files:** as planned, plus four more new test files from the review fix round and one
  from the log change: `test_chart_render_runner_deletion_cost_values.py`,
  `test_kube_pod_cost_writer_failures.py`, `test_worker_deletion_cost_drain_stop.py`,
  `test_worker_deletion_cost_retry_backoff.py`, `test_worker_deletion_cost_logging.py`.
  `templates/NOTES.txt` did not change (it does not say that the runner mounts no token).
- **Commits:** `9db4c0994` docs (spec, plan, ledger, mirror); the `feat` commit that holds this
  Outcome. Not pushed. No PR yet.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine` — ALL GATES GREEN
  (append-only check, ruff, ruff format, pyright, layering, pytest with coverage), 2026-11-16.
- **Build:** tiered-build run `wf_3c8a9ebb-38f` (3 waves, 5 tasks, 18 agents). Design review:
  ACCEPT-WITH-FIXES, 12 findings. Fixed: F1 (writer task stops at the drain signal), F2 (a removed
  `deletionCost.enabled` rendered an empty `automountServiceAccountToken`, which mounts a token),
  F3 (a bad CA file crashed the worker), F4 (5 s for the whole request), F6, F7 (a count during a
  good write skipped one backoff), F8, F9, F11 (a private-attribute assert), F12 (one WARNING per
  failure streak, then DEBUG; spec D3 updated).
- **Deviations:**
  - `DELETION_COST_ANNOTATION` is in `worker/kube_pod.py`, not in `worker/deletion_cost.py` as
    the plan said (review F5, accepted): the adapter is the only code that names the annotation.
  - The composition root has a helper, `build_deletion_cost_publisher` in `worker/loop.py`, so
    that it has its own tests (review F9).
  - `build_pod_cost_writer` has `# noqa: PLR0911` (one early return per prerequisite).
  - Open: the kind walkthrough of the spec's Acceptance. Not done yet.
  - Open (review, low): the writer task is cancelled when the claim loop sees the drain signal,
    not in the signal handler. One last attempt can go out for up to about 5 s after SIGTERM.
