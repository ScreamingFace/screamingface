---
id: OME-1231
linear_url: https://linear.app/openmined/issue/OME-1231/a-seeded-run-fails-instead-of-saying-the-model-cannot-take-a-seed
status: closed
type: task
priority: P2
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-18
closed: 2026-09-19
---

# A seeded run fails instead of saying the model cannot take a seed

A seeded fusion containing a model whose provider cannot accept `seed` dies mid-run with
`provider_error` after billing the members that worked. The catalogue already carries the
verdict — that model's `seed` is `provider_support: "unsupported"`.

The parameter preflight that should catch it already exists and already covers both the ambient
run seed and a Candidate's declared `params`, but it reads the gateway's POLICY
(`gateway_status`) and never the provider's EVIDENCE (`provider_support`) sitting on the same
object. This unit makes it read the evidence and refuse before any spend.

Direction changed from the ticket's original drop-and-continue to refuse-pre-spend, SDK-only,
on owner approval — see the verification comment on the issue. Drop-and-continue needs per-model
wire granularity plus an Engine change and stays open as a possible cross-cutting epic.

Labels: landing moved `screamingface-engine` → `py-screamingface`; the fix is entirely in the
Client SDK.

Ledger: `docs/work/2026-09-18-OME-1231-unsupported-provider-parameter.md`
