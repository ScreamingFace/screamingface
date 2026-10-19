---
id: OME-1602
linear_url: https://linear.app/openmined/issue/OME-1602/import-the-remaining-single-turn-text-inspect-evals-benchmarks
status: in_progress
type: feature
priority: medium
labels: [screamingface-engine, human, design-session]
parent: OME-1412
created: 2026-10-14
closed:
---

# Import the remaining single-turn text inspect_evals benchmarks

A probe of every remaining single-turn text package in OME-1412 found that only five import
with row edits alone. The rest either break at grading (several silently), need an importer
change, or aren't single-turn. The ticket carries the per-package table, the fault boxes F1–F11
and the owner decisions; this mirror tracks the six-PR stack.

- PR 1: guards for scorer arguments (F1) and extra-scorer metrics (F5). Adds no Benchmark.
- PR 2: guard for judges the importer doesn't see (F2). Adds no Benchmark.
- PR 3: guards for reading the model during replay (F3) and a judge inside the solver chain
  (F4). Adds no Benchmark.
- PR 4: simpleqa, simpleqa_verified, fortress_benign, strong_reject, aime2026, uccb, and
  two as local Tasks: infinite_bench_math_find and air_bench (+8).
- PR 5: multi-letter answer keys (F6). truthfulqa mc1, chembench, stereoset,
  cyse4_malware_analysis (+4). cyse4_threat_intelligence waits for its PDF mirror.
- PR 6: function scorer arguments (F1). drop (+1).
- The inspect_evals 0.20.0 to 0.24.0 bump and the sciknoweval slices moved to OME-1410.

- 2026-10-14: filed; owner decisions recorded on the ticket (aime2026 and uccb in, the pin bump is part of this ticket).
- 2026-10-15: the guards PR was split into three at the owner's call; PRs 1–3 opened as drafts.
- 2026-10-19: the pin bump (planned as PR 7) moved to OME-1410 at the owner's call, so a Benchmark's published ID moves only where its exam changed; the stack is six PRs.
