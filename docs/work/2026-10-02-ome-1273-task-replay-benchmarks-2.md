---
ticket: OME-1273
stack: screamingface-engine
status: done
started: 2026-10-02
finished: 2026-10-02
---

# ome-1273-task-replay-benchmarks-2 — import bbq, piqa, cybermetric, worldsense and sevenllm by Task replay, rendered by capture

## Intent

Nine more Task-replay Benchmarks from five packages (bbq, piqa, the four CyberMetric sets,
worldsense, SEvenLLM's two multiple-choice tasks), re-imported on the capture path (#1219,
#1191) after the owner closed #1198. That PR's sevenllm rows were wrong: the imitation writer
dropped sevenllm's chained instruction template, and both replays agreed because both ran the
same writer. worldsense needed a render switch and a letter-target exception there; capture
serves its question as written and the writer accepts its answer key by value (#1219). Each
Benchmark lands with its sealed declaration, its catalogue row, the owner's licence decision
(2026-10-01, unchanged) and a no-network grading test (spec R17). No mechanism code.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`, `benchmarks.py` —
  the nine generated rows, prose, tiers and licences carried over from #1198's reviewed rows.
- `tests/unit/inspect/test_inspect_task_replay_benchmarks.py` — the nine keys join the grading
  tests.
- `tests/unit/inspect/test_inspect_imported_benchmarks.py`, `test_benchmark_declaration.py` —
  the nine keys join the family and policy tables (prior-test edits; owner-granted
  `--skip-append-only`, as on #1198).

## Test plan

- Each Benchmark: sealed, licensed, registered; a right answer grades 1.0 and a wrong one 0.0
  under `no_network`; every row is choice-shaped, so none offers Draft Feedback (OME-796).

## Acceptance

- Every key in `TASK_REPLAY_CASES` with two agreeing replays; R7's licence gate green; gates
  green. sevenllm's Case Digests differ from #1198's (the instruction is now in the Case).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Imported** (Cases · Case Digest prefix · Case Source · license, owner 2026-10-01). Seven
  digests equal #1198's; sevenllm's two are new, because the instruction template is now
  inside every Case:

  | Benchmark | Cases | Digest | vs #1198 | Case Source | License |
  | -- | -- | -- | -- | -- | -- |
  | bbq | 58,492 | 8d7652ea4214 | same | Hugging Face heegyu/bbq at 5d6faae5 | cc-by-4.0 (card) |
  | piqa | 1,838 | bc3ae6040b20 | same | ybisk/piqa at 2e8ac2df + two unpinned URLs | unknown |
  | cybermetric_80 | 80 | 25fa5f98d03a | same | CyberMetric GitHub at 205262cd + sha256 | unknown |
  | cybermetric_500 | 500 | df8bfe73bc07 | same | same | unknown |
  | cybermetric_2000 | 2,000 | f5f42a83a438 | same | same | unknown |
  | cybermetric_10000 | 10,180 | 058be2a68b92 | same | same | unknown |
  | worldsense | 40,176 | 426b5a4e50aa | same | worldsense GitHub at bd81d945 + sha256 | cc-by-nc-4.0 |
  | sevenllm_mcq_zh | 50 | 8c703ae7baf2 | was d860352c24d4 | SEVENLLM-Dataset raw at 1de23ce5 | apache-2.0 |
  | sevenllm_mcq_en | 50 | dae1e9538a49 | was bce35ce9059c | same | apache-2.0 |

- **Commits:** one `feat(screamingface-engine)` commit: the nine rows, prose and licences
  spliced from #1198's reviewed rows, plus the tests.
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` → ALL GATES GREEN (the
  skip covers the two contract-table edits, as the owner granted on #1198).
- **Deviations:** none. `render_choices`, the letter-target exception and the agieval-style
  patches #1198 carried do not exist here: capture serves worldsense's question as written,
  and the writer accepts its answer key by value (#1219).
  Rows changed against #1198 only by the import date, the dropped `choice_template=`
  (piqa) and `render_choices=False` (worldsense) lines, and sevenllm's two digests.
  Review (2026-10-02): a TRUE/FALSE grading pair joined worldsense's numbered one. Open
  question for the owner: whether the four CyberMetric sets nest (80 ⊂ 500 ⊂ …); the
  descriptions do not say, and the import did not keep the files to check.
- **Owner-verify:** none; every import ran (two replays each, no model calls).
