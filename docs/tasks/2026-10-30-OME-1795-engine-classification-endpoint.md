---
id: OME-1795
linear_url: https://linear.app/openmined/issue/OME-1795/serve-one-classification-endpoint-in-the-engine-and-keep-query-text
status: in_progress
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1306
created: 2026-10-30
---

# Serve one classification endpoint in the Engine and keep query text out of access logs

Engine slice of hosted BYOM Unit 3. The Gateway operation is the sibling OME-1794 and the SDK
helper is OME-1796; all three land in one PR.

- One stable `/classify` world endpoint, registered in `build_world` before the direct-mount
  snapshot, so cold, warm and local runs see it. No per-classifier route or world config entry.
- Strict context: a JSON object with exactly `model` and `input`; intent `classify`. The worker
  sends only those two values to the Gateway under the trusted request scope.
- Refused before any classification request: an answer seed, capture and frozen-copy replay. A
  capture run keeps only the existing frozen-copy open and seal; replay and direct calls make no
  Gateway request. Checked through the real executor. Unknown, ungranted and chat model IDs
  answer one `404`.
- Query strings are removed from every Engine access-log record. The 8 KiB encoded limit answers
  `414`.
- After review (spec decisions 7 and 10): a dispatched classification reports one usage record
  with no cost, so a run that also makes a priced chat call ends unpriced; a lone surrogate in the
  context is `malformed_source` before any Gateway request; `check-publication` refuses a
  classifier target declared as an Engine model.

Acceptance: deterministic tests with a fake Gateway and queue and worker substitutes; one
endpoint serves two targets cold and warm with no reconfiguration and no prior listing;
`run_gates.py screamingface-engine` green with no prior test changed. Ingress and proxy logs are
outside this issue; pilot input stays synthetic or public until they are checked. Not a hosted
readiness claim.

Spec: `docs/spec/2026-10-30-hosted-byom-unit3-classification.md`. Ledger:
`docs/work/2026-10-30-hosted-byom-unit3.md`.
