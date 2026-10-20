---
id: OME-1546
linear_url: https://linear.app/openmined/issue/OME-1546/account-image-and-file-tokens-in-the-costusage-taxonomy
status: in_review
type: task
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1529
created: 2026-10-09
closed:
---

# Account image and file tokens in the cost.usage taxonomy

Image and PDF input cost is billed inside `prompt_tokens` with no field saying how much was media.
Gateway half: `usage.prompt_tokens_details.image_and_file_tokens`, filled from Gemini
`promptTokensDetails` (IMAGE + DOCUMENT) where present, explicit `null` on the Gemini /
Antigravity / Codex adapters otherwise, and absent (also unknown) on LiteLLM pass-through
providers. Totals unchanged. Spec: `docs/spec/2026-10-20-image-token-accounting.md`.

Follow-ups: engine forwarding into `ai.url4.cost.usage` (engine owner); owner decision on an
explicit `null` for pass-through providers; Codex cached-tokens drop filed as OME-1683 (bug).

- 2026-10-20: gateway half implemented on `OME-1546-image-token-accounting`; PR opened.
