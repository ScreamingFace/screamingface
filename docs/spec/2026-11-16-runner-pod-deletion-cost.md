# Runner scale-down removes idle pods first: the worker writes its busy slots as `pod-deletion-cost`

Status: APPROVED for build by the owner request of 2026-11-16 (ticket `OME-1931`, epic `OME-1314`).
Decisions D1-D9 below are the defaults of this spec. The owner can change them in review.

Issue: `OME-1931` (platform request, 2026-11-16). It replaces `OME-1871` (the same follow-up,
recorded 2026-11-10 in `docs/spec/2026-11-10-runner-pool-autoscaling.md`, section "Follow-up:
choose an idle pod on scale-down").

Evidence paths: `ENG` = `apps/screamingface-engine`. `INFRA` = `OpenMined/infrastructure` at
`main`, read with `gh api` on 2026-11-16 (read-only, no cluster access).

## Problem

When the runner pool scales down, the ReplicaSet controller selects the pod to delete. It cannot
see which pods are busy. The runner has no readiness probe, so all pool pods are Ready, and the
controller ranks them by node spread and age. It can delete a pod with 3 runs and keep an empty
pod.

No run is lost: the deleted pod drains its runs for up to `drainGraceS` (prod 57600 s = 16 h).
But during the drain the pod holds its node and its memory reservation, takes no new work, and
its free slots are not used. Its runs still count in the demand, so KEDA can add a new pod, often
on a new node. After some scale cycles, half-empty draining pods fill the nodes.

Kubernetes has a hint for this. The ReplicaSet deletes the pod with the LOWER
`controller.kubernetes.io/pod-deletion-cost` annotation first (the step after "not Ready before
Ready"). A pod without the annotation has cost 0. If each runner pod carries its busy slot count,
an idle pod goes first.

Platform runs an interim helper in `sf-fusion` (`INFRA
kubernetes/apps/sf-fusion/components/runner-deletion-cost/`, on in the dev, staging and prod
overlays). Every 3 s it reads `screamingface_engine_worker_slots_busy` from each runner on port
9109 and writes the annotation. Its limits: a lag of up to 3 s, a dependency on the gauge name
and the port, and no signal when it is down.

## Current state (facts)

- The busy slot count is `len(Worker._active)`. It changes in two places: after a claim batch
  (`ENG/src/screamingface_engine/worker/loop.py:346-353`) and in the done callback of a supervisor
  task (`loop.py:384-390`). Both places set the gauge `slots_busy`.
- The runner pod mounts no API token (`automountServiceAccountToken: false`,
  `ENG/deploy/helm/templates/deployment-runner.yaml:143`) and uses the App's ServiceAccount
  (`deployment-runner.yaml:144`). It has no downward-API env.
- The engine has no Kubernetes client library. `httpx` is a runtime dependency
  (`ENG/pyproject.toml:36`).
- The tenant chart can render a ServiceAccount (core group is allowed, `INFRA
  kubernetes/tenants/screamingface/project.yaml:59-60`). It cannot render a Role or a RoleBinding
  (`rbac.authorization.k8s.io` is not in the whitelist).
- All three clusters set `fullnameOverride: url4-cloud`. The runner Deployment is
  `url4-cloud-runner`, in namespace `sf-fusion`.
- Runner pods (`app.kubernetes.io/name: url4-runner`) have NO egress to the API server today. The
  namespace is default-deny (`INFRA kubernetes/apps/sf-fusion/base/netpol.yaml:13`), and
  `allow-url4-cloud-egress-apiserver` selects only `app.kubernetes.io/name: url4-cloud`
  (`url4-cloud-netpol.yaml:227-234`).
- A run child is a process in the SAME container as the worker, with the same user
  (`ENG/src/screamingface_engine/worker/exec_wrapper.py:23-29`). A file in the runner container is
  readable by each run child.

## Decisions

### D1. The worker writes the annotation on its own pod

The worker process sets `controller.kubernetes.io/pod-deletion-cost` on its OWN pod to its busy
slot count, a decimal string `"0"` to `"<workerSlots>"`.

Request: `PATCH /api/v1/namespaces/<namespace>/pods/<pod>` with
`Content-Type: application/merge-patch+json` and this body, and nothing else:

```json
{"metadata": {"annotations": {"controller.kubernetes.io/pod-deletion-cost": "3"}}}
```

The worker sends no GET, no LIST and no WATCH. It needs one verb: `patch` on `pods`.

Rejected: the App writes the costs from per-pod status (option B of the 2026-11-13 draft). Platform
chose the worker-side write, with a guard on their side (D8).

### D2. Write on a change, not on a timer

- The trigger is a change of the busy count: a claim batch that takes slots, or a run that ends.
- The writer coalesces. One write is in flight at most, and the latest count wins. A burst of
  changes gives one write of the final value.
- A write does not start less than 1 s after the previous attempt (`MIN_WRITE_INTERVAL_S`). This
  limits the API load to 1 request per second per pod in the worst case. A change during that
  second is written when the second ends.
- ONE write at worker start (the current count, usually 0). WHY: a container restart keeps the
  pod and its old annotation. Without this write, an idle pod could keep cost 3 until its next
  run. The worker cannot read the annotation (no `get` verb), so it writes.
- No write after the drain signal (SIGTERM). The pod is then in deletion, and the cost has no
  effect.

### D3. A failed write never stops or delays a run

- `notify(busy)` is a synchronous call that stores a number and sets an event. It does no I/O and
  cannot raise.
- The write runs in its own task, outside the supervisors' TaskGroup. An exception in it cannot
  cancel a run.
- A failure (timeout, connection error, non-2xx status) is logged at WARNING and counted. The
  worker continues.
- Retry: while the last write failed, the writer tries again after a backoff of 1 s, doubled to a
  maximum of 30 s. A new count wakes the retry at once (the 1 s minimum still applies). The retry
  stops when a write succeeds. WHY a retry at all: without it, a pod keeps a wrong cost until its
  next run starts or ends, which can be hours. This is not a periodic timer: when the last write
  succeeded, the worker sends nothing.
- HTTP timeout: 5 s for the whole request.

### D4. Fail open on a missing prerequisite

If the feature is on but a prerequisite is missing, the worker logs ONE warning that names the
missing item and runs without the feature. It does not exit. The prerequisites are: the pod name,
the pod namespace, `KUBERNETES_SERVICE_HOST`, the token file and the CA file.

WHY not fail fast: the feature only improves the scale-down choice. A crash loop of the runner
pool because of it would stop all runs.

If the Role or the network path is missing (403 or timeout), each write fails and the D3 retry
continues at one attempt per 30 s. The pool then acts as it does today. The feature starts to
work without a restart when platform adds the permission.

### D5. Settings and metrics

New settings (`ENG/src/screamingface_engine/config.py`, env prefix `URL4_CLOUD_`):

| Setting | Env | Default |
|---|---|---|
| `worker_deletion_cost_enabled: bool` | `URL4_CLOUD_WORKER_DELETION_COST_ENABLED` | `False` |
| `worker_pod_name: str \| None` | `URL4_CLOUD_WORKER_POD_NAME` | `None` |
| `worker_pod_namespace: str \| None` | `URL4_CLOUD_WORKER_POD_NAMESPACE` | `None` |

The API server address comes from the standard in-cluster env (`KUBERNETES_SERVICE_HOST`,
`KUBERNETES_SERVICE_PORT`). The token and the CA come from the standard mount
(`/var/run/secrets/kubernetes.io/serviceaccount/token` and `ca.crt`). The worker reads the token
file again for each write, because the kubelet replaces it before it expires.

New worker metric: `screamingface_engine_worker_deletion_cost_writes_total{outcome="ok"|"error"}`.

The gauge `screamingface_engine_worker_slots_busy` and port 9109 do not change. The interim
helper continues to work until platform removes it.

### D6. Chart: an opt-in runner ServiceAccount, a mounted token, and the pod identity

New values, default OFF:

```yaml
runnerPool:
  deletionCost:
    enabled: false
  serviceAccount:
    create: true
    name: ""          # "" = <fullname>-runner
    annotations: {}
```

When `runnerPool.deletionCost.enabled` is `false`, the render is the same as today: the runner
uses the App's ServiceAccount, mounts no token, and has no new env.

When it is `true`:

- The chart renders a ServiceAccount named `<fullname>-runner` (or `serviceAccount.name`), when
  `serviceAccount.create` is `true`. The ServiceAccount object sets
  `automountServiceAccountToken: false`; only the runner pod opts in.
- The runner pod sets `serviceAccountName` to that account and
  `automountServiceAccountToken: true`.
- The runner container gets three env entries: `URL4_CLOUD_WORKER_DELETION_COST_ENABLED=true`,
  `URL4_CLOUD_WORKER_POD_NAME` (downward API `metadata.name`) and
  `URL4_CLOUD_WORKER_POD_NAMESPACE` (downward API `metadata.namespace`).
- The render fails when `serviceAccount.create` is `false` and `serviceAccount.name` is empty.

The App's ServiceAccount, the App pod, the queue, the drain, the slots and the autoscaling
settings do not change. The switch does not depend on `runnerPool.autoscaling.enabled`: the cost
also helps a rollout and a manual scale-down.

The chart renders NO Role, RoleBinding, NetworkPolicy or admission policy (D8).

### D7. The ServiceAccount name for platform

`<fullname>-runner`. With `fullnameOverride: url4-cloud` on dev, staging and prod, the account is
`url4-cloud-runner` in `sf-fusion`
(`system:serviceaccount:sf-fusion:url4-cloud-runner`).

### D8. Platform side (OpenMined/infrastructure, not in this PR)

1. Role with `pods: [patch]` and a RoleBinding to `url4-cloud-runner` in `sf-fusion`.
2. The guard: the account can change only the annotation
   `controller.kubernetes.io/pod-deletion-cost`, and only on its own pod. The bound token carries
   the pod name (`request.userInfo.extra['authentication.kubernetes.io/pod-name']`). The request
   shape is in D1.
3. NEW FINDING: a network rule. Runner pods have no egress to the API server today (see
   "Current state"). Platform must add a CiliumNetworkPolicy for
   `app.kubernetes.io/name: url4-runner` with `toEntities: [kube-apiserver]`. Without it, each
   write times out after 5 s and the feature has no effect (the error counter increases).
4. In the same promotion: set `runnerPool.deletionCost.enabled: true` and remove the helper
   component `runner-deletion-cost` with its two port-9109 network policies.

The order is safe in both directions. If the chart value is on before items 1-3, the writes fail
and the pool acts as today (D4). If the helper and the worker both run, they write the same
number.

### D9. Accepted risk: the token is in the runner container

The runner container holds a ServiceAccount token, and each run child can read it. The child runs
only engine code and built-in benchmarks, but it parses untrusted data (model outputs, datasets,
caller expressions).

What a stolen token can do, with the guard of D8: set the deletion cost of its own pod. That
changes the scale-down choice for one pod. It cannot read secrets, list pods or change other
objects (the Role has one verb, and the guard limits it). It also gets the rights of all
authenticated identities (API discovery), which is the cluster default.

Without the guard, the token could patch each pod in `sf-fusion` (labels, annotations, image).
So the guard is a REQUIRED part of the platform change, not an option. The interim helper has the
same Role without a guard today, but its token is not in a pod that runs benchmark code.

Rejected for now: a sidecar that holds the token (one more container per pod and quota for it),
and the App as the single writer (platform chose the worker).

## Limits that stay

- A run can start between the ReplicaSet's choice and the pod's stop signal (milliseconds). The
  pod then drains that run, as today.
- A change in the 1 s minimum interval is written up to 1 s late.
- A pod whose writes fail keeps its last written cost. The error counter shows it.
- Two pods with the same busy count are ranked by the older rules (node spread, age). The cost is
  the busy slot count, not the remaining run time: the engine has no run-length estimate.

## Non-goals

- Changes to the queue, the drain, `drainGraceS`, the PDB, the slots or the KEDA settings.
- A change of `scaleDown.enabled` defaults. Platform sets it per environment.
- Role, RoleBinding, NetworkPolicy or admission policy in the chart.
- A weight by run age or run length.

## Acceptance

Unit (in this PR):

- The writer: one write at start; one write per change; a burst gives one write of the final
  value; no write when the count is the same; the minimum interval; retry with backoff after a
  failure; a newer count replaces a failed one; an exception never leaves `run()`.
- The HTTP adapter: method, path, content type, exact body, bearer token read again for each
  write, non-2xx raises, the token is not in a log line.
- The worker: `notify` after a claim batch and after a run ends; no `notify` after the drain
  signal; a writer that always fails does not change a run's result; the task is cancelled at
  exit.
- The composition root: feature off gives no writer; feature on with a missing prerequisite gives
  no writer and one warning.
- The chart: default render has no runner ServiceAccount, no token and no new env; enabled render
  has all of D6; the name override; the render guard.

Kind (after the build, before the PR is ready):

- 3 pods (busy, busy, idle), Role present: annotations read the busy counts; a scale-down to 2
  removes the idle pod.
- No Role: 403 is logged and counted; runs and scaling act as today.

## Answers to the ticket

| # | Ask | Answer |
|---|---|---|
| 1 | Build the worker change and the chart change | This PR. |
| 2 | The runner ServiceAccount name | `url4-cloud-runner` in `sf-fusion` (D7). |
| 3 | The chart version that ships it | `Chart.yaml` stays at 0.1.0 (it is not released). Infra pins the chart by commit (`chartRef`). The answer is the merge commit of this PR on `main`, and the next engine release that contains it. |

Extra ask to platform: the network rule of D8 item 3.
