---
id: OME-1496
linear_url: https://linear.app/openmined/issue/OME-1496/paid-smoke-cap-the-qwen-members-reasoning-at-reasoning-effortlow
status: done
type: task
priority: high
labels: [client-sf, agentic, autonomous]
created: 2026-10-06
closed: 2026-10-06
---

# Paid smoke: cap the qwen member's reasoning at reasoning_effort=low

Paid smoke run 37442602029 (2026-10-06, head dfbe0b7a1) failed only on
`inspect-lab_bench_cloning_scenarios`: 0/2 graded, `model_token_cap` x2. qwen3.7-flash spent the
whole 32768-token cap on reasoning and wrote no answer. #1254's Task replay changed inspect's
shuffle, so `slice=0:2` now picks two longer DNA Cases. Fix: `reasoning_effort="low"` on the qwen
member only; haiku and the gemini synthesizer keep their params. Parent epic: OME-1299.

Ledger: `docs/work/2026-10-06-paid-smoke-qwen-reasoning-low.md`.

- 2026-10-06: implemented; free pin tests green; PR opened, one paid dispatch pending (owner).
