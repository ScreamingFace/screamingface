---
id: OME-1599
linear_url: https://linear.app/openmined/issue/OME-1599
status: in_review
type: feature
priority: medium
labels: [url4-engine, design-session, agentic]
parent: OME-1529
created: 2026-10-22
---

# Enforce url4 trust checks on file refs: URL4-Auth-Token, policy registry and identity access

The draft spec `docs/spec/2026-10-22-OME-1599-node-to-node-auth.md` covers url4 node-to-node
authentication for remote blobs (C2) and remote-node calls (C6). It is waiting on Kevin's sign-off on
Q1–Q6 (§10) and Ionésio's review of §5.5 (`url4/peer`). Until it is approved, spec #1450 F1/F1b stand:
remote blobs and remote-node calls are refused before any I/O. Implementation follows sign-off: C6 on
`main`, and C2 after #1482.

Ledger: `docs/work/2026-10-22-node-auth-spec.md`.
