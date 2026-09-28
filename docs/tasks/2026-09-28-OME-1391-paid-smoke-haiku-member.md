---
id: OME-1391
linear_url: https://linear.app/openmined/issue/OME-1391/keep-the-paid-smoke-from-leaving-boards-ungraded-when-a-panel-model
status: in_review
type: task
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1299
created: 2026-09-28
closed:
---

# Keep the paid smoke from leaving boards ungraded when a panel model runs out of tokens

The 2026-09-28 paid press left `lab_bench_cloning_scenarios` and `lab_bench_seqqa` with zero
graded Cases: panel member `deepseek-v4-flash-0731` spent its whole 32,768-token budget
thinking on all 4 of their Cases, and a Fusion Case needs every member's answer. Swap that
member for `claude-haiku-4.5` (answers without thinking, always finishes); keep
`qwen3.7-flash` as the reasoning member so the engine's reasoning-only paths stay live.

Owner decisions (2026-09-28): a Case still dies when any member fails (quorum stays parked in
OME-559); swap the model rather than raise `max_tokens`.

- 2026-09-28: filed at PR-open; ledger `docs/work/2026-09-28-paid-smoke-haiku-member.md`.
