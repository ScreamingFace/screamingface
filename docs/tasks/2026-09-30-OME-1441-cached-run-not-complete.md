---
id: OME-1441
linear_url: https://linear.app/openmined/issue/OME-1441/submit-a-run-with-any-cache-hit-as-a-partial-cost-with-no-amount
status: in-progress
type: task
priority: high
labels: [client-sf, agentic, autonomous]
parent: OME-1251
created: 2026-09-30
closed:
---

# Submit a run with any cache hit as a partial cost with no amount

Stops the SDK publishing a cache replay's $0 as an exact cost (`OME-1143`). Owner decision
2026-09-30: any cache hit makes a submission `partial` with no amount, until `OME-1382` ranks on
spend plus saving.

Ledger: `docs/work/2026-09-30-OME-1441-cached-run-not-complete.md`.
Spec: `docs/spec/2026-09-30-cached-run-not-complete.md`.

- 2026-09-30: filed under `OME-1251` at PR-open. Built, all screamingface gates green.
- Not solved here: older SDKs and non-SDK clients (board-side follow-up), stored rows (`OME-1384`).
