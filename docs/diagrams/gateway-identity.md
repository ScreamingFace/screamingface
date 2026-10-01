# Gateway identity — how a caller reaches a provider

How the ScreamingFace cloud stack answers "who is calling?". Cloudflare Access authenticates the
caller at the edge; Envoy re-verifies that assertion and re-injects the answer as one plain header;
url4-cloud carries it to each run; aigateway resolves it to an account and then resolves that
principal's effective credential for the requested provider.

Contract: <https://pulse.dev.openmined.org/docs/products/gateway-identity-flow/>

| Header | Source claim | Meaning |
| --- | --- | --- |
| `X-User-Email` | Cloudflare Access JWT `email` | The whole identity. It is the account's `username`, which is unique — so it is the key. |

Envoy **clears it off the inbound request** before re-injecting the verified value, so a client
cannot forge it. That guarantee is what everything below rests on.

The flow also carries a tenant, and a `common_name` for Cloudflare **service tokens**. Both are
deliberately ignored here: an email is globally unique, so a tenant adds nothing to a key built from
it, and automation is out of scope until the gateway issues its own API keys — a service-token caller
gets a 401 rather than being half-identified.

The `.mmd` files are the source of truth; the committed `.svg`/`.png` beside them were rendered
with `@mermaid-js/mermaid-cli` (`mmdc -i <file>.mmd -o <file>.svg`, and again with `-s 2` for the
PNG). Re-render after editing one, and keep the inline block below in step with it.

> The SVGs contain `<foreignObject>`, which is what makes `<b>` and wrapped labels work. They render
> in a browser, on GitHub and in any docs site, but a plain SVG rasterizer drops the text — use the
> PNG there.

---

## 1 · Request flow

The one counter-intuitive part: this is **not** header pass-through. The App that receives the
headers and the Runner Pod that calls aigateway are different processes, and the outgoing request
does not exist yet when the headers arrive — so identity is captured, serialized onto the Job spec
as plain env, and re-rendered by the connector.

[`gateway-identity-flow.svg`](gateway-identity-flow.svg) · [PNG](gateway-identity-flow.png)

<!-- source: gateway-identity-flow.mmd -->
```mermaid
sequenceDiagram
    autonumber
    actor C as Client
    participant E as Envoy
    participant A as url4-cloud App
    participant J as Job spec (env)
    participant R as Runner Pod
    participant G as aigateway
    participant P as Provider

    C->>E: GET /?q=(url4 expression)<br/>+ the caller's own token
    Note over E,A: Cloudflare Access authenticated the caller at the edge.<br/>Envoy RE-VERIFIES that assertion against Cloudflare's JWKS,<br/>strips any client-sent copy, and re-injects X-User-Email.
    E->>A: GET /?q=(url4 expression)<br/>X-User-Email (verified)<br/>+ URL4-Capability, Authorization
    Note over E,A: A nonblank X-Profile is refused with 400 before scheduling.<br/>The normal flow below is selector-less.

    Note over A,J: job_env.identity_from_headers()<br/>blank counts as absent<br/>nothing present → None, and no credential selector is scheduled
    A->>J: schedule(identity=…)<br/>identity_to_env() → URL4_CLOUD_IDENTITY_*<br/>PLAIN env: identity is not a credential

    Note over A,R: THIS is why it is not header forwarding —<br/>the outgoing aigateway request does not exist yet.<br/>The App and the Runner are different Pods.

    J->>R: Pod starts with that env
    Note over R,G: job_env.identity_from_env() →<br/>build_aigateway_world(identity_headers=…)<br/>identity is held for the whole run<br/>no profile selector is reconstructed

    R->>G: POST /v1/chat/completions<br/>X-User-Email, THEN Authorization<br/>(gateway-owned last<br/>no X-Profile)

    Note over G,P: current_account() in cloudflare_headers mode:<br/>identity_from_headers() → CloudflareIdentity →<br/>Account.get_or_create(username=email)<br/>honouring is_active
    G->>G: resolve the effective credential<br/>for (account, provider)
    alt exactly one active Connection
        G->>P: provider call with THAT principal's credential
        P-->>G: completion
        G-->>R: OpenAI-shaped response + usage
        R-->>E: run frames over NATS → WebSocket
        E-->>C: Result / Terminated
    else several active Connections
        G-->>R: 409 connection_ambiguous<br/>remove extra active Connections
        R-->>E: terminal error frame
        E-->>C: Error / Terminated
    end

    Note over G,P: No X-User-Email in this mode → 401.<br/>Never anonymous: one shared principal<br/>would pool every caller's credentials.<br/>Service-token callers are out of scope.
```

**Why the username is the key.** `Account.username` is already unique, so the identity needs no
second derivation and there is no parallel key to keep in step: the lookup is
`Account.get_or_create(username=email)`. `credential_blobs` and `oauth_connections` hang off the
account's id, which is stable for the row's lifetime — so one caller keeps one account and one set of
credentials. The address is lowercased for the key, because letting `A@x.test` and `a@x.test` become
two accounts would split one person's credentials in two.

`get_or_create` is the framework's own primitive and already handles the race that actually happens
here — two concurrent first requests from one caller, the normal case for an SDK with a connection
pool. Tortoise creates inside a transaction and re-fetches on `IntegrityError`.

## 2 · Deployment topology

Trusting `X-User-Email` is only sound while aigateway cannot be reached except by the peers that
carry verified identity. Three things enforce that, and all must hold: no Ingress, a fail-closed
NetworkPolicy, and — in the gateway process itself — `AIGW_ALLOWED_NETWORKS`.

The third exists because the first two are *deployment* configuration, and one of them can be
declined by the cluster (see the precondition note below). `AIGW_ALLOWED_NETWORKS` is a list of CIDR
networks; a request whose TCP peer falls outside every one of them is refused **403 before the
identity header is read**. It is mandatory in this mode: `create_app` raises without it and the
chart fails the render, because "which networks?" has no answer the gateway can safely guess.

The peer is the TCP peer, never `X-Forwarded-For`. Deciding whether to trust one forgeable header by
reading a second, equally forgeable one would be circular — a deployment behind a proxy declares the
proxy's own address instead.

[`gateway-identity-topology.svg`](gateway-identity-topology.svg) · [PNG](gateway-identity-topology.png)

<!-- source: gateway-identity-topology.mmd -->
```mermaid
flowchart TB
    NET([Internet])

    subgraph CL["Kubernetes cluster"]
        subgraph NSA["namespace: url4-cloud"]
            ENVOY["Envoy / Gateway API<br/><b>re-verifies Cloudflare Access,<br/>injects X-User-Email</b><br/>chart: values-cloud.yaml"]
            APP["url4-cloud App<br/>app.kubernetes.io/name: url4-cloud<br/>HTTPRoute target"]
            JOB["Runner Jobs<br/>app.kubernetes.io/name: url4-runner<br/>one Pod per run"]
            AIGW["aigateway<br/>ClusterIP only, port 9105<br/><b>AIGW_AUTH_MODE=cloudflare_headers</b><br/>AIGW_ALLOWED_NETWORKS=Pod CIDR"]
            DB[("Postgres<br/>credential_blobs<br/>AES-256-GCM")]
        end
        OTHER["any other Pod<br/>(other namespace or unlabelled)"]
    end

    PROV(["Provider APIs<br/>Anthropic · Google · OpenRouter"])

    NET -->|"HTTPS + caller token"| ENVOY
    ENVOY -->|"HTTPRoute<br/>+ X-User-Email (verified)"| APP
    APP -->|"schedules, passing identity<br/>as plain Job env"| JOB
    APP -->|"catalog: GET /v1/models<br/>NetworkPolicy: ALLOWED"| AIGW
    JOB -->|"POST /v1/chat/completions<br/>NetworkPolicy: ALLOWED"| AIGW
    OTHER -.->|"NetworkPolicy: DENIED<br/>fail-closed, non-empty from:<br/><b>and 403 if the CNI lets it through</b>"| AIGW
    NET -.->|"NO Ingress<br/>ingress.enabled=false"| AIGW
    AIGW -->|"egress open by design"| PROV
    AIGW --> DB

    classDef edge fill:#1e293b,stroke:#fb923c,stroke-width:2px,color:#e2e8f0
    classDef app fill:#064e3b,stroke:#34d399,stroke-width:2px,color:#e2e8f0
    classDef gw fill:#083344,stroke:#22d3ee,stroke-width:3px,color:#e2e8f0
    classDef denied fill:#3f1d1d,stroke:#f87171,stroke-width:2px,color:#fecaca
    classDef ext fill:#1e293b,stroke:#94a3b8,stroke-width:1px,color:#e2e8f0

    class ENVOY edge
    class APP,JOB app
    class AIGW gw
    class OTHER denied
    class NET,PROV,DB ext

    linkStyle 5,6 stroke:#f87171,stroke-width:2px
```

**The NetworkPolicy detail that matters.** Each allowed client is ONE `from` element carrying both
its `namespaceSelector` and its `podSelector`. Selectors inside an element are ANDed; separate
elements are ORed — so splitting them would mean "any pod in that namespace OR that label anywhere",
i.e. the whole namespace. Two entries are needed because the App and the Runner Jobs share no label.

> **Unverified precondition.** A NetworkPolicy only restricts traffic if the cluster's CNI enforces
> it; some do not, and then the object is decoration. Test it: from a Pod in another namespace,
> `curl -H 'X-User-Email: …' http://<aigw-svc>:9105/v1/chat/completions` must **time out**.
>
> If it answers, the CNI is not enforcing the policy — but the request still gets **403** from
> `AIGW_ALLOWED_NETWORKS` unless that Pod's address is inside a declared network. That is the point
> of the in-process check: it converts a silent cluster-wide impersonation hole into a refusal.
> Narrow `config.allowedNetworks` from the shipped private ranges to your actual Pod CIDR and the
> two guards stop overlapping so generously.

## 3 · Auth modes and the refused configurations

[`gateway-identity-auth-modes.svg`](gateway-identity-auth-modes.svg) · [PNG](gateway-identity-auth-modes.png)

<!-- source: gateway-identity-auth-modes.mmd -->
```mermaid
flowchart TB
    REQ(["Request reaches aigateway"]) --> MODE{"AIGW_AUTH_MODE"}

    MODE -->|cloudflare_headers<br/><b>cloud default</b>| N1{"TCP peer inside<br/>AIGW_ALLOWED_NETWORKS?"}
    N1 -->|no| N403["<b>403</b><br/>checked BEFORE the header is read —<br/>the peer, never X-Forwarded-For<br/>(holds even where the CNI ignores<br/>the NetworkPolicy)"]
    N1 -->|yes| H1{"X-User-Email present?"}
    H1 -->|no| H401["<b>401</b><br/>never anonymous — a shared principal<br/>would pool every caller's credentials<br/>(service tokens land here too)"]
    H1 -->|yes| HACC["CloudflareIdentity →<br/>get_or_create(username=email)<br/>honours is_active"]
    HACC --> OK(["credential lookup for<br/>THAT principal"])

    MODE -->|jwt| J1{"Valid bearer token<br/>for an active Account?"}
    J1 -->|no| J401["<b>401</b>"]
    J1 -->|yes| OK

    MODE -->|disabled<br/><b>local only</b>| D1["anonymous account<br/>+ loopback-only middleware<br/>(client IP AND Host must be loopback)"]
    D1 --> OK

    subgraph REFUSED["Configurations the Helm chart REFUSES to render"]
        R1["authMode=cloudflare_headers<br/>+ ingress.enabled=true<br/><br/>a direct route in means anyone<br/>can set X-User-Email"]
        R2["authEnabled=false<br/>+ authMode≠disabled<br/><br/>two settings disagreeing about<br/>the auth posture"]
        R3["networkPolicy.enabled=true<br/>with no peers declared<br/><br/>an ingress rule with no from:<br/>admits every source"]
        R4["authMode=cloudflare_headers<br/>+ no allowedNetworks<br/><br/>create_app refuses too — a<br/>CrashLoop caught at render time"]
    end

    classDef ok fill:#064e3b,stroke:#34d399,stroke-width:2px,color:#e2e8f0
    classDef bad fill:#3f1d1d,stroke:#f87171,stroke-width:2px,color:#fecaca
    classDef dec fill:#1e293b,stroke:#fb923c,stroke-width:2px,color:#e2e8f0
    classDef local fill:#083344,stroke:#22d3ee,stroke-width:2px,color:#e2e8f0

    class OK,HACC ok
    class H401,J401,N403,R1,R2,R3,R4 bad
    class MODE,H1,J1,N1 dec
    class D1 local
```

`AIGATEWAY_AUTH_ENABLED` is the legacy spelling: `false` still means `disabled`, and the chart
resolves the pair so only `AIGW_AUTH_MODE` reaches the app.

## Local development

Nothing above is required locally. `url4-cloud serve --local` fuses the App and the runner in one
process, and aigateway runs in `disabled` mode (anonymous, loopback-only) — so a plain `curl` works
with no identity at all. To exercise the identity path locally, send the headers yourself; there is
no Envoy to strip them:

```sh
curl -H 'X-User-Email: me@openmined.org' \
     -H 'URL4-Capability: <token>' 'http://127.0.0.1:8000/?q=...'
```

## Credential resolution outcomes

Credential provisioning is separate from identity. Each principal has an isolated credential
namespace. A caller with no usable credential for the requested provider authenticates and then gets
`404 profile_not_found` (the legacy wire code retained until Stage E). If the account/provider pair
has several active Connections, resolution returns `409 connection_ambiguous`; callers cannot choose
one with a request header.
