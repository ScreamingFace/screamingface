---
id: OME-1977
linear_url: https://linear.app/openmined/issue/OME-1977/stop-the-futurex-past-judge-sending-temperature-0
status: in-review
type: bug
priority: high
labels: [bug, screamingface-engine, agentic]
created: 2026-11-19
closed:
---

# Stop the FutureX-Past Judge sending temperature 0

On the hosted Engine every FutureX-Past level-3/4 Case failed as `scorer_error`: the Judge pinned
`temperature: 0` on `openrouter/openai/gpt-5.4`, and no OpenRouter endpoint for that model
accepts it under the gateway's `require_parameters`. Filed in Triage, unassigned (bug rule), with
Irina and Kevin tagged. Ledger: `docs/work/2026-11-19-futurex-judge-temperature.md`.
