---
ticket: OME-1273
stack: screamingface-engine
status: done
started: 2026-10-01
finished: 2026-10-01
---

# ome-1273-task-replay-benchmarks-a — import the six plain packages by Task replay

## Intent

PR 5a of the OME-1273 stack (stacked on #1194): import bbq, piqa, cybermetric (4 tasks),
worldsense, sad (5 tasks) and sevenllm's two multiple-choice tasks by Task replay, each with
the owner's license decision (2026-10-01) and a no-network grading test (spec R17).

## Planned changes

- `prepare.py`, `benchmarks.py` — the generated rows, prose, tiers and licenses filled.
- `test_inspect_task_replay_benchmarks.py` — the new keys join the grading tests.
- `test_inspect_imported_benchmarks.py`, `test_benchmark_declaration.py` — the new keys join
  the family and policy tables (owner-granted `--skip-append-only`, as on PR 4).

## Test plan

- Each Benchmark: sealed, licensed, registered; a right answer grades 1.0 and a wrong one 0.0
  under `no_network`; MCQ rows carry no check surface.

## Acceptance

- Every key in `TASK_REPLAY_CASES` with two agreeing replays; R7's license gate green; gates green.

## Outcome (fill at the end — required before COMMIT)

- **Imported** (Cases · Case Digest prefix · Case Source · license, owner 2026-10-01):

  | Benchmark | Cases | Digest | Case Source | License |
  | -- | -- | -- | -- | -- |
  | bbq | 58,492 | 8d7652ea4214 | Hugging Face heegyu/bbq at 5d6faae5 | cc-by-4.0 (card) |
  | piqa | 1,838 | bc3ae6040b20 | ybisk/piqa at 2e8ac2df + two unpinned URLs | unknown |
  | cybermetric_80 | 80 | 25fa5f98d03a | CyberMetric GitHub at 205262cd + sha256 | unknown |
  | cybermetric_500 | 500 | df8bfe73bc07 | same | unknown |
  | cybermetric_2000 | 2,000 | f5f42a83a438 | same | unknown |
  | cybermetric_10000 | 10,180 | 058be2a68b92 | same | unknown |
  | worldsense | 40,176 | 426b5a4e50aa | worldsense GitHub at bd81d945 + sha256 | cc-by-nc-4.0 |
  | sevenllm_mcq_zh | 50 | d860352c24d4 | SEVENLLM-Dataset raw at 1de23ce5 | apache-2.0 |
  | sevenllm_mcq_en | 50 | bce35ce9059c | same | apache-2.0 |

- **Commits:** 7d25e468 ledger · 218f33a5 `render_choices` (a question that lists its own
  options stays as written) · 131dc4df Samples carrying choices are MCQ-shaped · the nine
  imports (owner granted `--skip-append-only` for the two tables) · this outcome.
- **Gates:** `run_gates.py screamingface-engine` → ALL GATES GREEN; extra-less pyright clean.
- **Deviations:**
  - sad (5 tasks) moved out of 5a to its own PR (owner, 2026-10-01): its solver adds a system
    message and relabels options "(A) …", and sad_stages_full has chat-message inputs; Case
    Preparation reproduces neither yet, so a sad renderer comes first.
  - worldsense needed two writer changes, both owner-approved: `render_choices=False` (its
    question already lists "(1) (2) (3)") and a third MCQ witness (Samples that carry
    choices), without which its row offered mid-run feedback over three options (OME-796).
  - The four CyberMetric focus lines name their set size: the catalogue refuses two
    Benchmarks with the same focus.
- **Owner-verify:** none; every import ran (two replays each, no model calls).
