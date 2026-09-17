---
id: OME-869
linear_url: https://linear.app/openmined/issue/OME-869/carry-cache-and-reasoning-token-classes-into-the-run-totals
status: In Progress
type: Feature
priority: P1
labels: [url4-cloud, agentic, autonomous]
created: 2026-08-17
closed:
---

# Carry cache and reasoning token classes into the run totals

Part of the OME-849 cost epic, found in peer review of PR #620. Spans carry all five token
classes; the run subtree carries only input and output, so cache-read, cache-creation and
reasoning reach the wire as zero. Spec: `docs/spec/2026-08-17-OME-849-run-cost-openrouter.md`.
