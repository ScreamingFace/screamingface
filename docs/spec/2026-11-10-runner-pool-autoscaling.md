# Runner pool autoscaling on claimable queue demand

## Problem

The runner pool is a fixed Deployment. Production runs 2 pods x 4 slots (`runnerPool.replicas: 2`,
`workerSlots: 4`), and each queue bucket lets its consumer hold 4 unacked runs
(`runnerPool.maxAckPending: 4`). A worker acks a run only at its end (`worker/supervisor.py`
terminal paths; `in_progress` heartbeats meanwhile), so "unacked" means "executing".

Scenario:

1. Users A and B each run 4 runs. The 8 slots are 100% busy.
2. User C submits a Benchmark with n Candidates. The App admits them and publishes them to C's
   bucket (`url4-runq.<sha256(caller) mod 16>`).
3. C's runs wait until a slot frees. Nothing adds a pod.

Nothing can detect this today:

- The worker exposes no queue metric (`worker/metrics.py`).
- The App's `screamingface_engine_queue_depth` gauge is refreshed only by the admission path
  (`adapters/queue_runner.py:_refresh_if_stale`), so it is stale between submissions. It also reads
  the stream message count, which in a WORK_QUEUE stream is queued PLUS unacked, i.e. it includes
  running runs and runs that a bucket's `max_ack_pending` holds back.
- Production has no KEDA, no HPA and no Prometheus (OpenMined/infrastructure, 2026-11-10).

## Decisions

### D1. The scale signal is CLAIMABLE demand, read from the per-bucket consumers

For each bucket `b` the App reads its durable consumer (`url4-runners-<b>`):

```
running_b   = num_ack_pending                         # delivered, not acked = executing
queued_b    = num_pending                             # not yet delivered
headroom_b  = max(0, max_ack_pending_b - running_b)   # how many more this bucket may start
claimable_b = min(queued_b, headroom_b)

demand  = sum(running_b + claimable_b)
replicas = ceil(demand / workerSlots)                 # done by the HPA, see D4
```

WHY not the stream message count: runs that a bucket's `max_ack_pending` holds back cannot be
claimed by ANY pod, so counting them adds pods that stay idle. In the scenario, if A and B each
also have 4 runs queued behind their cap, the message count is `16 + n` (5 pods) while only one new
pod can do work.

Scenario check (prod values): `demand = 8 + min(n, 4)`, so `replicas = 3` for any n >= 1. One new
pod, which takes C's runs.

A consumer that does not exist yet (no worker has bound that bucket) adds 0 and is counted in
`unbound_buckets`. Workers bind every bucket on their first claim cycle, and D4 keeps at least one
worker, so this is a cold-start state only.

### D2. The App samples on its own cadence

One periodic task per App process (`_install_periodic`, the shared loop of the reaper and the
unclaimed-run warner) reads the 16 consumers every `runner_demand_sample_s` (default 5 s) and keeps
the last good sample with its time. Admission does not drive it, and it does not touch admission
state. The App runs one replica (`replicaCount: 1`), so there is one source of truth. `0` disables
the sampler.

### D3. The signal is served as JSON at `GET /runner-demand`

```json
{"demand": 9, "running": 8, "claimable": 1, "queued": 1, "unbound_buckets": 0,
 "sampled_at": "2026-11-10T12:00:00Z", "age_s": 2.1}
```

- 200 with a fresh sample. 503 when there is no sample yet or the sample is older than
  `runner_demand_stale_s` (default 30 s). A 503 makes the KEDA scaler fail, and the HPA then keeps
  the current replica count. INVARIANT: the endpoint never answers a confident `0` it did not read;
  a false 0 would scale a loaded pool down to its minimum.
- Same exposure class as `/metrics` and `/readyz`: no auth dependency, on the App port, behind the
  chart's single `/` route (Cloudflare Access at the edge). The body holds aggregate counts only, no
  caller, topic or bucket identity.
- The same snapshot is also exported as gauges for operators (`screamingface_engine_runner_demand`,
  `..._running`, `..._claimable`, `..._queued`, `..._unbound_buckets`, `..._sample_age_s`). Absent
  before the first sample, as the existing queue gauges are.

WHY JSON and not KEDA's `format: prometheus`: the KEDA docs describe `valueLocation` for that
format only as a "dot-separated path"; looking a metric up by name is not documented. JSON works
in every KEDA version the AKS add-on ships (2.11 on AKS 1.30 up to 2.20 on AKS 1.37).

WHY not the KEDA `nats-jetstream` scaler: it takes one consumer per trigger, and with 16 triggers
the HPA uses the MAXIMUM of the metrics, not their sum, so it under-scales. It also cannot see the
`max_ack_pending` headroom (D1), and it needs the NATS monitoring port 8222 opened across
namespaces.

WHY not the Prometheus scaler: production has no Prometheus.

### D4. The chart renders an opt-in KEDA ScaledObject

New values block, default off:

```yaml
runnerPool:
  autoscaling:
    enabled: false
    minReplicas: 2          # >= 1; scale to zero is refused (cold start of the benchmark image)
    maxReplicas: null       # required when enabled
    pollingIntervalS: 15
    scaleUp:   {stabilizationS: 0,   podsPerStep: 4, stepS: 15}
    scaleDown: {stabilizationS: 300, podsPerStep: 1, stepS: 60}
```

When enabled:

- `templates/scaledobject-runner.yaml` renders a `keda.sh/v1alpha1` ScaledObject on
  `<fullname>-runner`: trigger `metrics-api`, `url: http://<fullname>.<namespace>.svc.cluster.local:<service.port>/runner-demand`,
  `format: json`, `valueLocation: demand`, `metricType: AverageValue`,
  `targetValue: <workerSlots>`. With AverageValue the HPA computes `ceil(demand / workerSlots)`
  regardless of the current count. `advanced.horizontalPodAutoscalerConfig.behavior` carries the
  scaleUp/scaleDown policies. No `fallback`: on scaler error the replica count holds.
- `deployment-runner.yaml` omits `spec.replicas` (the HPA owns it). `runnerPool.replicas` is
  ignored.
- The render REFUSES: `maxReplicas` unset; `minReplicas < 1`; `minReplicas > maxReplicas`;
  `runnerPool.maxAckPending` unset. The derived default `replicas x workerSlots` has no meaning
  once `replicas` varies, and OME-1142 already requires the pin above one replica.

Disabled, the render is byte-identical to today.

### D5. Scale-down relies on the existing drain

On scale-down the ReplicaSet deletes a pod. Its preStop SIGTERMs the worker, which stops pulling,
NAKs held messages, kills idle warm children, keeps busy children up to `drainGraceS`, and exits
when the last child ends (`worker/loop.py:_drain`). No run is lost. An idle pod exits in about a
second.

Known cost: without `controller.kubernetes.io/pod-deletion-cost`, the ReplicaSet may pick a busy
pod. That pod drains (prod: up to 16 h) while an idle pod stays, and its runs still count in
`demand`, so the pool can run up to one pod above need until those runs end. The slow scale-down
policy (1 pod per 60 s after a 300 s window) limits this. Deletion cost is a follow-up.

### D6. Nothing else changes

Admission, the per-caller cap, buckets, `maxAckPending`, the SDK and aigateway are unchanged. A
user whose bucket is at its cap gets no extra pod (D1). That is today's per-caller fairness, and
it is the next problem in this series.

### D7. Owner answers (2026-11-10)

- `GET /runner-demand` on the App port, same exposure class as `/metrics`: **accepted**.
- Scaling windows (up: immediate, 4 pods per 15 s; down: after 300 s, 1 pod per 60 s): **accepted**.
- Scale-down victim selection (`pod-deletion-cost`): **follow-up PR**, recorded below.

## Follow-up: choose an idle pod on scale-down (`pod-deletion-cost`)

Status: agreed with the owner on 2026-11-10, NOT in this PR. Filed as `OME-1871` (2026-11-10).

Problem: on scale-down the ReplicaSet picks the pod to delete. With no hint it may pick a BUSY
pod. That pod drains (prod `drainGraceS` 57600 s = 16 h) and takes no new work, while an idle pod
stays. Its runs still count in `demand`, so the pool runs up to one pod above need until they end,
and during a rollout a draining pod also holds quota.

Proposed fix: each worker keeps the annotation `controller.kubernetes.io/pod-deletion-cost` on its
own pod equal to its busy slot count, updated when a run starts or ends (rate-limited). The
ReplicaSet then deletes the pod with the lowest cost, an idle one, first.

What it needs, and why it is a separate PR:

- The worker pod has `automountServiceAccountToken: false` today and never calls the Kubernetes
  API. The fix needs a ServiceAccount token and a Role that allows `patch` on `pods` in its own
  namespace (ideally restricted to its own pod name). That changes the pod's security posture
  and needs review from devops (infra repo RBAC, `sf-fusion/url4-cloud-rbac.yaml`).
- The annotation is best-effort: an API error must never affect a run.
- Kubernetes treats the cost as a hint; it is honored by the ReplicaSet controller (beta, on by
  default since 1.22).

Acceptance for the follow-up: with 3 pods (busy, busy, idle) and demand dropping to 8, the idle pod
is the one removed.

## Non-goals

- Per-user limits, bucket count, `maxAckPending` values, the SDK fan-out.
- aigateway sizing.
- `pod-deletion-cost` (follow-up).
- Installing KEDA, network policy, quota, node pools, Argo CD settings: infra repo (below).
- More than one App replica.

## Infrastructure prerequisites (OpenMined/infrastructure, devops)

1. KEDA: AKS add-on (Terraform `workload_autoscaler_profile { keda_enabled = true }`). Operator in
   `kube-system`.
2. NetworkPolicy in `sf-fusion` (default-deny today): allow the KEDA operator pods to reach the
   App Service port 9108.
3. Quota `sf-fusion/ns-ceiling`: the drain model keeps old pods during a rollout, so it must hold
   `2 x maxReplicas` pool pods. Example `maxReplicas: 3` (6 pool pods): requests.cpu
   `540m + 6x900m + 100m = 6040m` (> 5), requests.memory `832 + 6x1540 + 128 = 10200Mi` (> 8Gi),
   limits.memory `3328 + 6x10496 + 512 = 66816Mi` (> 48Gi).
4. Tenant node pool `max_count` (prod D8as_v7, 1-2): new spend, owner approval first.
5. Argo CD: removing `spec.replicas` from a live Deployment drops it to 1 pod once (Kubernetes
   HPA docs). Use server-side apply or `ignoreDifferences` on the runner Deployment's
   `/spec/replicas`. Draining pods keep their runs, so no run is lost; capacity dips until KEDA acts.
6. `values/<env>.yaml`: `runnerPool.autoscaling.enabled: true`, `minReplicas`, `maxReplicas`.
7. Keep `runnerPool.maxAckPending` at the value the broker's durable consumers already have
   (prod: 4). A new value does not change an existing consumer (`runner_queue.py`: a change of
   `max_ack_pending` needs the consumer deleted and made again). Until that, workers claim up to
   the OLD cap. The demand signal reads the cap from the broker, so it stays correct, but the
   per-bucket width is not the configured one. Found in the kind walkthrough 2026-11-10.

## Invariants this protects

- Disabled means unchanged: the default render equals `origin/main`'s.
- The signal never counts a run that a new pod could not claim.
- A missing or stale reading is an error, never a 0.
- Scale-down never interrupts a run (the drain, unchanged).

## Side finding (not fixed here)

`RunQueue.depth()` is documented as "queued but not yet started", but a WORK_QUEUE stream keeps a
message until it is acked, so the count includes running runs. The depth ceiling and the
`screamingface_engine_queue_depth` help text inherit that, and `oldest_unclaimed_age_s` reads the
stream's first message, which is often a running run. Being fixed on branch
`queue-depth-unclaimed` (2026-11-10). That branch owns `BucketReading` and
`RunQueue.bucket_readings()` with the same shape as change 2 of this plan. Whichever branch merges
second rebases and keeps one copy.
