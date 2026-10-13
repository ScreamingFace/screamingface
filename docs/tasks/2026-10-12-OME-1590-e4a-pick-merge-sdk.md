---
id: OME-1590
linear_url: https://linear.app/openmined/issue/OME-1590/add-sfpick-sfmerge-and-argmax-by-signal
status: in_progress
type: feature
priority: 3
labels: [client-sf, agentic, autonomous]
created: 2026-10-12
closed:
---

# Add sf.Pick, sf.Merge and argmax by signal

Mirror of OME-1590 (parent epic OME-1289). PR 13 of 16 in the E4a stack, branch
`OME-1590-e4a-pick-merge-sdk` on `OME-1589-e4a-judge-pick-sdk`.

`sf.Pick(field=…)`, `sf.Pick(by_signal=sf.signal("cost_usd"), order="min")` and `sf.Merge({field: sf.FieldRule…})` with a writer model for a field; a field path longer than the Engine allows fails before spend.

Ledgers: `docs/work/2026-10-01-e4a-pick-merge-sdk.md`, `docs/work/2026-10-02-e4a-gap-closure-unit9s.md`.
