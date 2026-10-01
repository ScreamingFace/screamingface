---
id: OME-1415
linear_url: https://linear.app/openmined/issue/OME-1415
status: In Progress
type: feature
priority: Medium
labels: [desktop, agentic, autonomous]
created: 2026-09-29
closed:
---

# Un-mock the Studio Models page against the local Engine

Leaf under epic `OME-1308` (E18 · A local app). The Models page reads the local Engine's
`/v1/connections` and `/v1/models`. API keys and OAuth sign-in are real. The starred library is
keyed by real model ids. The PR also refreshes the stale `runtime/uv.lock`.

Spec: ../spec/2026-09-29-studio-models-unmock.md
Plan: ../plan/2026-09-29-studio-models-unmock.md
Parity matrix: ../plan/2026-09-29-OME-1308-studio-library-parity.md
Ledger: ../work/2026-09-29-studio-models-unmock.md
