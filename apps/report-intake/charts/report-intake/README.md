# report-intake Helm chart

Deploys the service that accepts a ScreamingFace client's error report, stores it, and files it
into the private tracker. Service internals are in
[`apps/report-intake/README.md`](../../README.md); this file is about the *shape* of the chart —
its values, its topology and what it refuses.

**The install runbook is [`apps/report-intake/DEPLOYMENT.md`](../../DEPLOYMENT.md)**: where each
install-time value comes from, the Cloudflare actions that live outside this repo, how to choose
`config.ticketSink`, how to drain the queue, and what to do when a render refusal fires.

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

## The edge rate limit (spec §7)

`config.anonRate` is **not** the limit spec §7 promises. Its key is the TCP peer, and inside the
cluster the mesh proxy is the peer on every request — so it is one bucket shared by every anonymous
caller on the internet, sized `replicaCount × limit`. It is the service-side spam brake and it
stays. `config.trustClientIpHeader` does not rescue it: both routes strip `CF-Connecting-IP`
unconditionally (spec §7 — a forwarded copy is client-controlled, and a rotated header buys a fresh
bucket per request while evicting real callers from a capped table), so it is `false` in every
posture this chart renders.

The per-caller half is `gateway.public.rateLimit`, an Envoy **`BackendTrafficPolicy`** on the
public route and no other. Off in `values.yaml`, on in `values-cloud.yaml`, defaulting to 20
requests per hour per client address.

**Two prerequisites it needs and this chart can neither install nor check, both failing open:**

| | What is missing | What happens |
|---|---|---|
| Envoy Gateway's rate-limit service | the Redis-backed deployment enabled in the `EnvoyGateway` config. `type: Global` is the only type that can bucket per caller — Envoy's *local* limiter has no `Distinct` matching, so all it could express is the shared bucket `config.anonRate` already is | the policy is not Accepted; the hostname serves unlimited |
| a `ClientTrafficPolicy` on the Gateway | `clientIPDetection` establishing the real client address. Behind Cloudflare and a cloud load balancer, the address Envoy sees is the *load balancer's*. This chart cannot render it: `ClientTrafficPolicy` targets the **Gateway**, which this chart does not install and other services share | `Distinct` buckets the internet into a handful of addresses |

After installing: `kubectl get backendtrafficpolicy <release>-report-intake-public-rate-limit -o yaml`
and read `status.conditions` for `Accepted=True`.

`sourceCIDRs` is IPv4-only by default and an IPv6 caller therefore matches no rule and is
unlimited. Add `::/0` where the Gateway terminates IPv6 client addresses — it is not the default
because a `sourceCIDR` the installed Envoy Gateway rejects makes the *whole* policy not-Accepted,
taking the IPv4 limit with it.

**A Cloudflare rate-limiting rule on `reports.screamingface.ai`, scoped to `POST /v1/reports`, is
still wanted.** It is in front of all of the above, sees the client before anything here can go
wrong, and costs a flood nothing in the cluster. That is also why `anonymous.enabled` does **not**
require the `BackendTrafficPolicy`: a deployment whose edge limit is Cloudflare's satisfies §7 and
is not forced into a Redis dependency.

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
| `gateway.public.rateLimit.enabled` without `anonymous.enabled` | the policy targets the public HTTPRoute by name; with no such route it attaches to nothing, limits nothing, and still reports Accepted |
| `gateway.public.rateLimit.enabled` with no `sourceCIDRs` | each entry is one rule, so an empty list is a policy with no rules — it renders, it is Accepted, and it limits nothing |
| `config.ticketSink: linear` without `config.linearTeamId` | an issue create with no `teamId` is refused on every report — a queue quietly growing rather than a pod that fails |
| `config.ticketSink: linear` without `linear.existingSecret` | no API key, so the app refuses to start; the alternative is a service that answers `202` to everything and files none of it |
| `authMode: mesh_or_turnstile` with `networkPolicy.enabled: false` | the peer check authenticates a *network*, so any pod that can dial the ClusterIP has its `X-User-Email` believed — the edge header-strip covers only traffic through the gateway. Set `networkPolicy.acknowledgeUnrestricted: true` where something outside this chart already restricts the Service |

## `values.schema.json`, and the line between it and the table above

Helm validates the coalesced values against `values.schema.json` **before** any template runs, so
the two layers cannot overlap without one hiding the other:

- **The schema types the values.** `config.port: "9109"`, `unit: hour`, a `config.authmode` typo,
  a `gateway.hostnames` block copied from the engine chart, a stale key left behind after a
  template was deleted. `additionalProperties: false` is the half that earns its keep: every one
  of those installs cleanly otherwise, and `Settings` is `extra="ignore"`, so the pod runs on a
  default while the values file says something else.
- **The templates refuse the combinations** — every row of the table above. None of them is
  duplicated as a schema `if/then`, deliberately: the schema runs first, so a conditional there
  would replace a paragraph naming the failure with `must be at least 1 item`, and
  `verify_chart_wiring.py` asserts several of those paragraphs by their words. Where a reader
  expects a conditional and finds none, a `$comment` in the schema says which guard owns it.

Three values also stay unconstrained on purpose, each with a `$comment` saying why:
`config.authMode` (the template's refusal explains what each mode *is*, and the verifier already
compares the rendered value to `config.py`'s `AuthMode` literal), `config.ticketSink` (`config.py`
keeps it a plain string so adding an adapter is one registry line — an enum here would re-add
exactly that coupling), and `config.deliveryTimeoutS`'s upper bound (arithmetic over two constants
in two modules; a third copy could drift into refusing a legal value).

## The environment surface

The ConfigMap renders **exactly** the fields on `report_intake.config.Settings`, plus uvicorn's
own `FORWARDED_ALLOW_IPS`; the three secret-valued fields (`DATABASE_URL`, `TURNSTILE_SECRET`,
`LINEAR_API_KEY`) come from Secrets on the Deployment. Nothing else, in either direction.

`LINEAR_API_KEY` is the one entry read as `optional: true`: the Secret naming it is expected
**not** to exist, because `config.ticketSink` is `queue` on every deployment of this chart today.
See "Filing into Linear directly" below.

That equality is enforced twice, because `Settings` is `extra="ignore"` and a name mismatch is
otherwise completely silent — for `AUTH_MODE` that means a pod serving with authentication
disabled while the manifest says otherwise:

- `apps/report-intake/tests/unit/test_chart_environment.py` — both directions, in this app's own
  gates, with no helm on the box.
- `.github/scripts/verify_chart_wiring.py` — against the **rendered** manifest, which is what
  survives a rename that keeps the templates parseable.

`create_app` is the third: it refuses to start on a `REPORT_INTAKE_*` variable matching no field.

## Filing into Linear directly

`config.ticketSink` selects the adapter. It is `queue` — v1's, and spec §9's decision: the
`reports` table *is* the queue, an agent files each row through MCP during triage, and no Linear
credential exists anywhere in this pod's environment.

`linear` is the other name, and **selecting it is a decision rather than a tuning knob.**
CLAUDE.md rule 9 says product code reaches Linear through MCP only; the amendment that would
carve out an exception for this service (`OME-976`) has not been made. Selecting it also puts a
long-lived credential to the private tracker the team works in inside this pod. The chart takes
no position on whether that should happen — it refuses to render the selection half-configured,
and the app refuses to start on the same conditions:

```sh
--set config.ticketSink=linear \
--set config.linearTeamId=<the team's UUID, not a key like OME> \
--set linear.existingSecret=<a Secret holding the API key>
```

There is deliberately **no `linear.enabled` flag**. A second switch could disagree with
`config.ticketSink`, and both directions of that disagreement are bad: a credential mounted for
nobody, or a pod that starts and files nothing.

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
