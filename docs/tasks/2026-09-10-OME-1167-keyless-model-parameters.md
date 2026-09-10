---
id: OME-1167
linear_url: https://linear.app/openmined/issue/OME-1167/checking-a-models-parameter-limits-fails-unless-a-provider-is
status: done
type: bug
priority: Medium
labels: [aigateway, agentic, autonomous]
created: 2026-09-10
closed: 2026-09-10
---

# Checking a model's parameter limits fails unless a provider is connected

`GET /v1/model-parameters` reuses the chat credential resolution, so an account with no
profile/connection for a provider gets 404 `profile_not_found` — even though the
parameter contract is static datasheet content. Make the contract answerable keyless;
dispatch and connection flows unchanged. Root cause lands in aigateway (relabelled from
`screamingface-engine` after investigation). Ledger:
`docs/work/2026-09-10-OME-1167-keyless-model-parameters.md`.
