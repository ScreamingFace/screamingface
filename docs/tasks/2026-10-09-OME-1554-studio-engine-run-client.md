---
id: OME-1554
linear_url: https://linear.app/openmined/issue/OME-1554
status: In Progress
type: feature
priority: Medium
labels: [desktop, agentic, autonomous]
created: 2026-10-09
closed:
---

# Studio Engine run client, and recipes written the way the SDK writes them

Leaf under epic `OME-1308` (E18 · A local app); slice B of Compose Fusion end to end, stacked on
`OME-1553`. Adds `lib/engine/run.ts`, the TypeScript client for the Engine's token, WebSocket and run
protocol, which links the candidate exactly as the SDK does. Also fixes params (`&q=`), `?recipe=`
import, and prompt text encoding (U+2028 newlines, `$$`). Not wired into the UI until slice C.

Spec: ../spec/2026-10-01-studio-compose-fusion-run.md
Plan: ../plan/2026-10-09-studio-compose-fusion-run.md
Ledger: ../work/2026-10-09-studio-engine-run-client.md
