---
id: OME-1460
linear_url: https://linear.app/openmined/issue/OME-1460/prepare-every-imported-benchmarks-cases-by-calling-the-evals-own-task
status: in_progress
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1273
created: 2026-10-02
closed:
---

# Prepare every Imported Benchmark's Cases by calling the eval's own task function

Fold the Hugging Face preparation path into Task replay: every Imported Benchmark is
prepared by calling the eval's own task function with capture rendering, the recorder
forces the declaration's Hub revision and seeds onto the eval's own fetches, and the 28
Hugging Face-path rows get a new Benchmark Revision under their existing keys. The Hugging
Face reader, registry, writer and lockfile are deleted. Design:
`docs/spec/2026-10-02-ome-1460-one-fetch-path.md`; delivery:
`docs/plan/2026-10-02-OME-1460-one-fetch-path.md` (task 0 refusal sweep, then four stacked
PRs: the enforcer, two fold halves, the deletion). Sequenced after OME-1273's step 7.

## Progress

- 2026-10-02: spec and plan written as a docs-only draft PR; ledger
  `docs/work/2026-10-02-ome-1460-one-fetch-path-spec.md`. The ticket stays in progress; the
  last fold PR closes it.
