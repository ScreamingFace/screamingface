---
id: OME-1500
linear_url: https://linear.app/openmined/issue/OME-1500/run-the-paid-smoke-over-every-benchmark-and-let-the-owner-pick-which
status: done
type: feature
priority: medium
labels: [client-sf, agentic, autonomous]
created: 2026-10-06
closed: 2026-10-06
---

# Run the paid smoke over every Benchmark, and let the owner pick which kind

The owner-pressed paid smoke ran only the Imported Benchmarks. It now runs every Benchmark the
live Engine lists, the 8 hand-built ones included, narrowed by a `scope` choice on the button
(`all` · `imported` · `hand-built`). A scope typo or a picked kind with nothing listed fails
before any spend. Renamed to "ScreamingFace Paid Benchmark Smoke"; timeout 180 minutes.

Ledger: `docs/work/2026-10-06-paid-benchmark-smoke.md`.
Spec: `docs/spec/2026-10-06-paid-benchmark-smoke.md`. Plan: `docs/plan/2026-10-06-paid-benchmark-smoke.md`.

- 2026-10-06: filed and PR opened; the first `scope=all` press is the owner's (ledger Owner-verify).
