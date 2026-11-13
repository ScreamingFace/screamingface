---
id: OME-1912
linear_url: https://linear.app/openmined/issue/OME-1912
status: in_progress
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1314
created: 2026-11-13
closed:
---

# Make runner autoscaling scale up on KEDA 2.17 and add a scale-up-only mode

The AKS KEDA add-on (2.17.2) drops `scaleUp.tolerance`, so the HPA keeps its 10 % band and the pool stalls. New chart value `runnerPool.autoscaling.targetPerPod` (3.6 for 4 slots on KEDA 2.17) makes the HPA always scale up. New `scaleDown.enabled: false` gives a scale-up-only pool until OME-1871.

- 2026-11-13: filed under epic `OME-1314` (E23) at PR-open. Source: platform follow-up on #1738 (https://github.com/ScreamingFace/screamingface/pull/1738#issuecomment-6830194905).
- Spec: `docs/spec/2026-11-10-runner-pool-autoscaling.md` (D8)
- Ledger: `docs/work/2026-11-13-keda-217-runner-target.md`
