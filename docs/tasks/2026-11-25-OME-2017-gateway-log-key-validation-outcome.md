---
id: OME-2017
linear_url: https://linear.app/openmined/issue/OME-2017/log-which-validation-call-refused-a-provider-key-in-the-ai-gateway
status: done
type: fix
priority: low
labels: [aigateway, agentic, autonomous]
parent: OME-1317
created: 2026-11-25
closed: 2026-11-25
---

# Log which validation call refused a provider key in the AI Gateway

Before the AI Gateway stores a provider key it checks the key with two calls (authentication,
then readiness), and `unavailable` and `misconfigured` both answer 503. The gateway logged
nothing about the check, so a client that flattened the response body left a bare 503 in the
access log: paid smoke run 45538646440 died on one and its cause was never found. The gateway
now writes one `api_key_validation_refused` line per refused check (provider, state, stage,
probe model): WARNING for `unavailable` and `misconfigured`, INFO for the rest, nothing for a
valid key. Gateway-authored values only: never the key, never provider text. No response
changes.

- 2026-11-25: built in one PR. Owner actions left: merge; deploy.
- Ledger: `docs/work/2026-11-25-gateway-log-key-validation-outcome.md`
