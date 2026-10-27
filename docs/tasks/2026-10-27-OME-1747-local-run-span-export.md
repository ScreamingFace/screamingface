---
id: OME-1747
linear_url: https://linear.app/openmined/issue/OME-1747/export-the-span-tree-of-local-in-process-engine-runs
status: in_progress
type: feature
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-27
closed:
---

# OME-1747 — Export the span tree of local in-process engine runs

Unit 6a of epic OME-1636 (e2e notebook workbench): local in-process runs wrap their publisher
in the same `SpanRelay` a Job uses, so the `url4.run` tree is exported when OTLP is configured
and the path stays a pure passthrough when it is not.

Ledger: ../work/2026-10-22-e2e-otel-local-runner.md
