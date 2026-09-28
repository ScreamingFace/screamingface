---
id: OME-1112
linear_url: https://linear.app/openmined/issue/OME-1112/benchmark-catalogue-records-where-each-benchmark-came-from
status: done
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-04
closed: 2026-09-16
---

# Benchmark catalogue records where each benchmark came from

Add `origin: "screamingface" | "inspect_evals"` to the Engine's benchmark
registration record, emitted for every board by `GET /v1/benchmarks`. Existing
boards default to `screamingface`; the import lane (parent epic OME-1111)
declares `inspect_evals` at registration. Blocks OME-1114 (grouped listing).

Ledger: `docs/work/2026-09-15-OME-1112-benchmark-origin.md`
