---
id: OME-1823
linear_url: https://linear.app/openmined/issue/OME-1823/add-clientroute-answer-for-the-engine-routed-answer-endpoint
status: in_progress
type: feature
priority: high
labels: [client-sf, agentic, autonomous]
parent: OME-1306
created: 2026-11-04
---

# Add Client.route_answer for the Engine routed answer endpoint

SDK slice of the router-only BYOM pilot. It calls the Engine endpoint from the sibling OME-1822;
both land in one PR.

- `Client.route_answer(profile, input) -> RoutedAnswer`, sync only, one GET never marked safe
  to replay, `Prefer: wait=60` with a 75 second read. No `sf.route_answer`, no async method.
- `sf.RoutedAnswer` with profile, revision, policy, contract, classifier, scores, selected label
  and model, and the answer. A strict decoder of `routed-answer-v1` (spec section 3.6).
- Retryable only when nothing ran: a connect-phase failure, an ingress `429`,
  `routing_preflight_unavailable`. A `503` is not retryable, even with `Retry-After`.
- The one-GET transport moves to `_engine/direct_get.py`; `classify` keeps its messages, codes,
  retry rules and 30 s and 45 s timeouts, and `tests/test_classify.py` is unchanged.

Acceptance: tests with a fake Engine transport; public surface snapshot regenerated on the
branch base, pinned by `.claude/test-change-approvals/OME-1823.json`; a `CHANGELOG.md` entry;
`run_gates.py screamingface` green.

Spec: `docs/spec/2026-11-04-byom-routing-pilot.md`. Ledger:
`docs/work/2026-11-04-byom-routing-pilot.md`.
