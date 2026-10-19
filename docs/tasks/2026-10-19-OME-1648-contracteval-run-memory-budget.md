---
id: OME-1648
linear_url: https://linear.app/openmined/issue/OME-1648/validate-a-larger-per-run-memory-budget-for-contracteval
status: in_progress
type: task
priority: high
labels: [screamingface-engine]
parent: OME-1607
created: 2026-10-19
closed:
---

# Validate a larger per-run memory budget for ContractEval

ContractEval cannot pass even a three-case sample under the 1 GiB per-run resident budget
(`memory_budget_exceeded`). Each run loads the whole 192 MiB `cases.json` (4,182 full CUAD
contracts). This blocks the ContractEval part of OME-1606.

- 2026-10-19: measured on kind — 1,382 MiB at 1 GiB (stopped during case loading); completed at
  2 GiB with a 1,828 MiB peak. Numbers posted on the Linear issue.
- 2026-10-19: owner chose option (c): budget 2,560 MiB now, 4 slots kept (VM capacity to grow);
  selective case loading as a follow-up issue. Ledger:
  `docs/work/2026-10-19-contracteval-run-memory-budget.md`.
