---
id: OME-999
linear_url: https://linear.app/openmined/issue/OME-999/running-one-benchmark-no-longer-requires-every-other-benchmarks-assets
status: in_progress
type: null
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-08-26
closed: null
---

# Running one benchmark no longer requires every other benchmark's assets

`prepare gdpval` then `evaluate(benchmark="gdpval-text")` dies on DRACO's missing assets:
world creation installs every registered board, and DRACO's `install()` reads its assets
eagerly — the one violator of the lazy-install invariant HealthBench's docstring documents
and IFEval/HealthBench/GDPval honor.

Fix: lazy providers in DRACO's install + a registry-level regression test pinning the
invariant (full builtin install over an empty assets root succeeds; only a board's own
route resolution requires its assets). Details in the Linear issue.
