---
id: OME-1753
linear_url: https://linear.app/openmined/issue/OME-1753/price-an-openrouter-refusal-with-a-policy-notice-at-dollar0
status: in_progress
type: fix
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1287
created: 2026-10-27
closed:
---

# Price an OpenRouter refusal with a policy notice at $0

Anthropic sometimes puts a policy notice in `message.refusal` when it refuses before output.
These replies have no `usage`, no output tokens and no cost, so OpenRouter does not bill them.
The pre-output refusal proof counted the notice as output, so the cost stayed `unavailable`.

The prod cache backfill on 2026-10-27 found 8 such rows of 160. The owner priced them at $0 by
hand. This change makes the live proof agree: text in `refusal` is not output. The proof still
needs no `usage`.

- Spec: `docs/spec/2026-10-26-openrouter-pre-output-refusal-zero.md` §10
- Ledger: `docs/work/2026-10-27-openrouter-refusal-notice-zero.md`
