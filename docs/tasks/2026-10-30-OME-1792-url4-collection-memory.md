---
id: OME-1792
linear_url: https://linear.app/openmined/issue/OME-1792/url4-parse-large-collections-once-and-release-finished-node-results
status: in_review
type: feature
priority: high
labels: [url4-sdk, agentic, autonomous]
created: 2026-10-30
closed:
---

# url4: parse large collections once and release finished node results

Iterating a large collection (e.g. a 330 MB imported-board `cases.json`) used to peak at about 4× the body:
two full parses, line/strip copies, and every row re-serialised. On top of that, the executor held every finished
result for the whole run. Now there is one parse, no full copies, only the iterated window is serialised
(`parse_collection(window=)`), and `RunMemo` drops a result after its last consumer. Measured extra peak: 4.01× → 1.00×.

Parent epic `OME-1314`. Ledger: `../work/2026-10-30-url4-collection-memory.md`.
