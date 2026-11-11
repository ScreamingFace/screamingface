# screamingface-engine

Helm chart for **screamingface-engine** — the stateless REST + WebSocket control plane (spec §9). It renders
the App **Deployment · Service · ConfigMap · Secret**, one of two edge objects
(**Ingress** or **HTTPRoute**), and the **runner pool** — a fixed worker-pool
**Deployment + PodDisruptionBudget** (OME-1092) that replaced one-Job-per-run scheduling.
The control plane holds **no RBAC at all**: it cannot create Pods, and the ServiceAccount
exists for pod identity only.

**Two paired images.** The App Deployment runs the dataset-free control-plane image. The runner
pool runs the matching `-benchmark` image with `command: ["screamingface-engine", "worker"]`;
that image layers private grading assets onto the same engine release, and the worker forks each
run as a child from its own image. `runner.image.tag` defaults to the control-plane tag, so
upgrades remain paired while rubrics stay off the client-facing pod.

By default a control-plane repository such as `registry.example/screamingface-engine` yields the pool image
`registry.example/screamingface-engine-benchmark`. Override `runner.image.repository` only when a registry
uses another name.

## Install

NATS (JetStream) is the telemetry bus, declared as a chart dependency (`Chart.yaml`, condition
`nats.enabled`, default off). The subchart `.tgz` is **vendored under `charts/`** and `Chart.lock`
is committed, so `helm template`/`install` resolve it straight from disk — **no
`helm dependency build`, no network.** Adding `--dependency-update` re-resolves the upstream repo
on every run and can silently pick up a different build than the one reviewed.

```bash
# Reuse an existing in-cluster NATS (JetStream) — leave the subchart inert, point the App at it:
helm upgrade --install url4 apps/screamingface-engine/deploy/helm \
  --namespace screamingface-engine --create-namespace \
  --set config.natsUrl=nats://my-nats:4222

# Or deploy the bundled NATS alongside the App. `nats.fullnameOverride` is REQUIRED here: it
# fixes the Service name that `config.natsUrl` is derived from.
helm upgrade --install url4 apps/screamingface-engine/deploy/helm \
  --namespace screamingface-engine --create-namespace \
  --set nats.enabled=true --set nats.fullnameOverride=nats
```

**There is no default `config.natsUrl`, deliberately.** A stock `helm template` with no bus
configured fails at render time:

```
config.natsUrl is required when nats.enabled=false — the App has no bus to reach otherwise
```

The previous default hardcoded `nats://screamingface-engine-nats:4222`, which only resolved when the release
happened to be named `screamingface-engine` — the subchart's Service is `<release>-nats`. Under any other
release name the App pointed at a Service that did not exist and nothing caught it until a live
connect failed. Failing the render is the fix.

Quote indexed `--set` keys in zsh.

### Values are validated

`values.schema.json` is checked on every `lint`/`template`/`install`. It rejects unknown and
misspelled keys (`runner.resource`, `config.natUrl`, a `podDisruptionBudget` block left behind
after a refactor) and enforces the combinations that would otherwise fail only at container
startup — `runner.backend` against the `RunnerBackend` enum, `tavily.enabled` without a key
source, `auth.create: false` without an `existingSecret`, `gateway.enabled` without a `parentRef`.

### Upgrading from the Job-per-run chart — REQUIRED values edits (OME-1092)

The worker-pool cutover retires the Job adapter, and with it three values this chart used to
document. Because the schema is `additionalProperties: false`, they are now **rejected**, not
ignored: an upgrade that still carries them fails before any template renders, with

```
Error: values don't meet the specifications of the schema(s) in the following chart(s):
screamingface-engine:
- at '': additional properties 'rbac' not allowed
```

(the exact wording varies with the Helm version; the key name in it is the one to delete)

Delete these from your values file:

| Removed | Why it is gone | Replacement |
| --- | --- | --- |
| `rbac.*` | The App no longer creates Jobs, so it needs no Role/RoleBinding at all — the pool pulls from the queue and `automountServiceAccountToken: false` | none; the RBAC objects are no longer rendered |
| `runner.resources` | Per-run Pod sizing died with the per-run Pod | `runnerPool.perRunCharge` + `runnerPool.overhead`, which size the *worker* pod as `workerSlots × perRunCharge + overhead` |
| `runner.jobTtlSeconds` | `ttlSecondsAfterFinished` was the Job's single-use replay guard; a claimed queue message is guarded by the durable consumer instead | none, and none needed — the queue's own max age (24 h, `run_queue_max_age_s`, not chart-exposed) bounds an unclaimed run |

`runner.backend` and `runner.image` are **unchanged** and still required.

The failure is loud and happens before anything is applied, so an upgrade that trips it has
changed nothing in the cluster — fix the values file and re-run.

## The edge: Ingress or Gateway API — pick one

The chart renders **exactly one** front door. Enabling both fails the render (two objects claiming
one Service means the edge contract is defined twice and diverges).

| | `ingress.enabled` (default) | `gateway.enabled` |
|---|---|---|
| Object | `networking.k8s.io/v1 Ingress` | `gateway.networking.k8s.io/v1 HTTPRoute` |
| Prerequisites | an ingress controller | Gateway API CRDs · a `GatewayClass` · a `Gateway` |
| TLS | `ingress.tls` + cert-manager annotation | on the Gateway's listener (cert-manager needs `ExperimentalGatewayAPISupport`) |
| **Timeouts** | **not expressible — see below** | `rules[].timeouts`, a typed spec field |

> **INVARIANT — the timeout contract.** This app holds one long-lived WebSocket per run plus REST
> calls that legitimately block for `config.syncMaxWaitS`. Whatever serves the edge **must** allow
> a response to outlive `config.jobDeadlineS` (16 h), or it severs live runs mid-stream.
>
> An `Ingress` has **no portable timeout field**. On Traefik these are static
> `entryPoints.<name>.transport.respondingTimeouts` settings applied when the *controller* is
> installed; other controllers use their own annotations. **So on the Ingress path this half of
> the contract is not carried by `helm install` and every environment must reproduce it
> independently.** That gap is the reason the chart also ships the HTTPRoute, where the same
> requirement is a typed field the chart owns.
>
> Bound the timeouts at `jobDeadlineS` rather than disabling them — an unbounded edge turns a
> wedged client into a permanent resource leak.

`gateway.timeouts.*` default to `jobDeadlineS` when left empty. Note that the Gateway API CRD
bundle version and the controller version are coupled: a controller that cannot parse the
installed CRDs leaves the Gateway at `Programmed=Unknown / "Waiting for controller"`, which looks
exactly like having no controller at all.

## The runner pool (OME-1092)

The pool is a Deployment of `runnerPool.replicas` pods, each running
`screamingface-engine worker` with `runnerPool.workerSlots` run slots. The declared concurrency
is `replicas × workerSlots`; the queue's `max_ack_pending` derives from the same slot count, so
the pool and the queue cannot disagree about how many runs one worker may hold.

What the pool's pods get:

- the paired benchmark image in worker mode — `command: ["screamingface-engine", "worker"]`,
  pinned in the template rather than in values: the command is the mode switch and nothing
  else, so a chart override could only ever name a mode the image does not have
- the deploy-time runner env by `envFrom` from the runner-env ConfigMap (unchanged from the Job
  path: Helm owns `AIGATEWAY_BASE_URL`, `URL4_CLOUD_NATS_URL`, the artifact-store settings), plus
  the Tavily and object-storage Secrets by `envFrom.secretRef` when enabled — never as literals
- `enableServiceLinks: false` — kubelet's legacy Docker-link vars would export
  `URL4_CLOUD_PORT=tcp://…` for the App's own Service and collide head-on with the app's
  `URL4_CLOUD_` settings prefix
- `automountServiceAccountToken: false` — the worker never calls the k8s API
- `securityContext` matching the App's, plus a `RuntimeDefault` seccomp profile and an `emptyDir`
  at `/tmp` (required by `readOnlyRootFilesystem`)
- `resources` = `workerSlots × perRunCharge + overhead` — sized so the declared concurrency can
  actually run rather than scheduling BestEffort. The memory REQUEST also adds, per
  warm child (`workerSlots` when `warmChildren` is unset), what it holds beyond its free slot's
  charge — `warmChildCharge.memoryMi − perRunCharge.memoryMi` (194 Mi with the defaults) — so it
  states what an idle warm pool actually holds; the memory limit is unchanged.
- one per-slot memory value (OME-1607): `perRunCharge.memoryLimitMi` is both the slot's share of
  the pod limit and each run's RESIDENT budget. The worker reads the run's process-tree RSS and
  stops a run over it with a permanent `memory_budget_exceeded` (not redelivered), before the
  pod's cgroup OOM-kills it or a co-tenant. The child's `RLIMIT_AS` stays a runaway backstop at
  `addressSpaceFactor ×` the budget (default 2, and the chart refuses < 2). The default budget is
  2,560 Mi (OME-1648): every ContractEval run parses its whole 192 MiB case file, which peaked at
  1,828 MiB resident in kind. With 4 slots the pod limit is 10,496 Mi; the request is unchanged.
- `ARROW_DEFAULT_MEMORY_POOL=system` and one OpenBLAS/OpenMP/MKL thread for every child: pyarrow's
  default pool reserves a 1 GiB arena and OpenBLAS a buffer per node CPU, address space a run
  never uses but `RLIMIT_AS` counts (a `draco-3pass` run died at 459 MiB resident without them).
- `nodeSelector` and `tolerations` from the chart's top-level placement values — the pool and
  the App Deployment therefore use the same operator-owned node pool and taint policy
- a `checksum/runner-env` + `checksum/secret` annotation pair, so a ConfigMap/Secret value
  change alone rolls the pool (the same invariant as the App Deployment)
- a Prometheus `/metrics` endpoint on `runnerPool.metricsPort` (the worker's own scrape
  surface — slots, claim latency, run duration, redeliveries, child exit codes)

**Drain (the deploy-interrupts-runs regression).** On SIGTERM the worker stops pulling and keeps
its in-flight children alive for `runnerPool.drainGraceS`, then terminates the rest with a named
`worker_draining` frame. The `preStop` starts that drain by SIGTERMing the worker immediately,
and `terminationGracePeriodSeconds` must stay above `drainGraceS` or the kubelet SIGKILLs
mid-drain. The PodDisruptionBudget (`maxUnavailable: 1`) does not block voluntary
disruptions — deliberately: `0` at a small replica count is either a placebo (1 replica: an
eviction still takes the whole pool) or a deadlock (a drain that can never evict). `1`
serializes voluntary disruptions — never two pods down at once — and the `preStop` drain, not
the PDB, is what protects in-flight runs. Expect one runner pod to be evicted during a node
drain, its runs closing out as `worker_draining`.

**Admission.** The App admits runs on **queue depth** (OME-1091): a run is refused with 503 +
`Retry-After` when the queue is at `run_queue_depth_ceiling` or the caller is at its in-flight
cap. Depth counts **unclaimed** runs only — runs no worker has claimed yet, read from the
per-bucket consumers. A running run is not depth, although the queue stream holds it until the
run ends. The `screamingface_engine_queue_depth` and
`screamingface_engine_queue_oldest_unclaimed_age_s` gauges use the same reading. This supersedes the OME-1065 quota-admission feature, which was retired with the Job
adapter — the counted resource changed from namespace quota headroom to queue depth, and the
cache-plus-reservation shape did not.

### Warm children (uniform executor PRD 03)

Each worker pod can keep child processes started AHEAD of a claim: they already did their
per-process work (Python start-up, the imports, the world build) and wait on stdin, so a claim
hands the run off in milliseconds instead of paying a cold boot. With 0 warm children a child
is spawned ON the claim instead, through the same protocol — slower start, least memory.

Set with `runnerPool.warmChildren` — the chart default is 2 per pod (sized 2026-09-26 to the
deployments' 4-slot pods). `null` leaves the worker's own default of one warm child per
`workerSlots`; the worker caps whatever is set here at `workerSlots` regardless, and the render
refuses a value ABOVE `workerSlots` outright, naming both values, rather than deploying a pool
that would be silently truncated.

**Memory.** Each IDLE warm child holds the imported engine and its built world: about 430 MiB
measured in kind with the builtin benchmarks. Idle children only occupy FREE slots (idle +
running ≤ `workerSlots`), so the per-slot memory LIMIT already covers them; the memory REQUEST
adds each warm child's excess over its slot's charge (`runnerPool.warmChildCharge.memoryMi` 450 −
`perRunCharge.memoryMi` 256), so the scheduler sees what the warm pool really uses.

**Metrics**, on the same `runnerPool.metricsPort` scrape surface as the pool's other metrics:

- `screamingface_engine_worker_warm_children` (gauge) — idle warm children right now
- `screamingface_engine_worker_warm_spawn_failures_total` (counter) — a warm child that failed
  to start, timed out before READY, or died idle
- `screamingface_engine_worker_handoff_latency_s` (histogram) — claim to the child's ACK
- `screamingface_engine_worker_child_boot_s` (histogram) — child spawn to its READY

## Autoscaling the runner pool

Autoscaling is opt-in and off by default (`runnerPool.autoscaling.enabled: false`). With
autoscaling disabled, the render is byte-identical to a chart without the `autoscaling` block.
With autoscaling enabled, the chart renders a KEDA `ScaledObject` on `<fullname>-runner`. The
runner Deployment renders no `spec.replicas`. The HPA owns the replica count, and
`runnerPool.replicas` is ignored.

**The signal.** The App reads each bucket consumer every `runner_demand_sample_s` (5 s). It serves
the result on `GET /runner-demand`. For each bucket `b`, the App computes:

```
running_b   = num_ack_pending                         # delivered, not acked = executing
queued_b    = num_pending                             # not yet delivered
headroom_b  = max(0, max_ack_pending_b - running_b)   # how many more this bucket may start
claimable_b = min(queued_b, headroom_b)

demand  = sum(running_b + claimable_b)
replicas = ceil(demand / workerSlots)                 # done by the HPA (the KEDA ScaledObject)
```

The signal counts claimable runs, not stream messages. Runs that a bucket's `max_ack_pending`
holds back cannot be claimed by any pod. Counting them adds pods that stay idle. Example: two pods
with four slots each run eight runs, and a third caller queues `n` runs. The demand is
`8 + min(n, 4)`, so the replicas are 3 for any `n` of 1 or more.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Renders the ScaledObject and omits `spec.replicas` from the runner Deployment. |
| `minReplicas` | `2` | Lowest replica count. Must be 1 or more. The pool does not scale to zero. |
| `maxReplicas` | `null` | Highest replica count. Required when `enabled` is `true`. |
| `pollingIntervalS` | `15` | Seconds between KEDA polls of `/runner-demand`. |
| `scaleUp` | 0 s window, 4 pods per 15 s | `stabilizationS: 0`, `podsPerStep: 4`, `stepS: 15`. Scale-up acts at once. |
| `scaleDown` | 300 s window, 1 pod per 60 s | `stabilizationS: 300`, `podsPerStep: 1`, `stepS: 60`. Scale-down acts slowly. |

**The render refuses** these settings:

- `maxReplicas` is not set.
- `minReplicas` is less than 1. The values schema refuses this value.
- `minReplicas` is greater than `maxReplicas`.
- `runnerPool.maxAckPending` is not set. The derived value `replicas × workerSlots` has no meaning
  when the replica count changes (OME-1142).

Pin `maxAckPending` to the value the queue's durable consumers already have. A new value does not
change an existing consumer: the consumer must be deleted and made again. Until then the workers
claim up to the old cap. `/runner-demand` reads the cap from the broker, so the signal follows the
old cap too.

Set `runnerPool.drainGraceS` to at least your longest run. On scale-down Kubernetes can remove a
busy pod while idle pods exist. The drain keeps that pod's runs only for `drainGraceS`, then stops
them. The chart default (30 s) stops almost every real run. Prod uses 57600 s.

**Fail-static.** `GET /runner-demand` answers as follows:

- 200 with `{demand, running, claimable, queued, unbound_buckets, sampled_at, age_s}` for a fresh
  sample.
- 503 when there is no sample, or when the sample is older than the App setting
  `runner_demand_stale_s` (default 30 s).
- 404 when the sampler is off (the App setting `runner_demand_sample_s` is `0`; default 5 s).

The two sampler settings are App settings with code defaults (`URL4_CLOUD_RUNNER_DEMAND_SAMPLE_S`,
`URL4_CLOUD_RUNNER_DEMAND_STALE_S`). This chart renders no value for them on purpose (owner
decision, 2026-11-10): the defaults fit every environment today. Add chart values when one
environment needs a different cadence.

A 503 makes the KEDA scaler fail. The HPA then keeps the current replica count. The endpoint never
answers a `0` that it did not read. No `fallback` is configured. The endpoint has the same exposure
class as `/metrics`: no auth, aggregate counts only, and no caller, topic or bucket identity.

The App also exports the same numbers as gauges: `screamingface_engine_runner_demand`,
`screamingface_engine_runner_demand_running`, `screamingface_engine_runner_demand_claimable`,
`screamingface_engine_runner_demand_queued`,
`screamingface_engine_runner_demand_unbound_buckets` and
`screamingface_engine_runner_demand_sample_age_s`. The gauges are absent before the first sample.

**Scale-down.** The preStop drain protects runs on scale-down. Without
`controller.kubernetes.io/pod-deletion-cost`, the ReplicaSet can pick a busy pod. That pod drains
for up to `drainGraceS`, while an idle pod stays. The slow scale-down policy limits this cost;
choosing an idle pod with `pod-deletion-cost` is a follow-up.

**Infrastructure prerequisites (OpenMined/infrastructure, devops).**

1. KEDA: enable the AKS add-on (Terraform `workload_autoscaler_profile { keda_enabled = true }`).
   The operator runs in `kube-system`.
2. NetworkPolicy in `sf-fusion` (default-deny today): allow the KEDA operator pods to reach the
   App Service port 9108.
3. Quota `sf-fusion/ns-ceiling`: the drain model keeps old pods during a rollout, so the quota must
   hold `2 x maxReplicas` pool pods. Example with `maxReplicas: 3` (6 pool pods):
   requests.cpu `540m + 6x900m + 100m = 6040m` (> 5), requests.memory
   `832 + 6x1540 + 128 = 10200Mi` (> 8Gi), limits.memory `3328 + 6x10496 + 512 = 66816Mi`
   (> 48Gi).
4. Tenant node pool `max_count` (prod D8as_v7, 1-2): this is new spend. The owner must approve it
   first.
5. Argo CD: removing `spec.replicas` from a live Deployment drops it to 1 pod once. Use
   server-side apply, or `ignoreDifferences` on the runner Deployment's `/spec/replicas`.
   Draining pods keep their runs, so no run is lost. Capacity dips until KEDA acts.
6. Per-env values: in `values/<env>.yaml`, set `runnerPool.autoscaling.enabled: true`,
   `minReplicas`, and `maxReplicas`.

## A private world config (OME-1770)

By default the App and the pool read the image's public `url4.toml`. A deployment that declares
private routes, such as configured-endpoint chat models, needs a complete world config that never
enters the image, the chart values or Git. The chart mounts it from ONE ConfigMap or Secret the
operator already created, read-only, into the App AND every runner pod, and points
`URL4_RUNNER_CONFIG` at it. The App's catalog and mount table and the worker's execution parse
the same file, so the two pod templates always carry the same source, key, path and checksum.

The checksum comes from the publication review. `check-publication` reads this world file and
the Gateway's configured-endpoints file, and refuses every Gateway target the world declares
without both `public_schema = false` and `web_search = false`. With `--print-checksum` it prints
the reviewed file's sha256 and nothing else, and only when the review passes; its findings go to
stderr. A failed review leaves `contentChecksum` empty, and the render refuses. Run it where
both files are, with the Engine version this chart deploys.

```sh
kubectl create secret generic url4-world --from-file=url4.toml=./world.toml
helm upgrade url4-cloud apps/screamingface-engine/deploy/helm \
  --reuse-values \
  --set worldConfig.existingSecret=url4-world \
  --set-string worldConfig.key=url4.toml \
  --set-string worldConfig.contentChecksum="$(URL4_RUNNER_CONFIG=./world.toml screamingface-engine admin check-publication --endpoints ./endpoints.toml --print-checksum)"
```

- **The file is complete.** It replaces the image's `url4.toml`; it is not an overlay. Copy the
  public file and add the private stanzas to the copy.
- **`contentChecksum` is required with a source.** The chart never reads an object it did not
  render, so it cannot hash the file itself. Pass a revision of the file's CONTENT: changing it
  rolls the App and the pool together, and warm children go with their worker pod, because they
  inherit its environment. The review prints the file's sha256, so the App's `/healthz`
  `config_digest` is the post-rollout check that the App loaded that exact file.
- **Rerun the review when either file changes.** A new Gateway target that this world declares
  without the two flags would otherwise appear in `/openapi.json` and in `/metrics` under its
  own path.
- **Each pod keeps the file it started with.** The file is mounted by `subPath`, which the
  kubelet never live-updates, so the warm and cold children of one worker always run the same
  file. A new revision reaches a pod only through the rollout its checksum starts.
- **Publish a changed file under a new Secret name.** A pod that starts reads the Secret as it
  is at that moment, so a Secret edited in place reaches restarted and scaled-up pods before
  the review and the rollout. Create each revision as a new Secret and point `existingSecret`
  at it in the same upgrade.
- **The rollout window fails fast once every worker checks the stamp.** The App and the pool
  roll as two Deployments. The App stamps its file's sha256 on every run it queues, and a worker
  serving another file refuses that run with the retryable `world_config_mismatch` and starts no
  child. A run in the window fails instead of running under a world the App that accepted it
  never served; the caller retries it.
- **Upgrade to the stamp check readers first.** A worker of an earlier version ignores the stamp
  and runs the job under its own file, so a changed file is unprotected while one such worker is
  left. Upgrade a release whose pool predates the check in three steps, and keep the world file
  it runs now through the first two; the App's `/healthz` `config_digest` must not change:
  1. The pool alone: `--set-string image.tag=<running tag> --set-string runner.image.tag=<new tag>`.
     The App keeps its image.
  2. Once `kubectl rollout status deployment/<fullname>-runner` reports done, the App:
     `--set-string image.tag=<new tag> --set-string runner.image.tag=`. The empty value pairs
     the two images again, and the pool, already on that tag, does not roll.
  3. Only then a changed file, the first `worldConfig` source included, in an upgrade of its own.

  A rollback below this version also keeps the file unchanged.
- **`podAnnotations` cannot set `checksum/world-config`.** The render refuses it: the key would
  replace the chart's revision on both pod templates, and a changed file would roll neither.
- **`key`** names the file inside the source (default `url4.toml`); it is always mounted as
  `url4.toml`. Set it explicitly on the first upgrade that adds `worldConfig`: `--reuse-values`
  keeps the previous release's values, which have no `worldConfig` block and so no default.
- The render refuses both sources at once, an empty `key`, a checksum without a source, and a
  missing or malformed checksum.

## Events stream (uniform executor, PRD 01)

Every run's frames now live on ONE JetStream stream, `url4-events` (subject
`url4-cloud.<topic>` per run), instead of one stream per run. The App and the runner pool
both declare it at startup and apply a changed limit; the values are rendered to both from
one place so they cannot disagree:

- `events.maxBytes` (default 1 GiB) — must fit the broker's JetStream file store, or startup
  fails naming `events.maxBytes`. When the store is full, JetStream drops the OLDEST frames
  of whichever run they belong to; a run in progress keeps publishing, it does not fail.
- `events.maxMsgsPerSubject` (default 20000) — one run's own frame retention bound, so a
  single long run cannot crowd every other run's frames out of the shared store.
- `events.maxAgeS` (default 86400) — the storage backstop: a run whose runner crashed before
  reclaiming its subject still clears itself after this many seconds, with no sweep needed.
- `events.replicas` (default 1) — same posture as `config.runQueueReplicas`: this chart bundles
  a single-node NATS subchart, which refuses `replicas > 1` outright.

**Upgrading past the per-run-stream layout.** No manual step. JetStream will not declare the
shared stream while a legacy `url4-cloud_<topic>` stream exists (their subjects overlap), so
the new App and worker delete every legacy stream at startup, log
`deleted N legacy per-run stream(s) at startup`, and declare `url4-events`. Once it exists,
JetStream refuses any new overlapping stream, so an old App still serving during the rollout
cannot create a legacy stream again. The frames of runs still in flight on a legacy stream are
lost at the cut-over (owner decision, 2026-09-27); to avoid that, scale the old App and runner
pool to 0 and let the queue drain before the sync. The deletion never touches `url4-events`,
`url4-runq`, or another workload's stream; an overlap with one of those still fails the
startup. `screamingface-engine admin purge-legacy-streams --dry-run` lists what would be
deleted, and without `--dry-run` it does the same deletion by hand.

**Alert rule.** `screamingface_engine_events_store_utilization_ratio > 0.8` for 5 minutes,
severity warning. Meaning: the events store is close to full, and JetStream will soon start
dropping the oldest frames of some run to make room for new ones. Response: raise
`events.maxBytes`, or grow the broker's JetStream store.

## Removed node-tier metrics

The node tier (unit 3, the separate sync-surface Deployment) was removed (uniform executor
PRD 05): every mount call now runs as a direct run on the runner pool. A dashboard or alert rule
that still queries a `screamingface_engine_node_sync_*` series must move to its replacement:

| Removed metric | Replacement |
|---|---|
| `screamingface_engine_node_sync_request_duration_seconds` | `screamingface_engine_mount_calls_total{path,status}` (counts by status) and `screamingface_engine_worker_handoff_latency_s` / `screamingface_engine_worker_run_duration_s` (time) |
| `screamingface_engine_node_sync_inflight` | `screamingface_engine_worker_slots_busy` |
| `screamingface_engine_node_sync_shed_total` | `screamingface_engine_mount_calls_total{status="503"}` (the run queue's per-caller cap) |
| `screamingface_engine_node_sync_budget_exhausted_total` | `screamingface_engine_mount_calls_total{status="504"}` |

## Artifact storage (OME-929)

A Run whose serialized result exceeds the inline cap (1 MiB) is parked under its content address,
and the terminal frame carries only a claim ticket the client redeems over `GET /artifacts/{id}`.

**With `config.runner: queue` this store cannot be a local directory.** Each run executes in a
worker pod whose disk is destroyed with it, so a result spilled there can never be served back:
the run succeeds, and then the client's redemption 404s — after every model call has been paid
for. A full DRACO 3-pass run is 11,902 calls and a ~3 MiB result, so it spills every time. The
App therefore **refuses to start** when `runner: queue` is paired with
`artifactStorage.backend: filesystem`.

```yaml
artifactStorage:
  backend: s3
garage:
  enabled: true
```

That is the whole configuration. No credentials to invent, no bucket to create, no commands to
run: the chart generates a stable key pair (reused across upgrades via `lookup`) and Garage
**adopts** it on first boot via its `--single-node`, `--default-access-key` and `--default-bucket`
server flags (Garage ≥ 2.3.0).

Set `artifactStorage.s3.accessKey` / `.secretKey`, or `existingSecret`, only to use credentials
you already have — e.g. when pointing at storage you already run.

Both halves are rendered from this one stanza — the Runner's copy in `configmap-runner-env.yaml`
and the App's in `configmap.yaml` — so a one-sided edit cannot point the writer and the reader at
different stores. That was the original defect: both read one variable that nothing set, and each
fell back to its own pod-local `/tmp`.

The read path goes **through the App**, not via a presigned URL, so the object store stays
cluster-internal and the SDK's existing size + sha256 verification is unchanged.

### Why there is no bootstrap Job

The obvious alternative — a `post-install` hook running `garage key create` — was rejected. It
makes Garage **mint** the credential, which the chart then has to discover and write back into a
Secret: that needs `create secrets` RBAC and turns a declarative chart into a two-phase one where
`helm template` no longer describes the result. Adopting a chart-stated key keeps the data flowing
one way.

Scripted layout is worse still. Garage's
[layout operations guide](https://garagehq.deuxfleurs.fr/documentation/operations/layout/) warns
that repeating `layout apply --version N` can leave a cluster **inconsistent**, and that the
version must be exactly one past the current one — precisely what a hook re-running on every
`helm upgrade` gets wrong. `--single-node` removes the operation rather than automating it.

### Credential rotation

The key pair is reused across upgrades on purpose: Garage adopts a default key only on **first
boot**, so minting a new pair later would leave the engine signing with credentials the store has
never seen — a 403 on every artifact, which reads like a code bug. To rotate deliberately, add the
new key to Garage (`garage key create` / `bucket allow`) and then set
`artifactStorage.s3.accessKey` / `.secretKey` to it.

### Expiry

Objects expire by **bucket lifecycle rule**, not by the App's sweeper — which is a no-op in `s3`
mode, because listing objects would need query-string signing beyond what the adapter's signer
supports. **A bucket with no lifecycle rule never expires artifacts.**

The **run blob store** (OME-1540) has its own store — see [Blob storage](#blob-storage-ome-1540)
— and in `s3` mode its bucket needs **its own** lifecycle rule: the App never deletes blobs
there either. Blobs live under `blobs/<tenant>/<run>/<hex>` (plus a `.json` metadata object
beside each). Without a rule on the blob bucket every upload stays until the blob volume fills,
and from then on every upload is refused with a 503.

One rule with no prefix filter, expiring after the artifact TTL (`URL4_CLOUD_ARTIFACT_TTL_S`,
default 48 h, rounded up to whole days because lifecycle rules count in days), serves both
buckets — apply it to the results bucket and to the blob bucket:

```json
{
  "Rules": [
    {
      "ID": "expire-after-artifact-ttl",
      "Status": "Enabled",
      "Filter": { "Prefix": "" },
      "Expiration": { "Days": 2 }
    }
  ]
}
```

Save it as `lifecycle.json` and apply it with any S3 client, once per bucket, e.g.
`aws s3api put-bucket-lifecycle-configuration --endpoint-url <endpoint> --bucket <bucket>
--lifecycle-configuration file://lifecycle.json`. With the bundled stores that is the results
Garage (`<fullname>-garage`, bucket `artifactStorage.s3.bucket`) and the blob Garage
(`<fullname>-garage-blobs`, bucket `blobs.storage.s3.bucket`), each with its own key pair from
its own Secret. Check that your store supports lifecycle expiry before relying on it; without
it, objects grow until removed by hand.

### Using storage you already run

Set `artifactStorage.s3.endpointUrl` (plus `accessKey`/`secretKey` or `existingSecret`) and leave
`garage.enabled` off. Only single-part PUT, streaming GET, HEAD and DELETE of one object are used.

**Caveat — path-style addressing.** The adapter addresses objects as `{endpoint}/{bucket}/{key}`.
That works with Garage, MinIO, SeaweedFS, Ceph RGW and Cloudflare R2. AWS S3 proper has deprecated
path-style in favour of virtual-hosted-style (`bucket.s3.region.amazonaws.com`), so pointing this
at real AWS S3 may fail — and it fails as a signing/404 error that looks like a credential
problem. Azure Blob is **not** S3-compatible at all and would need a new adapter behind the port.

## Blob storage (OME-1540)

Files a client uploads over `PUT /blob/sha256/<hex>` for its run's model calls are kept in a
store **separate from the artifact store** (owner decision 2026-11-03, #1603 review). Upload
volume is driven by clients — on a self-hosted engine with Access off, by anyone who can mint
a token — so sharing one store would let uploads fill the space a paid run needs to park its
result. Separated, **a full blob store fails uploads (503 with `Retry-After`) and never result
delivery.**

```yaml
blobs:
  storage:
    backend: ""        # "" = the same KIND as artifactStorage.backend, never the same store
    filesystemDir: ""  # filesystem mode; empty = <tmp>/screamingface-engine/blobs
    s3:
      endpointUrl: ""  # empty = the chart's second bundled Garage, below
      bucket: screamingface-blobs
      existingSecret: ""
    garage:
      persistence:
        size: 5Gi      # the blob quota
```

With `artifactStorage.backend: s3` and nothing else set, the chart renders **two** Garages:
`<fullname>-garage` for results and `<fullname>-garage-blobs` for blobs, each a single-node
StatefulSet with **its own volume** (`garage.persistence.size` and
`blobs.storage.garage.persistence.size`) and **its own key pair** (`<fullname>-artifact-storage`
and `<fullname>-blob-storage`, generated and adopted on first boot exactly as described above).
The blob Garage's cluster RPC secret is
**random** (`GARAGE_RPC_SECRET` in `<fullname>-blob-storage`, kept across upgrades by `lookup`),
not derived from the release name, and only the Garage pod receives it: the App and the runner
pool read the blob key pair by named `secretKeyRef`, not `envFrom`. With
`blobs.storage.s3.existingSecret`, that Secret must carry `GARAGE_RPC_SECRET` as well.
Set `blobs.storage.s3.endpointUrl` to use storage you already run; no blob Garage is rendered
then, and the render **fails** unless you also supply its credentials —
`blobs.storage.s3.existingSecret` (recommended; it must carry `URL4_CLOUD_BLOB_S3_ACCESS_KEY` and
`URL4_CLOUD_BLOB_S3_SECRET_KEY`) or both `accessKey` and `secretKey` — because a generated pair is
adopted only by the bundled blob Garage. Use a bucket, ideally a volume or quota, distinct from
the results store's, or the isolation is lost. Both the App and the runner pool carry a
`checksum/blob-secret` pod annotation, so a chart-owned key rotation rolls both.

**Concurrent first uploads.** The store's first metadata write is create-exclusive: an exclusive
`link` on the filesystem, a PUT with `If-None-Match: *` on S3. Garage v2.3.0 ignores that
condition (probed 2026-11-04: a second conditional PUT overwrote and answered 200), so on the
bundled Garage two uploads of the same new file racing within milliseconds can both answer `201`;
both hold the same verified bytes and the same record. A conforming S3 (AWS, MinIO) answers `412`
to the loser, which then answers `200`.

**Network policy.** The blob Garage's pods carry `app.kubernetes.io/component: garage-blobs`, not
`garage` (a shared value would put them behind the results Garage's Service). A platform
NetworkPolicy that admits App/runner ↔ Garage traffic by `component: garage` must also admit
`component: garage-blobs` on port 3900 (S3; and 3901, RPC, if your policy lists it), or every
blob request times out and uploads answer 503.

**Filesystem mode** is single-process only, like the artifact store: with `config.runner: queue`
the App refuses to start on a filesystem blob store, because the runner pool cannot read the
App's disk.

## Workload hardening

Both workloads — the same image, entered in its two modes — run non-root (uid 1000, the image's
own `USER`), with `ALL` capabilities dropped,
`allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true` + an `emptyDir` at `/tmp`, and a
`RuntimeDefault` seccomp profile — the Pod Security Standard **restricted** profile. Deploying into
a namespace labelled `pod-security.kubernetes.io/enforce: restricted` works as-is.

The App also sets `terminationGracePeriodSeconds` (45s) and a `preStop` sleep (5s): a terminating
pod is removed from endpoints and sent `SIGTERM` simultaneously, and endpoint removal takes seconds
to propagate — without the delay every rollout drops live WebSockets and in-flight sync holds.

The runner pool's drain is the mirror image: its `preStop` SIGTERMs the worker so the drain runs
inside the termination grace period, and its `PodDisruptionBudget` (`maxUnavailable: 1`)
serializes voluntary disruptions — never two pods down at once. A busy worker CAN be evicted
by a node drain; the `preStop` drain is what protects its runs (they close out as
`worker_draining`, not lost), so an expected eviction is not an incident.

## Labels

All resources carry the k8s **recommended labels** (`app.kubernetes.io/name·instance·version·
managed-by·part-of·component`) via `templates/_helpers.tpl` (docs/protocol.md §9). One deliberate
exception:

- The runner pool's pods carry `app.kubernetes.io/name: url4-runner` — the label aigateway's
  NetworkPolicy admits the run workload by (the old Job labels), so the pool replaces the Jobs
  without a CNI change.

## OCI image annotations

There is exactly one container image, and it should carry the OCI
**`org.opencontainers.image.*`** annotations
(opencontainers/image-spec) — set as `LABEL`s at build time, e.g.:

```dockerfile
LABEL org.opencontainers.image.title="screamingface-engine" \
      org.opencontainers.image.description="ScreamingFace screamingface-engine control plane + runner" \
      org.opencontainers.image.source="https://github.com/ScreamingFace/screamingface" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.vendor="OpenMined"
```

`image.repository` defaults to `ghcr.io/screamingface/screamingface-engine`; the tag defaults to the
chart `appVersion`. The App Deployment resolves to that one reference, and the runner pool to its
`-benchmark` pair.

## Lint / render

```bash
helm lint apps/screamingface-engine/deploy/helm
helm template apps/screamingface-engine/deploy/helm --set config.natsUrl=nats://n:4222
```

For a real end-to-end exercise of this chart — the same templates, values-only overrides — see
[`../kind/README.md`](../kind/README.md).

### Turning a deployment up to DEBUG, and what the probes ask (OME-942)

`config.logLevel` sets the level the `screamingface_engine` logger tree runs at, rendered to
BOTH halves — the App's ConfigMap and the runner pool's — as `URL4_CLOUD_LOG_LEVEL`. It was
previously readable by the code and settable by nobody, so no deployed pod could be turned up
during an incident:

```bash
helm upgrade ... --set config.logLevel=DEBUG   # then restart the pods
```

The probes ask two different questions and target two different endpoints:

| Probe | Path | Asks | On failure |
|---|---|---|---|
| `livenessProbe` | `/livez` | is this process up? | the pod is RESTARTED |
| `readinessProbe` | `/readyz` | has this pod's EVENT STREAM reached NATS at least once? | a new pod does not join the Service's endpoints |

Both used to target `/healthz`, which answers unconditionally — so the readiness probe could not
fail whatever the state of the pod's NATS connection. (That is read off the chart and the
endpoint. No incident is claimed; none was investigated.) Keep liveness broker-blind: a broker
outage must take pods out of rotation, not restart every replica. `/healthz` is still served,
unchanged, for anything outside this chart.

**Exactly what `/readyz` asks, and what it does not.** It asks the App's own event-stream
consumer (`app.state.stream`). The queue runner holds SEPARATE NATS connections and is not
probed, so a pod whose runner connections are dead while the consumer's is live still reports
ready. Both the check and the endpoint are time-bounded (3s and 4s) so the probe answers before
`readinessProbe.timeoutSeconds` rather than parking a handler the kubelet has stopped waiting
for. The 503 body's `reason` is a fixed literal — never the NATS URL and never the broker's own
error text, both of which reach an unauthenticated caller through the gateway's `/` route; the
detail is in the pod's log at WARNING.

**Cold-start gate only (ledger D8, owner decision).** `/readyz` asks the event stream until the
first ready answer, then latches ready for the life of the App and never asks again. The App is
pinned to one replica, so broker-aware readiness had nothing to route around: a NATS outage would
have emptied the Service and 503'd every route, including those that need no broker (token mint,
`/docs`, catalog REST, artifact GETs). What stays is the rollout gate — a new pod that cannot
reach NATS never takes traffic. A later outage shows in the pod's logs and on the run paths that
need the broker, not as a whole-API 503.

### Optional live activity

Structured activity defaults to `full` in Helm, local mode and workers. Set
`config.activityLevel: "off"` (Helm) or `URL4_CLOUD_ACTIVITY_LEVEL=off` (local/worker)
to disable it. Only `full` and `off` are supported. Explicit local Settings win over
environment configuration; the worker's deployment environment wins over queued
per-run values. Private/enclave operators can explicitly disable activity.

Full activity uses fixed 60-second heartbeats, safe producer observation timestamps and a
rolling 100-record/s, burst-200 budget, reserving 40 tokens from routine starts/heartbeats
for retries and outcomes. It has no lifetime emission cutoff and creates no archive.
Under pressure, optional records can be suppressed; this does not retry or fail the work.
The existing closing bridge-loss Log gains structured cumulative loss attributes in full
mode. That count covers all bridge Logs, and is neither a guaranteed live warning nor a
complete activity-loss count.

Off disables the new activity producer; existing lifecycle/results/accounting and operator
logs remain governed by their existing settings. The pre-existing operator-log
heartbeat retains its backoff in both modes; full mode adds an independent fixed heartbeat
owned by the activity observer. Removing its registration preserves operator diagnostics. This switch is not a deployment-wide privacy guarantee. Aggregate
privacy mode and the Client Logs tab are separate work.
