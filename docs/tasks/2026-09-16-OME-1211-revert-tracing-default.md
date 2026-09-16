---
id: OME-1211
linear_url: https://linear.app/openmined/issue/OME-1211
status: in_review
type: null
priority: 1
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-16
closed: null
---

# Revert the engine tracing default — it was timing out on every deployed run

`OME-1190` (#921) defaulted `tracing.enabled: true` with a hardcoded in-cluster collector
address. It reached `sf-fusion` and degraded every run:

```
otlp span export enabled service=screamingface-engine
Failed to export span batch due to timeout, max retries or shutdown.
```

Two things worth knowing before touching this area again:

- **In-cluster Service DNS does NOT imply reachability.** The dev namespace's network boundary
  permits only DNS, its own services, and the public internet on 443 — the collector is inside
  the cluster and every export packet is dropped. Staging has no collector at all. Enabling
  tracing means opening the network path **and** setting the values; those are one job, and the
  platform team owns it.

- **This failure is silent by design, which is what made it costly.** The sink swallows exporter
  errors (a collector outage must never fail a run) and flushes on shutdown (so a trace keeps
  its ending). Both are right individually. Together, against an unreachable endpoint, they
  produce a per-run timeout that nothing announces.

`bitsofsteve` predicted all of this in the #921 review and asked for the PR to be closed. It was
merged an hour later anyway — see `OME-1212` for the convention change that should prevent a
repeat.

Ledger: `docs/work/2026-09-16-OME-1211-revert-tracing-default.md`
