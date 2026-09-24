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

## The node tier (unit 3)

The sync surface (`GET /<mount>?q=`) can run as its own Deployment, separate from the App, so a
slow or crashing sync call cannot take down the WebSocket relays that in-flight ensemble runs
depend on. **Off by default** (`node.enabled: false`) — turn it on with:

```bash
--set node.enabled=true --set artifactStorage.backend=s3 --set garage.enabled=true
```

(or, pointing at storage you already run, `--set-string
artifactStorage.s3.endpointUrl=http://your-s3-endpoint:port` in place of `garage.enabled=true` —
`artifactStorage.backend=s3` alone is not enough to render: the chart also needs to know WHERE
the store is, from one of those two sources.)

**Needs S3.** The node's spill path (a response over 512 KiB) writes to the SAME object store
the App reads it back from, across pods — the chart REFUSES `node.enabled=true` paired with any
`artifactStorage.backend` other than `s3` (OME-929; the SAME failure mode for `runner: queue` +
`artifactStorage.backend: filesystem` is refused at App STARTUP, one tier over, rather than by
this chart — a local single-process run is a legitimate shape the chart never renders at all).
`values-cloud.yaml` leaves the node off for exactly this reason: it does not set an s3 backend,
so turning the node on there needs the same two extra flags as above at install time.

**Its own label set.** The node Deployment's pods carry `app.kubernetes.io/name: url4-cloud` —
the SAME name as the App, so aigateway's own NetworkPolicy admits the node's outbound calls
without a CNI change — but `app.kubernetes.io/instance: <release>-node`, NOT the App's plain
`<release>`. This is deliberate (FX-80): the App's own Service and Deployment select on a bare
`{name, instance}` pair with no component qualifier, which is a SUPERSET match — before the
node's instance diverged, the App's Service silently fronted the node's pods too, and the App
Deployment's replace/evict blast radius silently covered them as well. Nothing on the App side
changes to fix this; the node's own instance value is what breaks the match.

> **If you run an aigateway NetworkPolicy of your own (outside this repo)**, it must admit peers
> by `app.kubernetes.io/name: url4-cloud` alone, not by `name` AND `instance` together — a policy
> that also matches on `instance` denies the node tier's calls, because the node's instance is
> never the App's.

**A platform that owns its NetworkPolicies.** Some GitOps projects deny the NetworkPolicy kind
to tenant charts; there the chart's node policy fails the whole sync. Set
`node.networkPolicy.enabled=false` and render the equivalent policy on the platform side: admit
ONLY the App (`app.kubernetes.io/name: url4-cloud` AND `app.kubernetes.io/component:
control-plane`) to `node.port`, and let the App reach the node pods (`component: node`) on that
port. The policy is the node's authentication boundary — never turn it off without that
replacement. `node.metrics.scrapeFrom` rides the same policy, so it renders nothing while off.

**Verifying the App-only NetworkPolicy on a real cluster.** `tests/unit/test_chart_render_node_tier.py`
and `verify_chart_wiring.py` prove the policy is CORRECTLY SHAPED at render time; neither proves a
CNI actually enforces it — `kind`'s default CNI does not enforce `NetworkPolicy` at all (test-plan
§3, T15), so a kind-based test cannot tell you this works. On a cluster whose CNI does enforce it,
confirm both directions after installing with `node.enabled=true`:

```bash
# From a pod that is NOT the App (must be REFUSED):
kubectl run np-probe --rm -it --image=curlimages/curl --restart=Never -- \
  curl -sS -m 3 http://<release>-<release>-node:9109/livez
# expect: no response / connection timed out (the request never reaches the node)

# From inside the App's own pod (must SUCCEED):
kubectl exec deploy/<release>-<release> -- \
  curl -sS -m 3 http://<release>-<release>-node:9109/livez
# expect: 200 (or whatever /livez answers once the node is up)
```

**Metrics on their own port.** `/metrics` is served on `node.metrics.port` (default `9110`),
separate from the request port `node.port` (`9109`) — a scrape can never compete with a sync
call for the same listener. The NetworkPolicy admits it via a SECOND, independent ingress rule,
gated on `node.metrics.scrapeFrom` (a list of NetworkPolicy peer objects, default `[]`): with no
peer configured, metrics is reachable from nowhere else in the cluster, and no rule renders at
all.

**The artifact-signing key (OQ-3.2).** The node signs a spilled artifact's short-lived `303`
`Location`; the App verifies it. The SAME `URL4_CLOUD_ARTIFACT_SIGNING_KEY` Secret must reach
both tiers — `artifactSigning.existingSecret` (recommended for GitOps) is created out-of-band.
Left empty (and with `artifactSigning.signingKey` also empty), the chart generates one and
reuses it across upgrades via Helm's `lookup` function — but `lookup` reads the LIVE cluster, so
it returns nothing under `helm template` (no cluster to query).

> **GitOps / offline-render workflows (ArgoCD, or any `helm template` that never talks to
> the target cluster) MUST set `artifactSigning.existingSecret` or `artifactSigning.signingKey`.**
> Left to the generated default, every offline render mints a NEW random key — and unlike a live
> `helm upgrade --install` (where `lookup` finds and reuses the cluster's existing copy), an
> offline render has no way to know there already is one. If that render is then applied, every
> in-flight signed artifact URL breaks, and the two tiers can end up disagreeing about which key
> is current. The `checksum/artifact-signing` pod annotation is keyed on the SOURCE of the key
> (`signingKey`, else `existingSecret`'s name, else a fixed constant), not the rendered Secret, so
> a chart-generated key does not by itself force a rollout on every sync — but the Secret's actual
> VALUE still changes underneath it, which is the real hazard `existingSecret`/`signingKey` closes.

**Web tools are off on the node tier.** The node Deployment's `envFrom` never references the
Tavily Secret, regardless of `tavily.enabled` — only the runner pool does. A sync call has a 30 s
budget (`node.requestTimeoutS`), and a web-tool-enabled mount usually exhausts that budget before
its iteration count (contracts.md C4); operators should prefer `web_search = false` on model
routes the sync surface serves.

**Sizing the node pod (item 11, B6 review).** The defaults — `node.resources.limits.memory: 512Mi`,
`node.maxInflightPerWorker: 2` (× `node.workers: 1` = an in-flight cap of 2), and
`node.resultHardCapBytes: 67108864` (64 MiB, in bytes — the setting takes a byte count, not a
quantity suffix) — assume a small, in-memory response per request. One capped
response can hold TWO OR MORE copies in memory at once (the body itself, plus at least one
serialization/encoding copy) and, for a spilled result, an S3 upload buffer on top of that — so at
`maxInflight=2` a pod can carry several times the 64 MiB cap in flight before it ever reaches the
memory limit's headroom. If a `[data]` file mount on this node serves large files, raise
`node.resources.limits.memory` (and, correspondingly, `node.resources.requests.memory`) to keep
that headroom, or lower `node.resultHardCapBytes` instead if the response size is what should
shrink.

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
managed-by·part-of·component`) via `templates/_helpers.tpl` (docs/protocol.md §9). Two deliberate
exceptions:

- The runner pool's pods carry `app.kubernetes.io/name: url4-runner` — the label aigateway's
  NetworkPolicy admits the run workload by (the old Job labels), so the pool replaces the Jobs
  without a CNI change.
- The node tier's pods keep `app.kubernetes.io/name: url4-cloud` (the SAME name as the App, for
  the same aigateway-admission reason) but carry `app.kubernetes.io/instance: <release>-node`,
  not the App's own `<release>` (FX-80). See "The node tier" section above for why.

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

### Optional live activity

Set `config.activityLevel: "full"` on public deployments to emit the safe v1 model-call
activity stream. The default is `"off"`; private/enclave deployments should explicitly keep
it off. Only `full` and `off` are supported. The worker's deployment environment wins over
any queued per-run value. For local mode, set `URL4_CLOUD_ACTIVITY_LEVEL=full` in the
operator environment (or the equivalent local `Settings.activity_level`).

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
