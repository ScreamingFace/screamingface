---
id: OME-1746
linear_url: https://linear.app/openmined/issue/OME-1746/accept-openrouter-router-metadata-in-the-pre-output-refusal-proof
status: in_progress
type: fix
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1287
created: 2026-10-27
closed:
---

# Accept OpenRouter router metadata in the pre-output refusal proof

The gateway sends `X-OpenRouter-Metadata: enabled` on every OpenRouter call, so each prod reply
carries `openrouter_metadata`. The `OME-1738` proof rejected that field, so the $0 rule for a
refusal before output never applied in prod.

Owner decision (2026-10-27): both OpenRouter zero proofs (pre-output refusal and 429 insurance)
check only billing facts, never the reply format.

- Refusal: status 200, no usage/error, refusal signal, no output, no paid request extras.
- 429: no output, no billed work in `usage`, no paid stage, no paid request extras.
- Both: a non-zero `cost`/`amount` value anywhere keeps the cost unknown.
- Shared helpers in `billing_facts.py`; `docs/usage-accounting.md` and both specs updated.

Related: `OME-1738`, `OME-1446`. Ledger: `docs/work/2026-10-27-openrouter-refusal-metadata.md`.
