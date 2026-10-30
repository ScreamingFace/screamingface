---
id: OME-1786
linear_url: https://linear.app/openmined/issue/OME-1786/medxpert-turn-2-embeds-turn-1-accounting-so-a-frozen-copy-replay
status: triage
type: bug
priority: medium
labels: [bug, screamingface-engine, agentic]
created: 2026-10-29
closed:
---

# MedXpert turn 2 embeds turn-1 accounting, so a frozen-copy replay misses every turn-2 call

MedXpert turn 2 (`benchmarks/medxpert/definition.py:137-198`) puts the turn-1 candidate-invocation
envelope into its prompt, with `operations[].accounting` (usage, cost, latency, cache hits). At
replay the accounting differs, so the turn-2 request digest differs and every turn-2 call gets
`frozen_copy_miss`. A Case that scored in the capture fails at replay. Found with a stub gateway
while building OME-1775; not checked in prod.

- 2026-10-29: filed in Triage, unassigned; Irina and Kevin tagged for review.
