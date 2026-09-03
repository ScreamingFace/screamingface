---
id: OME-906
linear_url: https://linear.app/openmined/issue/OME-906
asana_url:
status: in_progress
type: task
priority: 1
labels: []
created: 2026-08-20
closed:
---

# Cached DRACO evaluations overflow the Runner event bridge

The Runner publishes one frame for each broker round trip. A cached DRACO burst makes
events far faster. Therefore the bridge overflows its 8192-event hard cap and a correct
Evaluation fails.

The correction pipelines the publishes with a bounded number of acknowledgements in
flight, and adds a durability barrier at the outcome boundary of the run.

- Spec: `docs/spec/2026-08-20-OME-906-pipelined-frame-publishing.md`
- Plan: `docs/plan/2026-08-20-OME-906-pipelined-frame-publishing.md`
- Ledger: `docs/work/2026-08-20-OME-906-pipelined-frame-publishing.md`

## Owner actions outstanding

OME-906 carries **no labels**. The card requires a landing leaf, one `actor` and one
`who-acts`. The Linear MCP plugin is not active in this session, and the card forbids any
other transport for mutations. Proposed set:

- landing: `screamingface-engine` (the deployable that shows the defect; the landing group
  is single-select, so `url4-python-sdk` cannot also apply)
- actor: `agentic`
- who-acts: `autonomous`

The state also needs the move to *in progress*.
