---
ticket: OME-1273
stack: screamingface-engine
status: done
started: 2026-10-02
finished: 2026-10-02
---

# ome-1273-task-replay-benchmarks-1 — import agieval, medqa and mgsm_en by Task replay, rendered by capture

## Intent

The first ten Task-replay Benchmarks (eight agieval tasks, medqa, mgsm_en), re-imported on the
capture path (#1219, #1191) after the owner closed #1194, whose rows were rendered by the
imitation writer and carried a hand-pinned agieval template constant. Each Benchmark lands
with its sealed declaration, its catalogue row, the owner's licence decision (2026-10-01,
unchanged) and a grading test that runs with outbound network blocked (spec R17). No
mechanism code: this PR is rows, prose and tests.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`, `benchmarks.py` —
  the ten generated rows, prose, tiers and licences carried over from #1194's reviewed rows.
- `tests/unit/inspect/test_inspect_task_replay_benchmarks.py` (new, from #1194 verbatim).
- `tests/unit/inspect/test_inspect_imported_benchmarks.py`, `test_benchmark_declaration.py` —
  the catalogue contract covers Task-replay declarations and the ten keys join the family
  and policy tables (prior-test edits; the owner granted `--skip-append-only` for the same
  edit on #1194).

## Test plan

- Each Benchmark: the declaration is sealed and names its task; a correct answer grades 1.0
  and a wrong one 0.0 through the real url4 routes, with `no_network`.
- mgsm_en offers Draft Feedback; the nine MCQ rows do not (OME-796).

## Acceptance

- Ten Benchmarks in `TASK_REPLAY_CASES` + `BENCHMARKS`, each digest agreed by two replays.
- R7's licence gate green (no `TODO` licence left). Gates green.
- No `upstream_templates.py`, no `--choice-template`: capture renders agieval's template.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Imported** (Cases · Case Digest prefix · Case Source), every digest byte-identical to
  #1194's, so capture confirms the imitation render was right for these ten:

  | Benchmark | Cases | Digest | Case Source |
  | -- | -- | -- | -- |
  | agieval_lsat_ar | 230 | 5f77e982829b | GitHub raw at commit 84ab72d9 |
  | agieval_lsat_lr | 510 | 104db4473e5e | same repo and commit |
  | agieval_lsat_rc | 269 | 984f6070d532 | same |
  | agieval_sat_math | 220 | 54ac8e2293cf | same |
  | agieval_sat_en | 206 | 02045f612ebb | same |
  | agieval_sat_en_without_passage | 206 | fe8910e42383 | same |
  | agieval_aqua_rat | 254 | 64dce3527cc1 | same |
  | agieval_logiqa_en | 651 | 7c80ae3ee578 | same |
  | medqa | 1273 | ea4634b08252 | Hugging Face bigbio/med_qa at revision ddef95d2 |
  | mgsm_en | 250 | 3f34b5110fc1 | openaipublic mgsm_en.tsv, upstream sha256 50021d0f |

- **Licenses (owner, 2026-10-01, unchanged):** agieval mit, medqa mit (the bigbio card says
  unknown), mgsm_en cc-by-4.0.
- **Commits:** one `feat(screamingface-engine)` commit: the ten rows, prose and licences
  spliced from #1194's reviewed rows, plus the tests.
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` → ALL GATES GREEN (the
  skip covers the two contract-table edits, as the owner granted on #1194).
- **Deviations:** none. `upstream_templates.py`, its pin test and `--choice-template` are
  gone: capture renders agieval's run-time template directly and the digests prove it.
  The declaration rows carry no `choice_template=` line (medqa's and the eight agieval ones
  had one on #1194); nothing else in a row changed but the import date.
  Review fix (2026-10-02): medqa's prose said four options; the replayed bigbio
  `med_qa_en_bigbio_qa` subset has five per Case, so the description now says five.
- **Owner-verify:** none outstanding; every import ran (two replays each, no model calls).
