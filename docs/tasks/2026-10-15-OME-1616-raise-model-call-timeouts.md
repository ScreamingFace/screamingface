---
id: OME-1616
linear_url: https://linear.app/openmined/issue/OME-1616/raise-model-call-timeouts-to-30-minutes-for-arc-agi-2
status: in_progress
type: bug
priority: medium
labels: [bug]
created: 2026-10-15
closed:
---

# Raise model call timeouts to 30 minutes for ARC-AGI-2

ARC-AGI-2 runs on prod stopped at 10 minutes on a single model call. Three budgets sit in a row
and the smallest wins: the Engine's `[aigateway] timeout_s` in `url4.toml` (sent to the gateway as
`x-aigw-execution-timeout-s`), the gateway cap `AIGW_PROVIDER_EXECUTION_TIMEOUT_S`, and LiteLLM's
own HTTP timeout, which falls back to 600 s unless `REQUEST_TIMEOUT` is set. All three move to
1800 s: the Engine file (baked into the Runner image) and the gateway chart's `extraEnv` in both
`values.yaml` and `values-prod.yaml`. Ledger: `../work/2026-10-15-arc-agi-timeouts-30m.md`.
