---
id: OME-1064
linear_url: https://linear.app/openmined/issue/OME-1064/make-runner-job-capacity-explicit-and-enforced-end-to-end
status: in_progress
type: epic
priority: 2
labels: [screamingface-engine, py-screamingface, agentic, autonomous]
created: 2026-09-01
closed:
---

# Make Runner Job capacity explicit and enforced end to end

Cross-cutting epic from the 2026-09-01 `draco-3pass` incident: a 9-candidate evaluation
froze for 23 minutes with no error, then failed every candidate, because Runner Job Pods
were never created.

Root cause is five capacity ceilings that do not know about each other — the SDK picks the
fan-out (`_MAX_CANDIDATES_IN_FLIGHT = 8`), the Engine's K8s path has no admission control at
all, and the `sf-fusion` `requests.cpu: 2` quota fits exactly 8 runners. One evaluation
saturates the namespace; anything concurrent is refused, silently.

Children: `OME-1059` (detection), `OME-1067` (blast radius), `OME-1065` (admission),
`OME-1066` (client backpressure), `OME-1058` (infra capacity). Related: `OME-908` (fairness,
blocked on `OME-1065`).

Spec: `docs/spec/2026-09-01-OME-1064-runner-capacity-admission.md`.
Plan: `docs/plan/2026-09-01-OME-1064-runner-capacity-admission.md`.
Ledger: `docs/work/2026-09-01-OME-1064-runner-capacity-design.md`.
