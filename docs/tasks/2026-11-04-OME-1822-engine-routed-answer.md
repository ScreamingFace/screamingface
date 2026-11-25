---
id: OME-1822
linear_url: https://linear.app/openmined/issue/OME-1822/serve-one-routed-answer-in-the-engine-classify-select-one-branch
status: in_progress
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1306
created: 2026-11-04
---

# Serve one routed answer in the Engine: classify, select one branch, answer

Engine slice of the router-only BYOM pilot, above hosted BYOM Unit 3. The SDK call is the
sibling OME-1823; both land in one PR.

- `GET /route-answer?q=({"profile": ..., "input": ...})!route-answer`, one direct run: a
  metadata-only preflight of the classifier and every branch, one classification through the
  existing `ClassificationEndpoint`, the unique highest label (`unique-argmax-v1`), and one call
  to the chat model bound to that label through the ordinary chat route, with the unchanged
  question.
- Private profiles in the declared world file: `[routing.profiles.<id>]` with a classifier,
  exactly `general`, `code`, `math`, a declared model and `max_tokens` per label, checked at
  composition; `max_tokens` is also checked against each branch's published contract before the
  classifier is called.
- Result contract `routed-answer-v1`; errors and statuses as spec section 3.5. No synthesizer,
  Fusion, fallback, routing cache, tools, seeds, capture or replay.

Acceptance: spec section 5 through deterministic tests with a fake Gateway, the real executor and
the App; prior tests unchanged; `run_gates.py screamingface-engine` green. Live and hosted proof
are separate.

Spec: `docs/spec/2026-11-04-byom-routing-pilot.md`. Ledger:
`docs/work/2026-11-04-byom-routing-pilot.md`.
