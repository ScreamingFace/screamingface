---
id: OME-1579
linear_url: https://linear.app/openmined/issue/OME-1579/add-the-deterministic-combine-core-to-the-engine
status: in_progress
type: feature
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-12
closed:
---

# Add the deterministic combine core to the engine

Mirror of OME-1579 (parent epic OME-1289). PR 2 of 16 in the E4a stack, branch
`OME-1579-e4a-combine-core` on `OME-1578-e4a-spec`.

Add `/ensemble/combine/v1`: the Engine combines member answers by rules from the call, with no model. Ports, the operator registry (`name@version`), the strict spec and context parsers, the evidence wire (`screamingface.combine-evidence.v1`), per-member Answers (answered or fail), abstain on no usable value, and cost, latency and token signals per member. It also reads a Fusion quorum panel (OME-1557): a member the panel left out is a fail Answer with the reason `missing`.

Ledgers: `docs/work/2026-09-30-e4a-combine-core.md`, `docs/work/2026-10-02-e4a-gap-closure-unit1.md`.
