---
id: OME-1904
linear_url: https://linear.app/openmined/issue/OME-1904/decide-how-a-duplicate-call-in-a-budgeted-url4-is-charged
status: backlog
type: decision
priority: 3
labels: [screamingface-engine, agentic, design-session]
created: 2026-11-12
closed:
---

# Decide how a duplicate call in a budgeted url4 is charged

Mirror of OME-1904 (parent epic OME-1291, E4c). A follow-up of the PR #1733 review (HupBaHa H3); not part of #1733.

A hand-written url4 can hold the same call two times (same fingerprint, no unique `binding=`). The Engine cannot tell which copy made which charge, so it drops both charges (erd one-claimant rule). The SDK always adds a unique `binding=`, so no SDK recipe has a duplicate.

Options: the first copy takes the charge; Case-level unassigned charges (wire change); or refuse a duplicate fingerprint in a budgeted url4 before any call.

Ledger: `docs/work/2026-10-22-e4c-routers-cascades.md` (2026-11-12 review round).
