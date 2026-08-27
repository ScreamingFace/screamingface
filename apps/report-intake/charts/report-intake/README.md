# report-intake Helm chart

Deploys the service that accepts a ScreamingFace client's error report, stores it, and files it
into the private tracker. Service internals are in
[`apps/report-intake/README.md`](../../README.md); this file is about the deployment.

## Two hostnames, and why it is not one

The service admits two caller classes at one endpoint (spec §7), and the *edge* is what tells
them apart — inside the cluster the mesh proxy is the TCP peer on both.

| | Identity hostname | Public hostname |
|---|---|---|
| value | `gateway.identity.enabled` | `anonymous.enabled` |
| Cloudflare Access | yes, and a `SecurityPolicy` re-verifies the assertion | none |
| `X-User-Email` | **set** from the verified `email` claim | **removed**, unconditionally |
| `CF-Connecting-IP` | removed | removed |
| paths published | `/v1/reports` only | `/v1/reports` only |
| what the service does | admits on identity, binds the address into the row | rate limit, then Turnstile |

Both routes match `PathPrefix: /v1/reports`, not `/`. `/healthz` and `/readyz` are deliberately
ungated and unbudgeted — spec §7's bot gate never gates liveness — and `/readyz` runs a database
query per request, so publishing them on the Access-free hostname would put one unauthenticated
query per HTTP request at the one endpoint outside the rate limiter. Nothing needs them through
the edge: the kubelet dials the Pod IP, `helm test` dials the ClusterIP Service.

**Do not "simplify" these into one route with `spec.jwt.optional: true`.** That is a full identity
bypass, not a shortcut: with `optional: true` the JWT filter is skipped entirely for a token-less
request, so `claimToHeaders` never runs and a client-supplied `X-User-Email` arrives untouched.
The peer is the mesh proxy, so the backend's peer check passes and the forged address is believed
and stored.

## Install

A bare install is deliberately safe and not useful — `config.authMode: disabled` is
**loopback-only**, so a pod installed from `values.yaml` alone answers `403` to everything that
reaches it through a mesh. The cloud posture is `values-cloud.yaml`:

```sh
helm install reports apps/report-intake/charts/report-intake \
  -f apps/report-intake/charts/report-intake/values-cloud.yaml \
  --set gateway.parentRef.name=<your Gateway> \
  --set gateway.identity.cloudflareAccess.teamDomain=<team>.cloudflareaccess.com \
  --set gateway.identity.cloudflareAccess.audience=<the Access application's AUD> \
  --set turnstile.existingSecret=<Secret holding the Turnstile secret> \
  --set database.existingSecret=<Secret holding a Postgres URL> \
  --set config.allowedNetworks[0]=<your cluster's Pod CIDR> \
  --set networkPolicy.clientPodNames[0]=<app.kubernetes.io/name of the mesh gateway's data plane> \
  --set networkPolicy.clientNamespace=<its namespace>
```

Each of those has no default because the chart cannot know it, and each fails the render rather
than defaulting to something plausible. See "What this chart refuses to render".

The last two are the ones that look defaultable and are not. Blanket RFC1918 for
`config.allowedNetworks` renders, installs, and works — and admits any private address that can
reach the Service to present a mesh identity. A NetworkPolicy left off renders, installs, and
works — and leaves every pod in the cluster able to dial the ClusterIP directly, where the
HTTPRoute header-strip does not apply. Nobody is ever forced to narrow a value that already
works, so neither ships with one.

**Prerequisites, none installed here:** the Gateway API CRDs, a GatewayClass, and **Envoy
Gateway** specifically — `SecurityPolicy` is its extension rather than core Gateway API. Plus the
two Secrets above, and a Cloudflare Turnstile widget whose *site* key lives in the client. The
site key is deliberately not a value of this chart: this service never reads it.

**And a Cloudflare rate-limiting rule on the public hostname.** Spec §7 promises anonymous callers
an edge rate limit, and only the edge can see the real client: inside the cluster the mesh proxy is
the TCP peer on every request, so `config.anonRate` is effectively ONE bucket shared by every
anonymous caller on the internet — a service-side spam brake, not a per-caller limit. Create the
rule on `reports.screamingface.ai` scoped to `POST /v1/reports` before publishing that hostname.
`config.trustClientIpHeader` is **not** the way to get per-caller keys here: both routes strip
`CF-Connecting-IP` unconditionally (spec §7 requires it — a forwarded copy is client-controlled,
and a rotated header buys a fresh bucket per request while evicting real callers from a capped
table), so the setting stays `false` in every posture this chart renders.

## What this chart refuses to render

Every refusal below is a configuration that installs cleanly and then fails somewhere nobody is
watching. `helm upgrade` would report success in each case.

| Configuration | Why it is refused |
|---|---|
| `anonymous.enabled` without `turnstile.enabled` | a public hostname with no Access in front and no bot gate behind is an unauthenticated write straight into the private tracker |
| `authMode: mesh_or_turnstile` without `config.allowedNetworks` | the peer check denies everything, so nothing can ever be mesh-verified; the app refuses to start too |
| `authMode: mesh_or_turnstile` without `turnstile.enabled` | siteverify rejects *our* secret, which the gate correctly reads as unevaluable — every anonymous report is `503` forever while the pod reports itself ready |
| `gateway.enabled` with `authMode: disabled` | loopback-only behind an edge: every request through the mesh gets `403`, which reads as a routing fault |
| `gateway.enabled` with neither route enabled | an edge with nothing attached to it |
| `gateway.identity.enabled` without `gateway.enabled` | the `SecurityPolicy` would target a route that does not exist, attach to nothing, and still report Accepted |
| `config.forwardedAllowIps: "*"` | uvicorn would rewrite `request.client.host` from a client-supplied `X-Forwarded-For` for every peer — the address both the identity check and the rate-limit key read |
| `networkPolicy.enabled` with no peers | an ingress rule with no `from:` admits every source |
| `authMode: mesh_or_turnstile` with `networkPolicy.enabled: false` | the peer check authenticates a *network*, so any pod that can dial the ClusterIP has its `X-User-Email` believed — the edge header-strip covers only traffic through the gateway. Set `networkPolicy.acknowledgeUnrestricted: true` where something outside this chart already restricts the Service |

## The environment surface

The ConfigMap renders **exactly** the fields on `report_intake.config.Settings`, plus uvicorn's
own `FORWARDED_ALLOW_IPS`; the two secret-valued fields (`DATABASE_URL`, `TURNSTILE_SECRET`) come
from Secrets on the Deployment. Nothing else, in either direction.

That equality is enforced twice, because `Settings` is `extra="ignore"` and a name mismatch is
otherwise completely silent — for `AUTH_MODE` that means a pod serving with authentication
disabled while the manifest says otherwise:

- `apps/report-intake/tests/unit/test_chart_environment.py` — both directions, in this app's own
  gates, with no helm on the box.
- `.github/scripts/verify_chart_wiring.py` — against the **rendered** manifest, which is what
  survives a rename that keeps the templates parseable.

`create_app` is the third: it refuses to start on a `REPORT_INTAKE_*` variable matching no field.

## Two things that will bite you

**`FORWARDED_ALLOW_IPS` must be disjoint from `config.allowedNetworks`, not merely narrow.**
Uvicorn's proxy-headers middleware is always on and overwrites `request.client.host` from a
client-supplied `X-Forwarded-For` for any peer inside it — and that address is both the mesh
identity check and the rate-limit key. A single trusted address that happens to fall inside
`allowedNetworks` re-opens the whole check for exactly the peers it exists to authenticate. The
chart refuses `"*"`; Helm has no CIDR arithmetic, so the general overlap is checked by
`verify_chart_wiring.py` and by the app at boot.

**`replicaCount > 1` needs a shared database, and is otherwise safe.** The retry sweep runs in
every replica and claims rows by a per-row conditional UPDATE against `lease_expires_at`, so the
database arbitrates and one bug report cannot become two tickets. Do not turn it into a
leader-elected singleton. What is *not* safe is the image's default sqlite file: it is per-Pod and
does not survive a restart. Point `database.existingSecret` at a real Postgres URL.
