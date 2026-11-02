---
id: OME-1738
linear_url: https://linear.app/openmined/issue/OME-1738/price-an-openrouter-refusal-before-output-as-dollar0
status: in_progress
type: fix
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1287
created: 2026-10-26
closed:
---

# Price an OpenRouter refusal before output as $0

On the lab_bench boards, runs of `claude-opus-5.5` show cost "—". Anthropic refuses some biology
questions before the model writes output. Through OpenRouter that reply is HTTP 200 with
`native_finish_reason: "refusal"`, no output and no `usage`, and OpenRouter keeps no generation
record for it. One such call made the whole run unpriced.

- aigateway: certify that exact shape as `provider_guaranteed_zero`
  (source `openrouter.pre_output_refusal`); fail closed on anything else.
- screamingface-engine: price that certified zero as $0, live and on a cache hit.

Spec: `docs/spec/2026-10-26-openrouter-pre-output-refusal-zero.md`.
Ledger: `docs/work/2026-10-26-openrouter-pre-output-refusal-zero.md`.
