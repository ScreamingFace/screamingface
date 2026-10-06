---
id: OME-1460
linear_url: https://linear.app/openmined/issue/OME-1460/prepare-every-imported-benchmarks-cases-by-calling-the-evals-own-task
status: done
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1273
created: 2026-10-02
closed: 2026-10-06
---

# Prepare every Imported Benchmark's Cases by calling the eval's own task function

Fold the Hugging Face preparation path into Task replay: every Imported Benchmark is
prepared by calling the eval's own task function with capture rendering, the recorder
forces the declaration's Hub revision and seeds onto the eval's own fetches, and the 30
Hugging Face-path rows get a new Benchmark Revision under their existing keys. The Hugging
Face reader, registry, writer and lockfile are deleted. Design:
`docs/spec/2026-10-02-ome-1460-one-fetch-path.md`; delivery:
`docs/plan/2026-10-02-OME-1460-one-fetch-path.md` (task 0 refusal sweep, then two PRs:
the enforcer; the fold and the deletion). Sequenced after OME-1273's step 7.

## Progress

- 2026-10-02: spec and plan written as a docs-only draft PR; ledger
  `docs/work/2026-10-02-ome-1460-one-fetch-path-spec.md`. The ticket stays in progress; the
  last fold PR closes it.
- 2026-10-05: spec #1223 merged (two PRs, D5). PR 1 of 2, #1237: the fetch-pin enforcer (a Task
  replay forces the declaration's Hub commits and seeds), the declaration's new fields, the gated
  skip, and five Task-replay rows pinned (medqa, bbq, piqa, pre_flight, bbeh); the Task 0 sweep
  ran all 30 Hugging Face-path rows under Task replay (ledger
  `docs/work/2026-10-05-one-fetch-path-enforcer.md`).
- 2026-10-06: PR 2 of 2: the 30 rows re-imported by Task replay under their keys (30 new
  Benchmark Revisions, the owner's licence decisions on the rows), the Hugging Face reader,
  registry, writer and pins.py deleted, the importer reduced to one path, docs and glossary
  updated (ledger `docs/work/2026-10-06-one-fetch-path-fold.md`). Closes the ticket.
