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
CLI on a **plus** account works. A plus plan is also refused for every static catalog slug
(retired upstream). Fix: the refusal reaches the caller as a typed 403 `codex_model_unsupported`
naming the model and the plan, plus `available_models` from the account's live list
(`GET /backend-api/codex/models`), returned only to that account's own refusal; `/v1/models`
serves the static seeds, swapped to the four current models (owner-approved 2026-10-17). Ledger: `../work/2026-10-16-codex-plan-unsupported.md`.
