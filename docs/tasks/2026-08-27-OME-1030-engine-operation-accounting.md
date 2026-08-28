---
id: OME-1030
linear_url: https://linear.app/openmined/issue/OME-1030/retain-per-operation-evaluation-accounting-in-candidate-results
status: in_review
type: task
priority: P2
labels: [screamingface-engine, autonomous, agentic]
created: 2026-08-27
closed:
---

# Retain per-operation evaluation accounting in Candidate results

Engine implementation child of OME-901. Deepen the existing connector-owned call facts, retain
Candidate outputs in their existing local scope, retain only request identity/accounting in the
run-level grading scope, and attach one shared exact-only accounting value to Candidate
`CaseOperation` and grading `Evidence`.

No `packages/url4` or AI Gateway source change. Generic `Url4Executor` remains unchanged and
benchmark-agnostic. Candidate/root usage remains authoritative; ambiguous values remain null.
CorrectiveLoop's nested Recipe calls remain outside exact per-operation projection in this unit:
its outer total stays authoritative and the nested subtotal remains explicitly unattributed.
No new timer, attempt counter, complete Candidate fingerprint, or failed-path interception ships.
Provider refusals retain terminal accounting before propagation; retry identity is retained only
when every contributing attempt agrees; malformed accounting remains fail-open and never changes a
successful model result.

Implementation was explicitly approved, is complete, and is under review against
`docs/plan/2026-08-27-OME-901-operation-accounting.md`.

Spec: `docs/spec/2026-08-27-OME-901-operation-accounting.md`.
Parent: OME-901.
