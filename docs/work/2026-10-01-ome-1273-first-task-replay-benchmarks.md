---
ticket: OME-1273
stack: screamingface-engine
status: done
started: 2026-10-01
finished: 2026-10-01
---

# ome-1273-first-task-replay-benchmarks — import agieval, medqa and mgsm_en by Task replay

## Intent

PR 4 of the OME-1273 stack (stacked on #1191): import the first ten Task-replay Benchmarks:
eight agieval tasks, medqa and mgsm_en. Each lands with its sealed declaration, its catalogue
row, the owner's licence decision (decided 2026-10-01) and a grading test that runs with
outbound network blocked (spec R17).

## Planned changes

- `apps/screamingface-engine/tests/unit/inspect/test_inspect_imported_benchmarks.py` — the
  catalogue contract covers Task-replay declarations (Task 4.0; owner granted
  `--skip-append-only` for that one commit).
- `apps/screamingface-engine/src/screamingface_engine_inspect/upstream_templates.py` (new) —
  agieval's run-time choice template as a constant, pinned by a test against agieval's solver.
- `import_replay.py`, `importer.py` — `--choice-template module:attr`: the import child
  renders with a template constant only after checking it equals the template the Task holds.
- `prepare.py`, `benchmarks.py` — the ten generated rows, prose and licences filled.
- Tests: `test_upstream_templates.py`, `test_inspect_agieval_benchmarks.py`,
  `test_inspect_medqa_benchmark.py`, `test_inspect_mgsm_benchmark.py` (new).

## Test plan

- The template override refuses a constant that differs from the Task's template.
- Each agieval key's template constant equals what `agieval_solver` builds (no network).
- Each Benchmark: the declaration is sealed and names its task; a correct answer grades 1.0
  and a wrong one 0.0 through the real url4 routes, with `no_network`.

## Acceptance

- Ten Benchmarks in `TASK_REPLAY_CASES` + `BENCHMARKS`, each digest agreed by two replays.
- R7's licence gate green (no `TODO` licence left).
- Gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, except one grading-test file for all ten
  (`test_inspect_task_replay_benchmarks.py`) instead of three, and
  `test_benchmark_declaration.py`'s expected-policy table also gained the ten rows.
- **Imported** (Cases · Case Digest prefix · Case Source):

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

- **Licenses (owner, 2026-10-01):** agieval mit (ruixiangcui/AGIEval LICENSE), medqa mit
  (jind11/MedQA LICENSE; the bigbio card says unknown), mgsm_en cc-by-4.0
  (google-research/url-nlp mgsm/LICENSE).
- **Commits:** d66fc71d ledger · fcb55ade verified choice-template override · ae9f6a33
  agieval's template constant + pin test · 7421d70b the ten imports + catalogue contract
  (owner granted `--skip-append-only` for that commit) · then this outcome.
- **Gates:** `run_gates.py screamingface-engine` → ALL GATES GREEN.
- **Deviations:**
  - The first real import found agieval builds its choice template at run time; owner chose
    our constant + pin test (2026-10-01), so the importer gained `--choice-template`, which
    the import child refuses unless the constant equals the template the Task holds.
  - It also found two PR 3 bugs (refusal traceback under `python -m`, solver-flag wording
    refused as code) and a PR 3 test using `agieval_lsat_ar` as its sample key; all three
    fixed on #1191 (b357437b, 1ae4265a) and this branch rebased onto it.
  - `dataset_url` points at each dataset's home page (the AGIEval and url-nlp GitHub repos),
    not the raw file a Case Source names.
  - Difficulty tiers are argued in words in each row, without published scores.
- **Owner-verify:** none outstanding; every import already ran (two replays each, no model
  calls).
