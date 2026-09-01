---
id: OME-966
linear_url: https://linear.app/openmined/issue/OME-966/the-run-topic-is-published-in-public-score-metadata
status: backlog
type: decision
priority: 2
labels: [scoreboard, agentic, design-session]
created: 2026-08-24
closed:
---

# The run topic is published in public score metadata

`subject == topic` (url4 `_Sequencer`) → client `run_id = subject` (`contract.py:286`) →
`metadata.run_id` on every submission → returned verbatim by the unauthenticated
`GET /v1/scores/{score_id}`. Invariant drift, not a live vulnerability: engine routes read
the topic out of a *verified* token, so topic knowledge alone authorizes nothing. Becomes
real the moment anything authorizes on topic knowledge — e.g. evidence-bundle retrieval.
Root cause includes a wrong docstring at `url4/streaming/protocol/envelope.py:25`.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md` (§1, §4)
