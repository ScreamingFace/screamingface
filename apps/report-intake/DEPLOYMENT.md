# report-intake Deployment

This runbook deploys `apps/report-intake` as a containerized FastAPI service on Kubernetes. The
chart is database-agnostic: it reads `REPORT_INTAKE_DATABASE_URL` from a Secret and runs Tortoise
migrations as a Helm `pre-install`/`pre-upgrade` Job.

Read this before installing. **A bare install of `values.yaml` is deliberately safe and useless** —
`config.authMode: disabled` is loopback-only, so a Pod installed that way answers `403` to
everything arriving through a mesh, and no route, no NetworkPolicy and no edge policy is rendered.
The deployable posture is `values-cloud.yaml`, which refuses to render until you supply values the
chart cannot know. That is the whole design: each refused value decides who may file a report or
who may be believed about who they are, and a value that already works is one nobody is ever
forced to narrow.

Chart internals — the values, the topology, what each guard protects — are in
[`charts/report-intake/README.md`](charts/report-intake/README.md). This file is the install.

## Artifacts

- Container image: `ghcr.io/screamingface/screamingface-report-intake:<version>`, published by
  `.github/workflows/release-report-intake.yml` on a `report-intake-v*` tag, amd64 and arm64.
- Chart: `oci://ghcr.io/screamingface/screamingface/charts/report-intake`, same tag, same version.
  A packaged chart's `appVersion` is set from the tag and the image helper falls back to it, so a
  released chart pins the exact image that release built without any values file naming a version.
- Dev images: `.github/workflows/dev-build-report-intake.yml` pushes
  `ghcr.io/screamingface/screamingface-report-intake:main-<shortsha>` and the same tag to
  `acropenmined.azurecr.io` on every merge to `main`. Same repository, immutable tags, never
  `:latest`. A dev cluster tracks `main` with `--set image.tag=main-<shortsha>` on the chart it
  already has — nothing else changes.

## Prerequisites, none installed by this chart

- **Gateway API CRDs, a GatewayClass, and a Gateway** for the routes to attach to.
- **Envoy Gateway specifically.** `SecurityPolicy` and `BackendTrafficPolicy` are its extensions,
  not core Gateway API. The identity hostname does not work without it, and neither does the edge
  rate limit.
- **Envoy Gateway's rate-limit service** (the Redis-backed one, enabled in the `EnvoyGateway`
  config) if you want `gateway.public.rateLimit`. See [The edge rate limit](#the-edge-rate-limit).
- **A `ClientTrafficPolicy` on the Gateway** with `clientIPDetection`, for the same reason.
- **Postgres — required, with no sqlite fallback for any deployment.** The image can open a
  sqlite file and the test suite runs on one, but a sqlite URL in `report-intake-db` yields a
  service that never becomes Ready. Migrations run as a Helm hook Job in its **own** Pod with its
  own filesystem, so the schema is created in a file the application Pod never sees; the Job exits
  0 and is reaped, the Deployment finds no `reports` table, and `/readyz` fails closed forever
  while `/healthz` keeps answering 200. The result is a Running-but-never-Ready Pod that reads
  like a routing fault. Observed on a cluster, not reasoned about.
- **Two Secrets** — the database URL and the Turnstile secret. See [Secrets](#secrets).
- **A Cloudflare Access application, a Turnstile widget, DNS for two hostnames, and a rate-limiting
  rule.** All four are dashboard actions outside this repository — see
  [Cloudflare, outside this repo](#cloudflare-outside-this-repo).

## The two hostnames, and why it is not one

The service admits two caller classes at one endpoint (spec §7), and the **edge** is what tells
them apart: inside the cluster the mesh proxy is the TCP peer on both.

| | Identity hostname | Public hostname |
|---|---|---|
| value | `gateway.identity.enabled` | `anonymous.enabled` |
| Cloudflare Access | yes, and a `SecurityPolicy` re-verifies the assertion | none |
| `X-User-Email` | **set** from the verified `email` claim | **removed**, unconditionally |
| `CF-Connecting-IP` | removed | removed |
| paths published | `/v1/reports` only | `/v1/reports` only |
| what the service does | admits on identity, binds the address into the row | rate limit, then Turnstile |
| who it is for | the portal and the console, whose callers have an Access session | the Python SDK, which holds an Access token but parses only `exp` from it and so has no address to present |

**Do not merge them into one route with `spec.jwt.optional: true`.** That is not a
simplification, it is a full identity bypass. With `optional: true` the JWT filter is *skipped
entirely* for a token-less request, so `claimToHeaders` never runs and a client-supplied
`X-User-Email` reaches the backend untouched. The peer on that path is the mesh proxy, which is
inside `config.allowedNetworks`, so the in-process check believes the forged address — and the
report is stored, rendered and triaged as having come from that person. Two hostnames exist so the
route that cannot verify anything is also the route that strips everything.

Both routes match `PathPrefix: /v1/reports`, never `/`. `/healthz` and `/readyz` are deliberately
ungated and unbudgeted (spec §7 — the bot gate never gates liveness), and `/readyz` runs a database
query per request, so a `/` prefix would publish one unauthenticated query per HTTP request at the
one endpoint outside the limiter. Nothing needs the probes through the edge: the kubelet dials the
Pod IP and `helm test` dials the ClusterIP Service.

## The install-time values

Eight values have no usable default. Six of them stop the render; the other two have a *name* but
no object behind it, which is worse to discover, so treat all eight as install input.

| Value | Where it comes from | Left unset |
|---|---|---|
| `gateway.parentRef.name` | the Gateway the routes attach to: `kubectl get gateway -A` | **render refused** |
| `gateway.identity.cloudflareAccess.teamDomain` | Cloudflare Zero Trust → Settings → the team domain, `<team>.cloudflareaccess.com`. A bare host: the issuer and the JWKS URL are both derived from it | **render refused** |
| `gateway.identity.cloudflareAccess.audience` | the Access application's **AUD tag** (Access → Applications → your app → Overview) | **render refused** — without it, any valid token from any application in the team authenticates here |
| `turnstile.existingSecret` | a Secret you create holding the Turnstile **secret** key | **render refused** |
| `config.allowedNetworks` | your cluster's Pod CIDR — see below | **render refused** |
| `networkPolicy.clientPodNames` | `app.kubernetes.io/name` on the mesh gateway's data-plane Pods | **render refused** |
| `database.existingSecret` | a Secret holding a Postgres URL under key `database-url` | **not refused** — defaults to the *name* `report-intake-db`. If no such Secret exists the Pod never starts, and the migration Job fails first |
| `networkPolicy.clientNamespace` | the namespace those data-plane Pods run in | **not refused** — defaults to the release namespace, which silently admits nobody if the mesh gateway lives elsewhere |

Finding the two cluster-specific ones:

```bash
# The Pod CIDR. Any of these, depending on the cluster:
kubectl get node -o jsonpath='{.items[0].spec.podCIDR}{"\n"}'
az aks show -g <rg> -n <cluster> --query networkProfile.podCidr -o tsv

# The mesh gateway's data plane — its pod label and its namespace.
kubectl get pods -A -l gateway.envoyproxy.io/owning-gateway-name --show-labels
```

**`config.allowedNetworks` is the value it is most tempting to default and the one you must
narrow.** Blanket RFC1918 renders, installs and works — and it means any private address that can
reach the ClusterIP may present a mesh identity and be believed. It authenticates a *network*, not
a workload, so even the correct Pod CIDR is every workload in the cluster; the NetworkPolicy is
what turns that back into "the mesh gateway". That is why the chart refuses `mesh_or_turnstile`
with the policy off unless you set `networkPolicy.acknowledgeUnrestricted: true` and say so.

**`config.forwardedAllowIps` must be *disjoint* from `config.allowedNetworks`, not merely narrow.**
It is uvicorn's own variable, deliberately unprefixed and not a `Settings` field, and uvicorn's
proxy-headers middleware is always on: it overwrites `request.client.host` from a client-supplied
`X-Forwarded-For` for any peer inside it. That address is what both the mesh identity check and the
rate-limit key read, so a single trusted address falling inside `allowedNetworks` re-opens the
check for exactly the peers it exists to authenticate. The chart refuses `"*"`; Helm has no CIDR
arithmetic, so the general overlap is checked by `.github/scripts/verify_chart_wiring.py` and by
the app at boot. The default `127.0.0.1` is correct for every posture this chart renders.

## Secrets

Neither literal is ever a chart value.

```bash
kubectl create namespace reports

# The database URL carries a password. The key name is database.existingSecretKey.
kubectl -n reports create secret generic report-intake-db \
  --from-literal=database-url='postgres://user:password@host:5432/report_intake'

# The Turnstile SECRET key, from the widget you created in the Cloudflare dashboard.
# The matching SITE key is NOT here: it is a browser-side value this service never reads,
# and an environment variable no Settings field reads makes the Pod refuse to start.
kubectl -n reports create secret generic report-intake-turnstile \
  --from-literal=turnstile-secret='0x4AAA...'
```

## Cloudflare, outside this repo

Four dashboard actions. None is installable from here and each fails in a way the cluster cannot
report.

1. **DNS for both hostnames**, proxied. `reports.screamingface.ai` (public) and
   `reports-internal.screamingface.ai` (identity) in `values-cloud.yaml`; change them there or with
   `--set`. They must resolve to the ingress the Gateway publishes.
2. **A Cloudflare Access application on the identity hostname only.** Its policy decides who may
   file a report as themselves. Take the **AUD tag** from its Overview into
   `gateway.identity.cloudflareAccess.audience`, and the team domain into `teamDomain`. Putting an
   Access application on the *public* hostname instead would defeat the point of having one —
   anonymous submission is spec §9's accepted decision, because the client producing the richest
   reports is the one that cannot authenticate.
3. **A Turnstile widget bound to the public hostname.** Its *secret* key goes into the Secret
   above; its *site* key goes into the client that renders the challenge, never into this chart.
   Without a working secret, siteverify rejects this service's own credentials, the gate reads as
   *unevaluable*, and every anonymous report is answered `503` **forever while the Pod reports
   itself healthy and ready**. That is why the chart refuses `mesh_or_turnstile` with
   `turnstile.enabled: false`.
4. **A rate-limiting rule on the public hostname, scoped to `POST /v1/reports`.** It sits in front
   of everything in the cluster and costs a flood nothing here. Create it before publishing that
   hostname.

## The edge rate limit

`config.anonRate` is **not** spec §7's rate limit. Its key is the TCP peer, and in a cluster the
mesh proxy is the peer on every request — so it is one bucket shared by every anonymous caller on
the internet, sized `replicaCount × anonRate.limit`. Keep it: it is the service-side spam brake.

The per-caller half is `gateway.public.rateLimit`, a `BackendTrafficPolicy` on the public route and
no other, defaulting to 20 requests per hour per client address. `values-cloud.yaml` turns it on.
The identity route is deliberately never a target: its callers are already verified, and every
request there arrives from the mesh proxy, so a per-source-address bucket would be one bucket.

**It has two prerequisites this chart can neither install nor check, and both fail open** — the
hostname keeps serving and nothing reports a fault:

- **Envoy Gateway's rate-limit service.** `type: Global` is the only type that can bucket per
  caller; Envoy's *local* limiter has no `Distinct` matching, so all it could express is the shared
  bucket `config.anonRate` already is. Global needs the Redis-backed rate-limit service enabled in
  the `EnvoyGateway` config, which is not part of a default Envoy Gateway install.
- **A `ClientTrafficPolicy` on the Gateway** with `clientIPDetection` (an `xForwardedFor` hop
  count, or Cloudflare's header). Without one, the address Envoy treats as the client is the *load
  balancer's*, and `Distinct` buckets the whole internet into a handful of addresses. This chart
  does not render it: `ClientTrafficPolicy` targets the **Gateway**, which this chart does not
  install and which other services attach to.

Check it landed:

```bash
kubectl -n reports get backendtrafficpolicy reports-report-intake-public-rate-limit \
  -o jsonpath='{.status.ancestors[*].conditions[*].type}{"\n"}'
```

`sourceCIDRs` is IPv4-only by default, so an **IPv6 caller matches no rule and is unlimited**. Add
`::/0` where the Gateway terminates IPv6 client addresses. It is not the default because a
`sourceCIDR` the installed Envoy Gateway rejects makes the whole policy not-Accepted, taking the
IPv4 limit with it — on the one hostname that accepts unauthenticated writes.

If you do not have the rate-limit service, set `gateway.public.rateLimit.enabled: false` and rely
on the Cloudflare rule. `anonymous.enabled` does not require this policy, precisely so that
deployment is possible without a Redis dependency.

## Install

```bash
export CHART=apps/report-intake/charts/report-intake

helm upgrade --install reports "$CHART" \
  --namespace reports \
  --create-namespace \
  --values "$CHART/values-cloud.yaml" \
  --set gateway.parentRef.name=<your Gateway> \
  --set gateway.parentRef.namespace=<its namespace> \
  --set gateway.identity.cloudflareAccess.teamDomain=<team>.cloudflareaccess.com \
  --set gateway.identity.cloudflareAccess.audience=<the Access application's AUD> \
  --set turnstile.existingSecret=report-intake-turnstile \
  --set database.existingSecret=report-intake-db \
  --set 'config.allowedNetworks[0]=<pod-cidr>' \
  --set 'networkPolicy.clientPodNames[0]=<mesh-data-plane-pod-name>' \
  --set networkPolicy.clientNamespace=<mesh-data-plane-namespace> \
  --wait
```

Quote indexed `--set` keys in shells such as zsh. From the published chart, replace the path with
`oci://ghcr.io/screamingface/screamingface/charts/report-intake --version <version>` and pass
`--values` a local copy of `values-cloud.yaml`.

`replicaCount` is `2` in `values-cloud.yaml` and **more than one replica is safe** — the retry
sweep runs in every replica and claims rows by a per-row conditional `UPDATE` against
`lease_expires_at`, so the database arbitrates and one bug report cannot become two tickets. Do not
turn it into a leader-elected singleton. What is *not* safe above one replica is the image's sqlite
default, which is per-Pod.

### Migrations

The chart runs, in a `pre-install`/`pre-upgrade` hook Job before any Pod is scheduled:

```bash
tortoise -c report_intake.db.TORTOISE_CONFIG migrate
```

**The service never migrates itself**, and this is not a preference: auto-migrating means every
replica racing the same DDL on a fresh database. Until the Job has run, `/readyz` fails closed —
it queries the `reports` *table*, not the connection, precisely so "migration not applied" is not
mistaken for a healthy Pod, and that is what keeps an unmigrated Pod out of the load balancer. If
the Job fails, no Pod ever becomes ready; read its logs before anything else.

### Probes

Liveness is `/healthz` and readiness is `/readyz`, and the split is load-bearing. `/healthz` is
static and touches nothing: a liveness probe that fails when the database is down turns one bad
database into a restart loop across every replica, which is strictly worse than serving `503` to
writes. Never point liveness at `/readyz`.

## Choosing the sink

`config.ticketSink` selects the adapter that files a report. There are two names.

**`queue` — the default, and what every deployment runs today.** The `reports` table *is* the
queue: a row is marked `queued` and an agent files it into Linear through MCP during triage. The
reporter gets a `ref` and `delivery.state: "pending"`, which the success shape already models. No
Linear credential exists anywhere in this Pod's environment. This is spec §9's decision, not a
placeholder.

**`linear` — a decision, not a tuning knob.** It files through Linear's GraphQL API directly.
Selecting it means two things at once:

- Repo `CLAUDE.md` **rule 9** says product code reaches Linear through MCP only, and the amendment
  that would carve out an exception for this service (`OME-976`) **has not been made**. Nothing in
  this repository amends it; shipping the adapter did not select it.
- It puts a long-lived credential to the private tracker the team works in inside a Pod that
  accepts unauthenticated writes.

The chart takes no position on whether that should happen. It refuses to render the selection
half-configured, and the app refuses to start on the same conditions:

```bash
--set config.ticketSink=linear \
--set config.linearTeamId=<the team's UUID, not a key like OME> \
--set linear.existingSecret=<a Secret holding the API key, key `api-key`>
```

`linearTeamId` is `IssueCreateInput.teamId`, a UUID. A team *key* posted as an id is a validation
error on every report rather than a boot failure on none — a queue quietly growing instead of a Pod
that fails. The key is a personal/scoped Linear API key, sent as a bare `Authorization:` header
with no `Bearer` prefix.

There is deliberately **no `linear.enabled` flag**: `config.ticketSink` is the switch, and a second
one could disagree with it — a credential mounted for nobody, or a Pod that starts and files
nothing. `REPORT_INTAKE_LINEAR_API_KEY` is rendered on the Deployment in *every* install from a
`secretKeyRef` with `optional: true`, so the Secret not existing is the normal state and the Pod
starts without it. Creating that Secret is the act rule 9 governs.

## Draining the queue

With `ticketSink: queue`, filing is a human or agent step. Three commands do it, reached by
`kubectl exec`. They are **not** an HTTP surface — spec §1 removed `GET /v1/reports/{ref}` on its
merits, and these are not it under another name.

```bash
kubectl -n reports exec deploy/reports-report-intake -- \
  report-intake queue list --limit 20

kubectl -n reports exec deploy/reports-report-intake -- \
  report-intake queue show r_8f21c0abcd12

kubectl -n reports exec deploy/reports-report-intake -- \
  report-intake queue mark-filed r_8f21c0abcd12 \
    --ticket-id OME-1042 \
    --ticket-url https://linear.app/openmined/issue/OME-1042
```

- **`list` shows `queued` rows only**, newest received first, with columns `REF`, `OCCURRED AT`,
  `ERROR`, `TRACE ID`, `REPLY TO`, `MESH CALLER`. The last two are different things and are
  labelled so nobody merges them: `REPLY TO` is whatever the reporter typed and is never identity;
  `MESH CALLER` is what the mesh verified. `pending` belongs to the retry queue, `delivered` is
  done, and `failed` is an alert rather than a backlog.
- **`show` prints the ticket body verbatim, or refuses it** — rendered by `render_ticket` from the
  stored payload, byte for byte what the sink would have sent. That is what you paste into Linear.
  Everything after the first blank line is that body. It runs the same fail-closed content check
  the dispatcher runs before calling a sink, so a body the service already refused to send is
  refused here too (exit `1`, with the reason on stderr) rather than handed to you to paste. It is
  never softened or redacted: verbatim or nothing.
- **`mark-filed` moves the row to `delivered` and records the ticket**, and does **not** increment
  `attempts`: that column is how hard *this service* tried, and a person filing by hand is not the
  sink having been called. Re-running with the same ticket id is idempotent; a *different* id is
  refused rather than overwriting the first.
- **stdout is the table, stderr is everything else**, so `queue list | grep` sees rows. Exit codes
  are distinguishable on purpose: `0` fine, `1` refused (no such ref, unreadable payload,
  conflicting ticket, a body the sink refuses as content), `2` argparse usage, `3` storage would
  not answer. Only `3` is worth retrying — and `3` is what both an unmigrated database and a
  database that cannot be reached at all give you.

`report-intake` with no arguments still runs uvicorn, byte for byte. That is the container's
`ENTRYPOINT`, so it is deployment behaviour rather than a default.

## Smoke checks

```bash
helm test reports --namespace reports --timeout 3m
```

The test Pod curls **both** probes through the ClusterIP Service. `/readyz` is the one that
matters: it proves the `reports` table is queryable, which is what the migration Job was for. A
test that hit only `/healthz` would pass on a release whose migration failed.

It deliberately does **not** post a report: the write endpoint is gated on identity or a Turnstile
token and a chart test has neither. To exercise the public path end to end you need a real
Turnstile token from a browser; to exercise the identity path, an Access session on the identity
hostname. What arrived is visible in `report-intake queue list`, with `MESH CALLER` populated for
the second and empty for the first — which is also how you confirm the two routes are behaving
differently.

## When a render refusal fires

Every refusal below describes a configuration that installs *cleanly* and then fails somewhere
nobody is watching; `helm upgrade` would report success in each case. Match on the fragment.

| The message says | What it means | What to do |
|---|---|---|
| `is not a mode this service has` | `config.authMode` is neither `disabled` nor `mesh_or_turnstile`; pydantic could not parse it either, so the Pod would crash on every start | use one of the two. There is no third |
| `set config.allowedNetworks to your cluster's Pod CIDR` | `mesh_or_turnstile` with nothing allowed to inject an identity. The peer check would deny everything: nothing could ever be mesh-verified, and every caller including the mesh's own would fall to the bot gate | set it. The app refuses to start for the same reason |
| `every anonymous report is answered 503 forever` | `mesh_or_turnstile` without Turnstile. siteverify would reject *this service's* credentials, which the gate correctly reads as unevaluable | `turnstile.enabled=true` plus `turnstile.existingSecret` |
| `networkPolicy.enabled=false — the peer check authenticates a NETWORK` | any workload in the cluster could dial the ClusterIP and have its `X-User-Email` believed. The HTTPRoute filters strip that header only from traffic through the edge | name your mesh gateway's data plane in `networkPolicy.clientPodNames`, or set `networkPolicy.acknowledgeUnrestricted=true` where something outside this chart already restricts the Service |
| `an unauthenticated write straight into the private tracker` | `anonymous.enabled` with no bot gate behind it | `turnstile.enabled=true`, or serve the identity hostname only |
| `requires gateway.enabled=true` | a public hostname or an identity route with no Gateway API edge to render it on | `gateway.enabled=true` |
| `authMode=disabled is not "no auth", it is LOOPBACK-ONLY` | an edge in front of a Pod that answers `403` to everything arriving through it. It reads as a routing fault | `config.authMode=mesh_or_turnstile` for any deployment with an edge |
| `renders a Gateway API edge with no route attached` | `gateway.enabled` with neither `anonymous.enabled` nor `gateway.identity.enabled` | enable at least one |
| `gateway.parentRef.name is required` | an HTTPRoute with no `parentRef` attaches to nothing and silently serves nothing | `kubectl get gateway -A` |
| `the issuer and JWKS URL are derived from it` | no Cloudflare team domain, so the JWT filter would verify against nothing | Zero Trust → Settings → team domain |
| `without an audience check every application in the team is accepted` | no AUD tag. This service turns a verified token into a stored identity, so that is a wider door than it looks | Access → Applications → Overview → AUD |
| `turnstile.existingSecret is required` | the chart never holds the literal | create the Secret, name it |
| `database.existingSecret is required` | the URL carries a password and is never a chart value | create the Secret with key `database-url` |
| `an ingress rule with no from: admits every source` | `networkPolicy.enabled` with no peers — an allow-all wearing the name of a restriction | set `clientPodNames` / `ingressCIDRs` / `allowFrom`, or turn the policy off deliberately |
| `it attaches to nothing, limits nothing, and still reports Accepted` | `gateway.public.rateLimit.enabled` without `anonymous.enabled`: the policy targets a route that does not exist | enable the public hostname, or turn the rate limit off |
| `an empty list is a policy with no rules` | `gateway.public.rateLimit.sourceCIDRs` is empty. Each entry is one rule | leave the default `0.0.0.0/0`, or name the ranges the Gateway terminates |
| `config.linearTeamId` | `ticketSink=linear` with no team. An issue create with no `teamId` is refused on every report | set the team's UUID, or go back to `queue` |
| `OME-976` | `ticketSink=linear` with no API key Secret — and the rule that governs the choice | read [Choosing the sink](#choosing-the-sink) before setting it |
| `uvicorn would rewrite request.client.host` | `config.forwardedAllowIps: "*"`, which lets any caller forge the address the identity check and the rate-limit key both read | name the real proxy's addresses, disjoint from `config.allowedNetworks` |

A message about `additional properties … not allowed`, `got string, want integer`, or `value must
be one of` is `values.schema.json`, not a template — Helm validates the coalesced values before
anything renders. It is usually a misspelled key: `config.authmode` and a stale block left over
from an older values file both install silently otherwise, because `Settings` is `extra="ignore"`
and the Pod then runs on a default while your values file says something else.

## Operations Notes

- The container listens on `0.0.0.0:9109` and exposes `/healthz` and `/readyz`. Its `HEALTHCHECK`
  uses `/healthz` for the same reason the liveness probe does.
- The ConfigMap renders **exactly** the fields on `report_intake.config.Settings`, plus uvicorn's
  own `FORWARDED_ALLOW_IPS`. The three secret-valued names come from Secrets on the Deployment.
  Nothing else, in either direction — the equality is asserted from both sides, because
  `extra="ignore"` makes a mismatch silent and for `AUTH_MODE` that means a production Pod running
  with authentication disabled while the manifest says otherwise.
- The Deployment carries a `checksum/config` annotation, so a `helm upgrade` that moves a value in
  the ConfigMap actually rolls the Pods. `envFrom` is read once, at container start.
- The migration Job reads the database URL and **nothing else**: it runs no application code, so a
  second copy of the auth posture there would be a second place a mismatch could hide.
- `automountServiceAccountToken: false`. This service calls no Kubernetes API — it talks to a
  database and to Cloudflare's siteverify. Mounting a token would hand an endpoint that accepts
  unauthenticated writes a cluster credential it has no use for.
- `config.trustClientIpHeader` stays `false` in every posture this chart renders. Both routes strip
  `CF-Connecting-IP` unconditionally, and trusting the header whenever the peer is inside
  `allowedNetworks` means trusting it always — the mesh proxy is the peer on every request.
- `config.deliveryTimeoutS` is coupled to the retry sweep's claim grace. Raising it far enough
  re-opens a window in which a sweeper on another replica claims a report the request path is still
  delivering — one bug report, two tickets. `create_app` refuses to start on the bad relation.
  Spec §2.2's number is `3`.
- A report is never lost, and `503` is the only status that means nothing was stored. A delivery
  failure is answered `202` with `delivery.state: "pending"`, and the retry queue owns it from
  there: six attempts over roughly 24 h, then terminal `failed`, logged at error.
- Rows are purged after `config.retentionDays` (90). The ticket is the durable artifact; the row
  exists for idempotency, retry and forensics.
