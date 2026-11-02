---
id: OME-1746
linear_url: https://linear.app/openmined/issue/OME-1746/base-the-openrouter-zero-proofs-on-billing-facts-not-the-reply-format
status: in_progress
type: fix
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1287
created: 2026-10-27
closed:
---

# Base the OpenRouter zero proofs on billing facts, not the reply format

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

Review follow-up (same issue, owner decision 2026-10-27): the `/code-review` of #1571 found three
gaps, fixed in a second PR: no proof raises on a value of any shape; the refusal proof sees output
in any message field; both proofs share the paid-stage rule. Ledger:
`docs/work/2026-10-27-openrouter-zero-proof-review-fixes.md`.
