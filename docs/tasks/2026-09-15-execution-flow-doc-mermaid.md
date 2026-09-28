---
id: OME-1205
linear_url: https://linear.app/openmined/issue/OME-1205/make-the-engine-execution-flow-doc-render-as-real-diagrams-and-match
status: done
type: task
priority: 4
labels: [screamingface-engine, agentic, autonomous, task]
created: 2026-09-15
closed: 2026-09-15
---

# Make the engine execution-flow doc render as real diagrams and match the code

Convert `apps/screamingface-engine/docs/execution-flow-diagrams.md` §1/§2 ASCII flows to
mermaid (flowcharts + one sequenceDiagram) and fix the four stale references found in the
2026-09-15 verify pass (memory_stream path, credential-forwarding step, traceparent function
name, two-vs-three modes heading). Docs only; rides the OME-1102 branch/PR.

Ledger: docs/work/2026-09-15-OME-1205-execution-flow-doc-mermaid.md
