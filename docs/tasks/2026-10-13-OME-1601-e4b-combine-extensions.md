---
id: OME-1601
linear_url: https://linear.app/openmined/issue/OME-1601/add-mean-weighted-median-judge-order-filter-by-judge-and-pick-output
status: in_progress
type: feature
priority: 3
labels: [client-sf, agentic, autonomous]
created: 2026-10-13
closed:
---

# Add mean, weighted median, judge order, Filter by judge and Pick output to combine

Mirror of OME-1601 (parent epic OME-1290, E4b). E4b part 1 on top of the E4a deterministic
combine (OME-1289). One branch, `OME-1601-e4b-combine-extensions`, on `main`.

Scope: the writer after Rank or Filter sees the Case input; offline recipes for 11 combine
scenarios; `mean@1` and `weighted_mean@1`; `weighted_median@1`; `sf.Judge(order="min")`; Filter by
judge score; `sf.Pick(output=...)`; a refactor that removes repeated code. The signal sources
(`verbalized`, `logprob`, `entropy`, `consistency@N`) and a judge per member are deferred.

Design: `docs/spec/2026-10-13-e4b-combine-extensions/`, `docs/plan/2026-10-13-e4b-combine-extensions.md`.
Ledgers: `docs/work/2026-10-13-e4b-*.md`. Test approvals: `.claude/test-change-approvals/OME-1601.json`.
