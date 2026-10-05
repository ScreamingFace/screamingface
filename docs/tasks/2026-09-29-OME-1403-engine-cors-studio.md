---
id: OME-1403
linear_url: https://linear.app/openmined/issue/OME-1403
status: In Progress
type: feature
priority: Medium
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-29
closed:
---

# Engine: grant CORS to the Studio frontend's origins

Leaf under epic `OME-1308` (E18 · A local app). The Engine grants CORS to Studio's origins only
(`http://localhost:3000`, `tauri://localhost`, `http://tauri.localhost`, `https://tauri.localhost`),
overridable by `URL4_CLOUD_CORS_ALLOWED_ORIGINS`; credentials off.

Spec: ../spec/2026-09-29-engine-cors-studio.md
Plan: ../plan/2026-09-29-engine-cors-studio.md
Ledger: ../work/2026-09-29-engine-cors-studio.md
