---
id: OME-1905
linear_url: https://linear.app/openmined/issue/OME-1905/keep-the-decision-operations-and-charges-of-a-failed-case
status: backlog
type: feature
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-11-12
closed:
---

# Keep the decision, operations and charges of a failed Case

Mirror of OME-1905 (parent epic OME-1291, E4c). A follow-up of the PR #1733 review (HupBaHa H4) and E4c deviation 4; not part of #1733.

A failed Case (member failure, `fail_closed`, `signal_missing`, `quorum_not_met`) keeps only its failure code: no Gate decision, no operations, no charges. Scope: the Candidate invocation keeps the records made before the failure; the SDK decoder, the report and a frozen-copy replay show them.

Ledger: `docs/work/2026-10-22-e4c-routers-cascades.md` (deviation 4; 2026-11-12 review round).
