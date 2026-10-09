---
id: OME-1435
linear_url: https://linear.app/openmined/issue/OME-1435/add-e14-capture-and-replay-modes-to-the-engine
status: in_progress
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-30
closed:
---

# Add E14 capture and replay modes to the Engine

Parent: OME-1307. 1 PR, in the E14 stack.

Ledger: `docs/work/2026-10-08-e14-b3-engine-frozen-copy.md`.
Spec: `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` (binding).

Scope:

- Headers: `X-Capture: true` and `X-Replay-Frozen-Copy: <uuid>`. Both at once is a 400.
- Capture: the run opens a frozen copy, sends its id on every chat call, stores every web-tool result and seals the copy at the end. The run is `complete` only when every step is stored.
- Replay: every chat call goes to the replay route. Tavily and model admission are never called. A miss fails the case with `frozen_copy_miss`.
- Depends on OME-1434. Deploy order: gateway, then engine workers, then the App.

- 2026-10-09: PR opened on branch `OME-1435-e14-b3-engine-frozen-copy`; gates green against the branch below; owner-approved test edits recorded in the ledger.
