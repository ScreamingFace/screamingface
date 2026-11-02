---
id: OME-1778
linear_url: https://linear.app/openmined/issue/OME-1778/fold-connection-backed-pairs-into-the-provider-availability-listing
status: in_review
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-29
---

# Fold Connection-backed pairs into the provider availability listing (D17)

`GET /v1/provider-access` now answers by the rule chat resolves by. A pair its marker's effective
reference does not serve lists through its Connections: one active row gives that row's operational
status, two or more give `error`, none active gives `pending`, else `error`, else `not_connected`.
A provider connected natively after the E4 census lists `connected`, as chat serves it. No runtime
flag. Spec `docs/spec/2026-10-29-availability-fold-in.md`, plan
`docs/plan/2026-10-29-availability-fold-in.md`.

- 2026-10-29: filed, implemented, PR opened.
