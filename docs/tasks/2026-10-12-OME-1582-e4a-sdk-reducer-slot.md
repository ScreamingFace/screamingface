---
id: OME-1582
linear_url: https://linear.app/openmined/issue/OME-1582/let-an-sdk-fusion-end-in-a-reducer
status: in_progress
type: feature
priority: 3
labels: [client-sf, agentic, autonomous]
created: 2026-10-12
closed:
---

# Let an SDK Fusion end in a reducer

Mirror of OME-1582 (parent epic OME-1289). PR 5 of 16 in the E4a stack, branch
`OME-1582-e4a-sdk-reducer-slot` on `OME-1581-e4a-engine-wiring`.

Add `sf.Reduce`, `sf.Extract`, `sf.signal` and `sf.matches`; compile a reducer synthesizer to one combine call after checking the Engine's operator catalog before spend; decode the evidence into `case.answers()`, abstain counts and the `screamingface.report-trace.v1` export. A Fusion with quorum or optional members may end in a reducer: the members reach the combine call as a broadcast panel.

Ledgers: `docs/work/2026-09-30-e4a-sdk-reducer-slot.md`, `docs/work/2026-10-02-e4a-gap-closure-unit4.md`.
