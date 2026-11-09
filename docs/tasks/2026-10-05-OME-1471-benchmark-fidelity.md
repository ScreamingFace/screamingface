---
id: OME-1471
linear_url: https://linear.app/openmined/issue/OME-1471/benchmark-fidelity-agent-checking-a-benchmark-against-its-paper-and
status: done
type: feature
priority: medium
labels: [screamingface-engine, agentic]
parent: OME-1299
created: 2026-10-05
closed: 2026-11-09
---

# Benchmark fidelity agent: check a Benchmark against its paper and original code, and say whether our score is comparable

Parent: OME-1299. One PR (owner decision 2026-11-06).

Ledger: `docs/work/2026-11-06-ome-1471-benchmark-fidelity.md`.
Spec: `docs/spec/2026-11-06-OME-1471-benchmark-fidelity.md`.
Plan: `docs/plan/2026-11-06-OME-1471-benchmark-fidelity.md`.

- 2026-10-05: ticket filed by the owner, blocked by OME-1455 (Benchmark Provenance).
- 2026-11-06: OME-1455 Done; `blocked` and `deferred` removed. Spec, plan and the two glossary
  entries (Fidelity Record, Fidelity Verdict) drafted; draft PR [#1700](https://github.com/ScreamingFace/screamingface/pull/1700) opened from branch
  `OME-1471-benchmark-fidelity`. Check script, audit agent and the IFEval record follow on the
  same branch.
- 2026-11-09: owner moved the records' home to `apps/screamingface-engine/docs/benchmarks-fidelity/`
  (spec §1 S6).
- 2026-11-09: check script, agent, Lane 2 line and the IFEval record pushed to the same PR;
  `just engine fidelity-check` → ifeval fresh, 93 no record; blind planted run caught the one
  planted deviation. Ledger done. Pending the owner: review, merge, Linear → Done.
- 2026-11-09: #1700 merged. Follow-up PR [#1708](https://github.com/ScreamingFace/screamingface/pull/1708) from branch `OME-1471-fidelity-agent-fixes` fixes the four
  gaps the ZeroBench and MaCBench dry runs found (verdict precedence, the authors' recorded
  replies, gated datasets, citation prefixes). Ledger `docs/work/2026-11-09-fidelity-agent-fixes.md`.
