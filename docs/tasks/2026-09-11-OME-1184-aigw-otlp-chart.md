---
id: OME-1184
linear_url: https://linear.app/openmined/issue/OME-1184
status: in_review
type: null
priority: 3
labels: [aigateway, agentic, autonomous]
created: 2026-09-11
closed: null
---

# Ship the OTLP endpoint to aigateway through its chart

`OME-1132` made aigateway emit spans and left it inert — nothing set
`OTEL_EXPORTER_OTLP_ENDPOINT` and the chart had no way to. This is the half that turns it on,
mirroring `OME-1131`'s engine shape deliberately.

Four things worth knowing before touching this area:

- **The collector is in-cluster and needs NO credential.** `signoz-otel-collector` in namespace
  `signoz` (cluster `aks-dev`), OTLP/HTTP on `:4318` — the port read from the collector's own
  startup log, not assumed. So `tracing.headers` stays empty and no Secret renders by default.

- **⚠️ Never point `tracing.endpoint` at the SigNoz UI hostname.**
  `https://signoz.pulse.dev.openmined.org/v1/traces` answers **200 with `text/html`** (the UI's
  SPA catch-all; a nonsense path answers identically). OTel's exporter treats any 2xx as
  success, so that hostname discards every span while reporting perfect health.

- **This chart has NO `values.schema.json`**, unlike the engine's. The template `fail` on
  `enabled && !endpoint` is therefore the ONLY guard rather than a backstop behind a schema
  rule — which is why it has a dedicated test.

- **`tracing.headers` is OPTIONAL**, unlike every other credential here, and the pod references
  the Secret only when one exists. An `envFrom` naming a Secret that is never created stops the
  pod from starting.

Two traps recorded so they are not re-introduced:

- **Do not add `lookup` reuse to `secret-tracing.yaml`.** `OME-1131` wrote it (copying
  `secret-tavily.yaml`) and removed it as a bug — this template renders only when headers are
  supplied, so the reuse branch silently reverts a credential rotation to the stale cluster
  copy. It cannot be fixed by moving the condition: "absent" is a legitimate configuration.

- **`azure/setup-helm@v5` in `aigateway-tests.yml`'s `test` job is load-bearing.** Without it
  these chart tests `skipif` and pass while asserting nothing. That is exactly what happened to
  the engine's equivalents (`OME-1189`). If you ever see them reported as skipped in CI, that
  is a broken gate, not a tolerable environment difference.

**Deployment is ArgoCD**, not GitHub Actions. `screamingface-sf-aigw` (dev) tracks this repo's
chart with values from `$values/kubernetes/apps/sf-aigw/values/dev.yaml` in
`OpenMined/infrastructure`. Turning tracing on is four lines there:

```yaml
tracing:
  enabled: true
  endpoint: http://signoz-otel-collector.signoz.svc.cluster.local:4318
  serviceName: aigateway
  resourceAttributes: deployment.environment=dev
```

Preview environments carry INLINE values in their ArgoCD Application rather than a values file,
so they are untouched and stay off — whether previews should trace at all is an owner call.

Ledger: `docs/work/2026-09-11-OME-1184-aigw-otlp-chart.md`
