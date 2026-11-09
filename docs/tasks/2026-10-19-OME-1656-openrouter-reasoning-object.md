---
id: OME-1656
linear_url: https://linear.app/openmined/issue/OME-1656/support-openrouter-reasoning-objects-in-sfmodel-parameters
status: pick_immediately
type: bug
priority: medium
labels: [bug]
parent:
created: 2026-10-19
closed:
---

# Support OpenRouter reasoning objects in sf.Model parameters

Expose OpenRouter's object-form reasoning effort through the existing scalar dotted parameter
`reasoning.effort`. The gateway validates and projects it to `reasoning: {effort: ...}`, includes it
in cache identity and the model-parameter contract, and refuses simultaneous use with the legacy
`reasoning_effort` spelling.

Ledger: ../work/2026-10-19-openrouter-reasoning-object.md
