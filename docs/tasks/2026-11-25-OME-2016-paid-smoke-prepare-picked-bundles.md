---
id: OME-2016
linear_url: https://linear.app/openmined/issue/OME-2016/prepare-only-the-named-benchmarks-datasets-when-the-paid-smoke-names
status: done
type: fix
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1299
created: 2026-11-25
closed: 2026-11-25
---

# Prepare only the named Benchmarks' datasets when the paid smoke names Benchmarks

The paid smoke's `benchmarks` field narrowed what ran, not what was downloaded: the prepare
step prepared all 100 dataset bundles and relied on the asset cache, whose key hashes the
benchmark code, so a branch that edits a Benchmark always missed it (run 45538646440: 25
minutes of downloads to grade 2 Cases of `medxpert`). A press that names Benchmarks now asks
the Engine's preparer which bundles those Benchmarks read (`--list-bundles --for-benchmarks`)
and prepares only those, plus `inspect-gsm8k`, which two other paid tests read on every press.
A named press does not save the asset cache; a press by scope is unchanged.

- 2026-11-25: built in one PR. Owner actions left: merge; one real press with
  `benchmarks: medxpert` to confirm the prepare step lists two bundles.
- Ledger: `docs/work/2026-11-25-paid-smoke-prepare-picked-bundles.md`
