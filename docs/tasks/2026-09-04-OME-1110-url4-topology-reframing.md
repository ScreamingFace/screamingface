---
id: OME-1110
linear_url: https://linear.app/openmined/issue/OME-1110/reframe-url4-topology-node-host-discovery-addressing-transport-spec
status: in_review
type: task
priority: P2
labels: [url4-sdk, design-session, agentic, task]
created: 2026-09-04
closed:
---

# Reframe url4 topology: node, host, discovery, addressing, transport (spec + PDF)

Short plain-English PDF with diagrams defining Node, Host, mounts, addressing (`/name` vs
`url4://name`), discovery (`.well-known` vs OPTIONS, pros/cons), delivery modes and fallback
(SSE per node, sync floor), telemetry (envelope / SSE / OTLP), and the Engine's mapping to a
url4 Host. Appendix A: proposed spec deltas for Kevin (Parts C/G, §1.4 rename, §33, §34).
Appendix B: follow-up work items. Doctrine skill synced (F4 closed).

Deferred by owner decision: plan/preflight, swarm as a protocol noun, node grades.
Ledger: `docs/work/2026-09-04-OME-1110-url4-topology-reframing.md`.
