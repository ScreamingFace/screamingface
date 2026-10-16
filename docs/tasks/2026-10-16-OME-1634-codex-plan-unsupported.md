---
id: OME-1634
linear_url: https://linear.app/openmined/issue/OME-1634/codex-calls-through-the-gateway-fail-with-400-on-every-model-text-only
status: in_progress
type: bug
priority: high
labels: [bug, aigateway, agentic]
created: 2026-10-16
closed:
---

# Codex calls through the gateway fail with 400 on every model, text-only included

Root cause: the gateway's Codex sign-in was on a ChatGPT **free** plan; the Codex backend refuses
every model for it ("not supported when using Codex with a ChatGPT account"), while the `codex`
CLI on a **plus** account works. Not a request-wiring defect. Fix: that refusal now reaches the
caller as a typed 403 `codex_plan_unsupported` naming the plan from the token, instead of a
400 `provider_error` relaying upstream text. Ledger: `../work/2026-10-16-codex-plan-unsupported.md`.
