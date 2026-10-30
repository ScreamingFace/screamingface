---
id: OME-1546
linear_url: https://linear.app/openmined/issue/OME-1546/account-image-and-file-tokens-in-the-costusage-taxonomy
status: done
type: task
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1529
created: 2026-10-09
closed: 2026-10-23
---

# Account image and file tokens in the cost.usage taxonomy

Image and PDF input cost is billed inside `prompt_tokens` with no field saying how much was media.
Gateway half: `usage.prompt_tokens_details.image_and_file_tokens`, filled from Gemini
`promptTokensDetails` (IMAGE + DOCUMENT) where present, explicit `null` on the Gemini /
Antigravity / Codex adapters otherwise, and absent (also unknown) on LiteLLM pass-through
providers. Totals unchanged. Spec: `docs/spec/2026-10-20-image-token-accounting.md`.

Scope narrowed by the owner on 2026-10-27: OME-1546 closes the gateway unit (#1481) only. Engine
forwarding into `ai.url4.cost.usage` and the live non-zero image-token acceptance moved to
OME-1744 ("Forward image and file tokens from the gateway into the engine's run cost", under
OME-1529). Other follow-ups: owner decision on an explicit `null` for pass-through providers;
Codex cached-tokens drop filed as OME-1683 (bug).

- 2026-10-20: gateway half implemented on `OME-1546-image-token-accounting`; PR opened.
- 2026-10-22: final review fix (subset bound) authored; work finished.
- 2026-10-27: scope narrowed to the gateway unit; engine half moved to OME-1744.

Merged in PR #1481 as `b76556ca3` on 2026-10-23.
