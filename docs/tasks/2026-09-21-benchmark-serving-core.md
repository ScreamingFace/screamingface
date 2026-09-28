---
id: OME-1236
linear_url: https://linear.app/openmined/issue/OME-1236/let-a-new-hand-built-benchmark-declare-only-its-dataset-prompt-grading
status: done
type: task
priority: 3
labels: [screamingface-engine, agentic, autonomous, task]
created: 2026-09-21
closed: 2026-09-21
---

# Let a new hand-built benchmark declare only its dataset, prompt, grading, and scoring

Extract the per-board serving plumbing (routes, memoized preflight, case
serving, reply decode — the seven functions contracteval and medxpert carry
name-for-name) into the shared `benchmarks/spine/` core, then migrate both
donor boards onto it with byte-identical protocol golden replay. Three stacked
PRs; remaining boards follow up separately. Details: the Linear issue +
`docs/work/2026-09-21-OME-1236-benchmark-serving-core.md`.
