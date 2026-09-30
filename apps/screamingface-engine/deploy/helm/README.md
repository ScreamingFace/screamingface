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
cap. This supersedes the OME-1065 quota-admission feature, which was retired with the Job
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

### Using storage you already run

Set `artifactStorage.s3.endpointUrl` (plus `accessKey`/`secretKey` or `existingSecret`) and leave
`garage.enabled` off. Only single-part PUT, streaming GET, HEAD and DELETE of one object are used.

**Caveat — path-style addressing.** The adapter addresses objects as `{endpoint}/{bucket}/{key}`.
That works with Garage, MinIO, SeaweedFS, Ceph RGW and Cloudflare R2. AWS S3 proper has deprecated
path-style in favour of virtual-hosted-style (`bucket.s3.region.amazonaws.com`), so pointing this
at real AWS S3 may fail — and it fails as a signing/404 error that looks like a credential
problem. Azure Blob is **not** S3-compatible at all and would need a new adapter behind the port.

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
