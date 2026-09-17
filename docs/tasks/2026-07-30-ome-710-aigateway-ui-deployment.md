---
id: OME-710
linear_url: https://linear.app/openmined/issue/OME-710/ship-aigateway-ui-container-image-helm-chart-wired-to-aigateway-in
status: in_progress
type: task
priority: P2
labels: [aigateway/deployment, autonomous, agentic]
created: 2026-07-30
closed:
---

# OME-710 — Ship `aigateway-ui`: container image + Helm chart wired to aigateway in-cluster

`OME-708`/`OME-709` built the admin console. It runs locally and deploys nowhere. This makes it
deployable and connects it to the gateway inside the cluster.

> **Landing label.** Filed under `app › aigateway/deployment` rather than the still-missing
> `app › aigateway-ui`. Both ends of this change are deployment wiring for one connection, so the
> deployment leaf is the honest fit — not a workaround for the missing label. That label is still
> owed for `OME-708`/`OME-709`.

## The connection has two ends, and the far end already says no

`charts/aigateway/values.yaml` defaults `networkPolicy.clientPodNames` to
`[url4-cloud, url4-runner]`, and the policy template **fails the render** rather than emit a rule
with no `from:`. In `cloudflare_headers` mode that policy is not hardening — it *is* the
authentication boundary. The console is a BFF, so it is the console's **Pod** that connects, and a
console not named there is denied at the CNI: a connect timeout with nothing in the gateway's logs,
because the packet never arrives.

Second end: `AIGATEWAY_ADMIN_EMAILS` had no chart path at all. The ConfigMap emits a fixed key set,
so `OME-706`'s admin API would answer `503 admin API disabled` forever regardless of values.

## Changes

**aigateway** — `config.adminEmails` → `AIGATEWAY_ADMIN_EMAILS` in the ConfigMap; `aigateway-ui`
added to `networkPolicy.clientPodNames` in both `values.yaml` and `values-prod.yaml`; README.

**aigateway-ui** — `Dockerfile` (multi-stage, node 22 slim, runs as the base image's `node` user at
UID 1000) + `.dockerignore`; `charts/aigateway-ui/` with Deployment, Service, ConfigMap,
ServiceAccount and NetworkPolicy; README.

**CI** — `.github/workflows/charts.yml` plus `.github/scripts/verify_chart_wiring.py`. The
aigateway chart was previously linted only inside `release-aigateway.yml`, so a chart change in a
PR had no gate at all.

## Invariants

- `ingress.enabled: true` **fails the render**. The console trusts `X-User-Email`, so a direct
  route to port 9107 is full admin impersonation with one `curl -H`. No flag makes that safe, so
  there is no flag — and the chart ships no Ingress template.
- Egress is narrow, deliberately unlike aigateway's `- {}`. The gateway's egress is open because it
  dials provider APIs whose ranges cannot be known; the console dials one Service and DNS.
- DNS is named explicitly. Once a Pod has any egress rule everything unnamed is denied, DNS
  included, and the failure is `EAI_AGAIN` — which reads like a wrong Service name.

## Acceptance

`helm lint` + `helm template` clean for both charts; `verify_chart_wiring.py` green, including the
cross-chart assertions; the image builds and serves `/healthz`, `theme-init.js` and a hashed
`.next/static` asset as a non-root user; `run_gates.py aigateway` and `aigateway-ui` still green.

## Not in scope

`release-aigateway-ui.yml` — the lane that publishes the image and chart on an `aigateway-ui-v*`
tag. This issue produces the artefacts that lane would consume.
