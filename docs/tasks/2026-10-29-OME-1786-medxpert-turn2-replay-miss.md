---
id: OME-1786
linear_url: https://linear.app/openmined/issue/OME-1786/medxpert-turn-2-embeds-turn-1-accounting-so-a-frozen-copy-replay
status: done
type: bug
priority: medium
labels: [bug, screamingface-engine, agentic]
created: 2026-10-29
closed: 2026-11-21
---

# MedXpert turn 2 embeds turn-1 accounting, so a frozen-copy replay misses every turn-2 call

MedXpert turn 2 (`benchmarks/medxpert/definition.py:137-198`) puts the turn-1 candidate-invocation
envelope into its prompt, with `operations[].accounting` (usage, cost, latency, cache hits). At
replay the accounting differs, so the turn-2 request digest differs and every turn-2 call gets
`frozen_copy_miss`. A Case that scored in the capture fails at replay. Found with a stub gateway
while building OME-1775; not checked in prod.

- 2026-10-29: filed in Triage, unassigned; Irina and Kevin tagged for review.
- 2026-11-21: fixed. Turn 2 now carries only the text of the turn-1 answer, read through a
  MedXpertQA-owned route, so a rerun or a frozen-copy replay sends the same turn-2 bytes. The
  same defect made a plain rerun miss the request cache: an external researcher saw 1,899 of
  2,450 commit calls billed again. The turn-2 prompt changes on every Case, so the published
  revision moves `1e5a3b8a461a52f7` → `490235dc9a53b7d9` with the owner's sign-off. This is the
  "smaller first step" of GitHub issue 1966; turn 2 is still a new call to the whole Candidate.
  Ledger: `docs/work/2026-11-21-medxpert-turn2-reasoning-text-only.md`.
  Branch: `OME-1786-medxpert-turn2-reasoning-text-only`.
