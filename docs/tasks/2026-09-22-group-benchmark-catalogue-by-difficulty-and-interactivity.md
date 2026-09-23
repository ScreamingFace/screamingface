---
id: OME-1257
linear_url: https://linear.app/openmined/issue/OME-1257/group-the-benchmark-catalogue-by-difficulty-and-interactivity
status: in_progress
type: feature
priority: P2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-22
closed:
---

# Group the benchmark catalogue by difficulty and interactivity

Researcher feedback (Purdue on-device-routing call, 2026-09-21) asked for the
benchmark catalogue organized by difficulty and interactivity instead of one flat
list. The `interaction` axis already exists as a declared field on every benchmark;
this ticket adds a hand-assigned `difficulty` tier to the declarations, serves it in
every catalogue row, and makes `sf.benchmarks.list()` group by the two axes — with
the ours/imported provenance grouping (`OME-1114`) still visible.

Acceptance: every registered board declares a difficulty from a closed vocabulary
(registry test fails on missing/unknown); catalogue rows serve `difficulty` beside
`interaction`; the SDK listing presents the two-axis grouping; the vocabulary and
per-board tier assignments appear in the PR description for owner review.

Ledger: `docs/work/2026-09-22-OME-1257-catalogue-difficulty-grouping.md`
