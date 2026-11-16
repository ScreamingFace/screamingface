---
id: OME-1931
linear_url: https://linear.app/openmined/issue/OME-1931/runner-scale-down-removes-busy-pods-the-worker-should-publish-its-busy
status: in_review
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1314
created: 2026-11-16
closed:
---

# Runner scale-down removes busy pods: the worker publishes its busy slots as pod-deletion-cost

On a scale-down, Kubernetes can remove a busy runner pod and keep an idle one. The busy pod then
drains for up to 16 h and holds its node. The worker now writes its busy slot count to the
`controller.kubernetes.io/pod-deletion-cost` annotation of its own pod, so idle pods go first. The
chart gives the runner its own ServiceAccount (`<fullname>-runner`), a mounted token and its pod
identity, behind `runnerPool.deletionCost.enabled` (default off).

- 2026-11-16: filed by platform under epic `OME-1314` (E23). It replaces `OME-1871`, which is closed
  as a duplicate.
- 2026-11-16: PR #1856 opened; kind walkthrough passed; answers posted on the ticket.
- Spec: `docs/spec/2026-11-16-runner-pod-deletion-cost.md`
- Plan: `docs/plan/2026-11-16-runner-pod-deletion-cost.md`
- Ledger: `docs/work/2026-11-16-runner-pod-deletion-cost.md`
