---
id: OME-1947
linear_url: https://linear.app/openmined/issue/OME-1947/frozen-copies-are-never-deleted-so-the-production-gateway-database
status: in_review
type: bug
priority: high
labels: [bug, aigateway, agentic]
parent:
created: 2026-11-17
closed:
---

# Frozen copies are never deleted, so the production gateway database grows about 2.7 GB each day

The production AI Gateway database grew from 11.7 GB (2026-10-29) to 47 GB (2026-11-16). Frozen
copies use 40.7 GB of it. No code deletes a frozen copy. 40% of the data was in open copies of
runs that did not end normally; no reader can use them.

- 2026-11-16: read-only audit of production. A manual cleanup deleted 200 of 327 abandoned open
  copies (about 7.4 GB); 127 remain.
- 2026-11-17: filed as a `bug` (Triage, unassigned, Irina + Kevin tagged).
- Spec: `docs/spec/2026-11-16-frozen-copy-retention/` (branch `frozen-copy-retention`).
- 2026-11-17: the owner approved the spec (decisions Q1 to Q25, six review rounds). Plan for stack A:
  `docs/plan/2026-11-17-frozen-copy-retention-stack-a.md`.
- 2026-11-17: the owner approved the plan for stack A and the assertion-only change of one
  existing test (record `.claude/test-change-approvals/OME-1947.json`). Work started; ledger
  `docs/work/2026-11-17-frozen-copy-retention-stack-a.md`.
- 2026-11-17: stack A (A1, A2, A3) is in one pull request:
  https://github.com/ScreamingFace/screamingface/pull/1911 (branch
  `OME-1947-frozen-copy-retention-stack-a`). Stacks B and C come after it; the issue stays open
  until stack C is released.
