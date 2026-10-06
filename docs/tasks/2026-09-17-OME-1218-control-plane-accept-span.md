---
id: OME-1218
linear_url: https://linear.app/openmined/issue/OME-1218/emit-control-plane-server-spans-so-accept-enqueue-and-queue-wait-are
status: in_review
type: improvement
priority: 2
labels: [screamingface-engine, agentic, design-session]
created: 2026-09-17
closed:
---

# Emit control-plane server spans so accept, enqueue and queue wait are visible

The engine control plane emitted no span: `GET /` forwarded the inbound `traceparent` verbatim,
so accept + enqueue + queue wait were invisible and a run without inbound context had an orphan
`url4.run` root. Owner decision (2026-10-01, option 1): `url4.run` becomes a CHILD of the
control-plane accept span — the control plane forwards its own span id. Consistent with
`OME-1185`. Probe routes emit no span. Other control-plane routes are a later step.

Canonical artifacts:

- Ledger: `docs/work/2026-10-01-OME-1218-control-plane-accept-span.md`
