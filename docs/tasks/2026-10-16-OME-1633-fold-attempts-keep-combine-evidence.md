---
id: OME-1633
linear_url: https://linear.app/openmined/issue/OME-1633/judge-fusions-fail-every-case-on-a-benchmark-that-asks-each-question
status: done
type: bug
priority: 2
labels: [bug, screamingface-engine, agentic, autonomous]
created: 2026-10-16
closed: 2026-10-16
---

# OME-1633 — Judge Fusions fail every Case on a Benchmark that asks each question twice

The Attempts merge re-checked the merged Case from a field-name dump, so a judge Fusion's
combine evidence came back as `schema_id`, which it refuses. Every judged Case with two or
more Attempts failed as `benchmark_unavailable` (ARC-AGI-2 smoke run, 2026-10-15: 4 of 6 judge
twins). Fix: the merge dumps by wire name.

Ledger: ../work/2026-10-16-fold-attempts-keep-combine-evidence.md
