---
id: OME-1568
linear_url: https://linear.app/openmined/issue/OME-1568/read-url4-node-state-through-public-url4-apis-only
status: In Progress
type: Task
priority: P2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-09
closed:
---

# OME-1568 — Read url4 node state through public url4 APIs only

Parent: OME-1289 (E4a). Sibling: OME-1567 (url4).

The Engine reads `eval_path`, holdings collections and data routes through public url4 APIs, and two
guard tests forbid private `url4.peer` imports and private url4 node attribute reads. No behavior
change.

Plan: ../plan/2026-10-09-url4-rds-code-pointer.md ("Second follow-up round" V1, "Third round" W1)
Ledger: ../work/2026-10-09-url4-rds-code-pointer.md
