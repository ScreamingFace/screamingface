# aigateway-ui Helm chart

The admin console for gateway tenants and their provider API keys. Deploys the container image and
points it at an aigateway release.

## What this is, architecturally

The console is a **Backend-for-Frontend**. The browser never reaches aigateway's `/v1/admin`
surface — the console's Pod does, server-side. Two consequences shape every value below:

1. **In-cluster, the console is an aigateway client like any other.** It needs a route to the
   gateway, and the gateway needs to admit it.
2. **The console trusts `X-User-Email`**, exactly as the gateway does. Whoever can open a
   connection to port 9107 can claim to be any admin.

## Install

The chart needs two things it cannot guess.

```sh
helm install aigw-ui apps/aigateway-ui/charts/aigateway-ui \
  --set aigateway.serviceName=aigw-aigateway \
  --set networkPolicy.clientPodNames[0]=<your mesh gateway's app.kubernetes.io/name>
```

**`aigateway.serviceName`** — the gateway's Service is named `<its release>-aigateway`, and this
chart has no way to learn the other release's name. The default assumes `aigw`, the release name
used throughout this repo. Set `aigateway.baseUrl` instead for a gateway outside the cluster.

**`networkPolicy.clientPodNames`** — who may reach the console. There is no default because only
you know how your mesh gateway is labelled, and rather than render a policy admitting everything,
the chart **fails**. See below.

### The gateway side must also be told

`AIGATEWAY_ADMIN_EMAILS` is empty by default, which means the admin API answers **503 (admin API
disabled)** to everyone and the console shows exactly that. Set it on the *gateway* release:

```sh
helm upgrade aigw apps/aigateway/charts/aigateway \
  --set-string 'config.adminEmails[0]=you@example.com'
```

The gateway's `networkPolicy.clientPodNames` already includes `aigateway-ui` by default. If you
override that list, keep the entry — see below for what its absence looks like.

## Two ways this fails that do not look like what they are

**The console is not in the gateway's `clientPodNames`.** In `cloudflare_headers` mode the
gateway's NetworkPolicy is not hardening — it *is* the authentication boundary. Omitting the
console does not degrade it; the CNI drops the packet. The symptom is a connect timeout in the
console and **nothing at all in the gateway's logs**, because nothing arrived. It reads like the
gateway is down.

**Egress DNS is disabled.** Once a Pod has any egress rule, everything unnamed is denied — cluster
DNS included. The gateway's Service name then fails to resolve and calls fail with `EAI_AGAIN`,
which reads like a wrong `serviceName` rather than a blocked packet. `networkPolicy.egress.dns`
exists for the rare cluster whose DNS is not in `kube-system`; leaving it on is almost always
right.

## `ingress.enabled: true` is refused, not discouraged

The chart ships no Ingress template and fails the render if you ask for one. This is the same
invariant aigateway's `validateAuth` enforces: the console trusts the identity header because the
mesh verifies Cloudflare Access and injects it, stripping any client copy. A direct route to port
9107 removes that guarantee, and

```sh
curl -H 'X-User-Email: <any allowlisted admin>' http://console/
```

is then full admin access — create tenants, attach provider API keys, enumerate every account.
There is no configuration under which a second front door is safe, so there is no flag for it.
Route the console through the same mesh gateway that injects identity.

## Values worth knowing

| Key | Default | Why |
|---|---|---|
| `aigateway.serviceName` | `aigw-aigateway` | The gateway's Service. Assumes release name `aigw`. |
| `aigateway.baseUrl` | `""` | Explicit URL; wins over the parts above. |
| `config.logLevel` | `info` | `LOG_LEVEL` for the BFF's JSON log lines. `error` drops the per-call `warn` refusals. |
| `networkPolicy.clientPodNames` | `[]` | Who may reach the console. **Empty fails the render.** |
| `networkPolicy.egress.gatewayPodName` | `aigateway` | The label the gateway's Pods carry. |
| `ingress.enabled` | `false` | `true` fails the render. See above. |
| `extraEnv` | `[]` | Never put `AIGATEWAY_DEV_USER_EMAIL` here — it is the local-dev identity escape hatch. |

## Egress is narrow, unlike aigateway's

aigateway's egress is `- {}` — unrestricted — because its job is dialling provider APIs whose
address ranges cannot be known by a chart. The console dials one Service and DNS, so that is all
it is allowed. Copying the gateway's rule here would have looked consistent and been wrong.

## Verifying a change

```sh
python3 .github/scripts/verify_chart_wiring.py
```

Renders both charts and asserts on the parsed output, including the cross-chart properties neither
chart can check alone. `helm lint` is **not** sufficient — it reports "0 chart(s) failed" for a
chart that cannot render at all, because it reads templates without executing them.
