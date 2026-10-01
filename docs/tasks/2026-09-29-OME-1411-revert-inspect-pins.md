---
id: OME-1411
linear_url: https://linear.app/openmined/issue/OME-1411/put-the-imported-benchmarks-back-on-the-inspect-versions-their-exams
status: done
type: fix
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-733
created: 2026-09-29
closed: 2026-09-29
---

# Put the imported benchmarks back on the inspect versions their exams were built with

Dependabot's #1026 bumped inspect-ai 0.3.263 → 0.3.266 and inspect-evals 0.20.0 → 0.21.0.
Imported boards hash both versions into their revision, so all 18 published exams moved on
main. The inspect CI lane reported the failures but stayed green, because `pytest | tee` has no
`pipefail`. This reverts only the two pins and holds both packages in Dependabot until
OME-1410 (bump verification) lands.

- 2026-09-29: filed with the revert PR (branch `OME-1411-revert-inspect-pins`, ledger
  `docs/work/2026-09-29-revert-inspect-pins.md`). `tests/unit/inspect` 496 passed; the 18
  published revisions are byte-identical again.
