---
id: OME-1434
linear_url: https://linear.app/openmined/issue/OME-1434/add-the-e14-frozen-copy-capture-and-replay-to-the-ai-gateway
status: in_progress
type: feature
priority: high
labels: [aigateway, agentic, autonomous]
created: 2026-09-30
closed:
---

# Add the E14 frozen copy (capture and replay) to the AI Gateway

Parent: OME-1307. 1 PR, in the E14 stack.

Ledger: `docs/work/2026-10-08-e14-b1-gateway-frozen-copy.md`.
Spec: `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` (binding).

Scope:

- Store: tables `frozen_copies` and `frozen_copy_entries`, migration `0014`. Copies are kept forever. No route returns stored requests.
- Capture: a chat call with `X-AIGW-Frozen-Copy` stores its request and its answer. A store failure never fails the call. Streaming is not captured.
- Routes: open, seal and tool-results routes for the owner. Replay routes serve sealed copies to any account.
- The cache-revision design is removed.

- 2026-10-09: PR opened on branch `OME-1434-e14-b1-gateway-frozen-copy`; gates green against the branch below; owner-approved test edits recorded in the ledger.
