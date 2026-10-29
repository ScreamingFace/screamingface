---
id: OME-1744
linear_url: https://linear.app/openmined/issue/OME-1744/forward-image-and-file-tokens-from-the-gateway-into-the-engines-run
status: done
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-27
closed: 2026-10-28
---

# Forward image and file tokens from the gateway into the engine's run cost

The engine reads the gateway's `usage.prompt_tokens_details.image_and_file_tokens` (#1481) and carries it into
the run cost as `gen_ai.usage.image_and_file_tokens` on url4's `Usage`/`TokenUsage`.

- **Unknown is never 0.** Unknown covers no breakdown, a null value and a cache hit, and it is left out of the frame. Text-only frames from providers without a breakdown stay byte-identical. A provider that reports a real 0 (Gemini) emits it.
- **Totals.** Span and run totals are unknown if any contributing call is unknown. This is a deliberate departure from OME-869's run-total rule for this one field.
- **Input totals** are unchanged, because image tokens are already inside them.

Split from `OME-1546` (gateway half, #1481). Parent epic `OME-1529`. Live non-zero acceptance stays open: no credentials were available.

Merged as `8de39b882` (PR #1572, approved by IonesioJunior) on 2026-10-28.
