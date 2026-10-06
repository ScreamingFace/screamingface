---
id: OME-1495
linear_url: https://linear.app/openmined/issue/OME-1495/engine-app-deployment-has-no-otlp-env-so-the-url4accept-span-never
status: done
type: bug
priority: 2
labels: [bug, screamingface-engine, agentic, autonomous]
created: 2026-10-06
closed: 2026-10-06
---

# Engine App Deployment has no OTLP env, so the url4.accept span never exports

Bug (no parent epic; Triage, unassigned; Irina + Kevin tagged). Related: Phase 2 epic `OME-1129`,
original `OME-1218` (PR #1216). The chart rendered the `OTEL_*` keys and tracing Secret for the
runner pool only, so the App's `load_span_sink(os.environ)` returned None on dev: no `url4.accept`
span, and `url4.run` adopted the caller's never-exported span as its parent. Fix: one
`tracingEnv` helper rendered into both ConfigMaps + the tracing `secretRef` on the App under
`tracingHasSecret`. Live SigNoz verification is post-deploy.

Canonical artifacts:

- Ledger: `docs/work/2026-10-06-engine-app-otlp-env.md`
