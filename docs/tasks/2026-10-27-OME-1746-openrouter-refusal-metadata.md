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

- Accept `openrouter_metadata` when it proves a plain route (`is_byok: false`, only known fields).
- Cleanups: shared shape checks in `response_shape.py`; `docs/usage-accounting.md` updated.

Related: `OME-1738`. Spec: `docs/spec/2026-10-26-openrouter-pre-output-refusal-zero.md` §8.
Ledger: `docs/work/2026-10-27-openrouter-refusal-metadata.md`.
