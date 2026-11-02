---
id: OME-1794
linear_url: https://linear.app/openmined/issue/OME-1794/classify-text-with-configured-endpoint-classifiers-through-a-typed
status: in_progress
type: feature
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1306
created: 2026-10-30
---

# Classify text with configured endpoint classifiers through a typed Gateway operation

Gateway slice of hosted BYOM Unit 3, on top of the merged chat slices. The Engine endpoint is the
sibling OME-1795 and the SDK helper is OME-1796; all three land in one PR.

- Definitions: a typed classifier target next to chat targets (`task = "text-classification"`,
  `contract = "hf-text-classification-v1"`, flat or single-batch envelope, `bounded-score`).
- Operation: `POST /v1/classifications` forwards the exact input as `{"inputs": ...}` and returns
  labels and scores unchanged, in upstream order, ties kept. No argmax, softmax, downstream call,
  cache or accounting.
- Catalog: `GET /v1/classifiers` and `GET /v1/classifiers/details?model=`, caller-filtered.
- Readiness probes the task of the validation target; `/v1/providers` lists a provider by
  inference capability, so a classifier-only endpoint is connectable.
- Chat never lists or calls a classifier, and classification never calls a chat target.
- After review (spec decision 10): a model or input holding a lone surrogate is refused as
  `400 invalid_request` before any key read or upstream request.
- After the second review (spec decision 11): a body nested past the JSON decoder's depth is the
  malformed-body `400`, not a `500`, before any provider lookup, key read or upstream request.
- After the third review (spec decision 12): a lone surrogate in an unknown field name is
  `400 invalid_request`, not a `500`; the Gateway's own `503 provider_queue_timeout` logs at
  WARNING as in chat, an upstream `503` stays ERROR; a test pins the grant before the alias.

Acceptance: deterministic tests with fake upstreams; unknown, ungranted and wrong-task IDs cause
no credential read and no upstream I/O; `run_gates.py aigateway` green. Two owner-approved prior
test changes in `test_definitions.py` (spec decisions 1 and 1a: one task value, and two
`ChatTarget` type assertions before reading `upstream_model`), pinned by
`.claude/test-change-approvals/OME-1794.json`. Not a hosted readiness claim.

Spec: `docs/spec/2026-10-30-hosted-byom-unit3-classification.md`. Ledger:
`docs/work/2026-10-30-hosted-byom-unit3.md`.
