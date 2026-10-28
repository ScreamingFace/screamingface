---
id: OME-1757
linear_url: https://linear.app/openmined/issue/OME-1757/warn-when-an-imported-dataset-bundles-sources-under-other-licences
status: done
type: feature
priority: low
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-10-28
closed: 2026-10-28
---

# Warn when an imported dataset bundles sources under other licences

The importer proposes a Benchmark's licence line from the one Hugging Face dataset card. When the
dataset looks like a bundle of other datasets, it now warns: "aggregate dataset — check each
source's licence by hand before writing the licence line". Two shapes trigger it, both read from
what the importer already has: 3 or more configs of one Hub repo (MMMU: 30 subject configs), or a
per-row `source` column on the card (MathVista: cc-by-sa-4.0 on the card, 31 source datasets in
the rows). The warning lands in the generated licence note and on stderr. It never blocks, the
proposed licence value is decided as before, and no existing row changes.

Ledger: `docs/work/2026-10-28-warn-on-bundled-dataset-licences.md`.
