---
id: OME-1870
linear_url: https://linear.app/openmined/issue/OME-1870/autoscale-the-engine-runner-pool-on-claimable-queue-demand
status: in_progress
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1314
created: 2026-11-10
closed:
---

# Autoscale the engine runner pool on claimable queue demand

The runner pool was a fixed Deployment. When every slot was busy, a new user's runs waited in the
queue and nothing added capacity. The App now samples each bucket consumer and serves claimable
demand on `GET /runner-demand`; an opt-in KEDA ScaledObject scales the pool on it.

- 2026-11-10: filed under epic `OME-1314` (E23) at PR-open. Follow-up `OME-1871` (remove idle pods
  first on scale-down).
- Spec: `docs/spec/2026-11-10-runner-pool-autoscaling.md`
- Ledger: `docs/work/2026-11-10-runner-pool-autoscaling.md`
