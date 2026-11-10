---
id: OME-1858
linear_url: https://linear.app/openmined/issue/OME-1858/audit-every-catalogue-benchmark-against-its-paper-and-original-code
status: done
type: task
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-11-09
closed: 2026-11-09
---

# Audit every catalogue Benchmark against its paper and original code, and record a Fidelity Verdict for each

Parent: OME-1299. Follows OME-1471, which shipped the record format, the check script, the
audit agent and the IFEval record.

Ledger: `docs/work/2026-11-09-fidelity-sweep.md`.

- 2026-11-09: 93 records written by the `sf-benchmark-fidelity` agent in the owner's order
  (board nine → Leaderboard-scored → the rest), each citation opened by the calling session
  before copy-in; `just engine fidelity-check` → 94 fresh, 0 stale, 0 no record, 0 orphan.
  Three stacked PRs, one per slice: `OME-1858-pr1-fidelity-sweep-sota-board` (19) →
  `OME-1858-pr2-fidelity-sweep-leaderboard-scored` (36) → `OME-1858-pr3-fidelity-sweep-remaining`
  (38 + ledger + this mirror). Verdicts: 2 comparable-to-paper, 23 comparable-to-inspect,
  30 not-comparable, 39 unverified. Owner decisions the records surfaced are listed on the
  ticket and in the ledger; none was changed here. Pending the owner: review, merge in order,
  Linear → Done.
