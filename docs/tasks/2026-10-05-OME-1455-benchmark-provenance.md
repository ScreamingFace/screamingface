---
id: OME-1455
linear_url: https://linear.app/openmined/issue/OME-1455/show-where-each-benchmark-comes-from-and-how-much-room-frontier-models
status: in_progress
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-10-02
closed:
---

# Show where each Benchmark comes from and how much room frontier models have left on it

Every Benchmark declares its Benchmark Provenance (paper, authors, citation,
website, harness, dataset, licence with any restriction), its size, a content warning when its
prompts are harmful, a Human Baseline, a Frontier Score and the SDK notebook that runs it. The
Engine derives one Benchmark Saturation verdict from the frontier headroom and every surface
(Leaderboard page, catalogue, SDK list and card) shows the same strip. Delivered as four PRs
(owner, 2026-10-05: backend first, so new Benchmarks carry the fields before any page renders
them): spec + plan + glossary; backend across Engine, Scoreboard and SDK with a strict
conformance test that grandfathers the 65 pre-existing Benchmarks; sourced values for every
Benchmark; the pages, after product signs off the mockup.

- 2026-10-02: ticket filed by the owner before work (In Progress).
- 2026-10-05: PR 1 (spec, plan, glossary) [#1234](https://github.com/ScreamingFace/screamingface/pull/1234) opened from branch
  `OME-1455-benchmark-provenance-spec`, ledger
  `docs/work/2026-10-05-ome-1455-benchmark-provenance-spec.md`.
- 2026-10-05: PR 2 (backend: Engine fields + importer + served verdict, Scoreboard copy, SDK
  discovery) [#1236](https://github.com/ScreamingFace/screamingface/pull/1236) opened from branch `OME-1455-benchmark-provenance-backend`, ledger
  `docs/work/2026-10-05-ome-1455-benchmark-provenance-backend.md`.
- 2026-10-06: product reply on the pages (PR 4): the provenance strip goes in a right-hand sidebar,
  not above the leaderboard, so results stay above the fold; collapsed-by-default is open until
  product sees the mockup; it lands post-launch, after product's own page changes (leaderboard
  copy, a more compact benchmark table). PR 3 (values for all 65, allowlist emptied) started on
  branch `OME-1455-pr3-benchmark-provenance-values`, stacked on PR 2; ledger
  `docs/work/2026-10-06-ome-1455-benchmark-provenance-values.md`; opened as draft
  [#1252](https://github.com/ScreamingFace/screamingface/pull/1252), base = PR 2's branch
  (retarget to main once #1236 merges). Verdicts over the 65: 23 saturated / 30 open / 12 unknown.
