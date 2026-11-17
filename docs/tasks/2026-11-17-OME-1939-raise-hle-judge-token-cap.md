---
id: OME-1939
linear_url: https://linear.app/openmined/issue/OME-1939/hle-scores-a-case-0-when-the-judge-runs-out-of-tokens-before-it-gives
status: Done
type: bug
priority: High
labels: [bug, screamingface-engine, agentic, design-session]
parent_epic:
assignee:
created: 2026-11-17
closed: 2026-11-17
---

# HLE scores a Case 0 when the judge runs out of tokens before it gives a grade

The HLE judge (`glm-5.3-flash`) ran out of its 32,768-token budget on about 1.5% of Cases and
wrote no grade, so those Cases counted 0. Fix: `hle` and `hle_diamond` pin the judge's
`max_tokens` at 131072 (the model's OpenRouter limit), and the judge role is bound with the
row's pins so inspect_evals' `default.yaml` stanza cannot override them. Published revisions
held; a re-grade and revision bump follow (`OME-1909`). Closed on merge.

Work ledger: `docs/work/2026-11-17-raise-hle-judge-token-cap.md`.
