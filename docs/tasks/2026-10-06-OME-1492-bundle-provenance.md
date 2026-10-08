---
id: OME-1492
linear_url: https://linear.app/openmined/issue/OME-1492/show-what-each-benchmarks-build-fetched-and-which-cases-moved-when-its
status: done
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-06
closed: 2026-10-07
---

# Show what each Benchmark's build fetched, and which Cases moved when its seal fails

Three PRs (owner call 2026-10-06):

1. The provenance block for the Imported Benchmarks: `provenance.json` in each bundle, the
   summary line, and the paid smoke's "Where the Cases came from" table.
2. An order-blind Case Set Digest sealed at import beside the Case Digest, so a broken seal
   says "same Cases in another order" or "text changed" (owner call 2026-10-07: no per-Case
   list).
3. A provenance block from each of the six hand-built preparers, and the Benchmark-to-bundle
   mapping the overview needs for shared bundles.

Ledger (PR 1): `docs/work/2026-10-06-bundle-provenance.md`.
Spec (PR 1): `docs/spec/2026-10-06-OME-1492-bundle-provenance.md`.

- 2026-10-06: PR 1 implemented; gates green on both stacks.
- 2026-10-07: PR 2 implemented (order-blind `case_set_digest` on every declaration, 57/57 backfilled); gates green.
- 2026-10-07: PR 3 implemented (ledger `docs/work/2026-10-07-hand-built-provenance.md`, spec `docs/spec/2026-10-07-OME-1492-pr3-hand-built-provenance.md`): the six hand-built preparers write the block; the run page maps the four shared-bundle Benchmarks.
- 2026-10-07: review fixes for #1268 and #1284 ride #1285, because both merged before the fixes were pushed: a used bundle folder is refused before its label is touched, a NaN time renders as unreadable, a repeated Case is pinned in the order-blind seal, and the glossary gains Bundle Provenance and Case Set Digest. Closed with #1285.
