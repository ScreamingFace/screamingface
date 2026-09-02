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
  actually run rather than scheduling BestEffort
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
mid-drain. The PodDisruptionBudget (`maxUnavailable: 0`) is the other half: a node drain or
voluntary disruption can never take a slot away from a run that is using it.

**Admission.** The App admits runs on **queue depth** (OME-1091): a run is refused with 503 +
`Retry-After` when the queue is at `run_queue_depth_ceiling` or the caller is at its in-flight
cap. This supersedes the OME-1065 quota-admission feature, which was retired with the Job
adapter — the counted resource changed from namespace quota headroom to queue depth, and the
cache-plus-reservation shape did not.

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
inside the termination grace period, and its `PodDisruptionBudget` (`maxUnavailable: 0`) means a
node drain or voluntary disruption can never evict a busy worker mid-run.

## Labels

All resources carry the k8s **recommended labels** (`app.kubernetes.io/name·instance·version·
managed-by·part-of·component`) via `templates/_helpers.tpl` (docs/protocol.md §9). The runner
pool is the one deliberate exception: its pods carry `app.kubernetes.io/name: url4-runner` — the
label aigateway's NetworkPolicy admits the run workload by (the old Job labels), so the pool
replaces the Jobs without a CNI change.

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
