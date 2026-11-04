---
id: OME-1773
linear_url: https://linear.app/openmined/issue/OME-1773/check-hosted-byom-preflight-per-account-in-the-sdk-against-a-fake
status: in_progress
type: feature
priority: high
labels: [client-sf, agentic, autonomous]
parent: OME-1306
created: 2026-10-29
---

# Check hosted BYOM preflight per account in the SDK against a fake Engine

SDK slice of hosted BYOM Unit 2, beside OME-1770 (Engine) and OME-1771 (Gateway chart); the three
land in one PR. Tests only, no SDK code change.

`packages/screamingface/tests/test_hosted_byom_preflight.py` gives each account its own fake
Engine view of one configured endpoint model, with the Gateway's real `openai-chat-basic-v1`
contract shape: `max_tokens` only, no `seed` row.

- Granted with a key: listed, `execution_access = configured`; the run reaches execution.
- Granted without a key: listed, `missing`; refused as `provider_not_connected` before dispatch.
- Not granted: absent from the listing; the details probe gets the Engine's not-installed 404;
  refused as `model_unavailable` before dispatch.
- A seeded evaluation is refused as `unsupported_model_parameter` before dispatch.

Each case covers a plain Model and a Fusion mixing the endpoint with a subsidized model, sync and
async. No refusal dispatches a Candidate or emits an event.

Ledger: `docs/work/2026-10-29-hosted-byom-unit2.md`.
