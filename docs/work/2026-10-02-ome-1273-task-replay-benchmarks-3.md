---
ticket: OME-1273
stack: screamingface-engine
status: done
started: 2026-10-02
finished: 2026-10-02
---

# ome-1273-task-replay-benchmarks-3 — import sad by Task replay, rendered by capture; cyberseceval_4 probed

## Intent

Plan step 7, batch 1: the five SAD-mini tasks (facts_llms, facts_human_defaults, influence,
stages_full, stages_oversight) as Task-replay Benchmarks on the capture path (#1219, #1191),
each with its sealed declaration, catalogue row, the owner's licence decision (2026-10-01:
cc-by-4.0, LRudL/sad) and a no-network grading test (spec R17). cyberseceval_4's three
deterministically graded tasks (mitre_frr, malware_analysis, threat_intelligence) are probed
with the same importer; each refusal is read and named, never patched around. No mechanism
code: rows, prose and tests only.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`, `benchmarks.py` —
  the generated sad rows, prose, tiers and licences; `task_args={"seed": 7}` on every sad
  row (its choice shuffle and the stages tasks' per-Sample prompt placement are unseeded by
  default, so two replays would disagree; 7 is the repo's existing choice-shuffle seed).
- `tests/unit/inspect/test_inspect_task_replay_benchmarks.py` — the sad keys join the
  sealed/licensed test; a grading test under `no_network` for sad's own lenient scorer.
- `tests/unit/inspect/test_inspect_imported_benchmarks.py`, `test_benchmark_declaration.py` —
  the sad keys join the family and policy tables (prior-test edits; `--skip-append-only`
  locally, as the owner granted on #1194/#1198/#1220/#1221).

## Test plan

- Each sad Benchmark: sealed, licensed, registered; choice-shaped, so no Draft Feedback.
- sad's lenient scorer: "(B)" grades 1.0 against B and 0.0 against A, under `no_network`;
  an answer in no recognised form grades 1/choices (the eval's own chance score).

## Acceptance

- Every importable sad key in `TASK_REPLAY_CASES` with two agreeing replays; R7's licence
  gate green; gates green. Every refused task named with the importer's own words.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Imported** (Cases · Case Digest prefix · Case Source · license, owner 2026-10-01). Every
  sad row records all five SAD-mini zips as Case Sources, because the eval's loader fetches
  all five whichever task is built; each is pinned by upstream's sha256 at LRudL/sad commit
  dfc5c983. Every row carries `task_args={"seed": 7}` and `keep_sample_metadata=True` (the
  importer's rule for an eval's own scorer; sad keeps `sad_id`).

  | Benchmark | Cases | Digest | License |
  | -- | -- | -- | -- |
  | sad_facts_llms | 249 | a84c6535db4e | cc-by-4.0 |
  | sad_facts_human_defaults | 1,200 | faa75981e823 | cc-by-4.0 |
  | sad_influence | 255 | cf1ebc85a3cb | cc-by-4.0 |
  | sad_stages_oversight | 400 | da1c29f15006 | cc-by-4.0 |

- **Refused, in the importer's own words** (nothing patched to let them through):
  - sad_stages_full: `PrepareError: case 15: sample input is empty or not text` — records
    15, 59 and 103 of upstream's stages/full batch files have an empty `body`; the Case
    boundary never prepares a Case with nothing to ask, and a Task-replay row has no named
    exclusion to drop them.
  - cyse4_mitre_frr: `PrepareError: case 1: sample target is empty or not text` — its Samples
    carry no answer key (a regex decides refused/accepted), and `has_answer_key=False` is
    refused at assembly for a Benchmark with no Judge.
  - cyse4_malware_analysis: `PrepareError: case 1: sample target is empty or not text` —
    capture rendered its multi-answer prompt, but the answer key is a list of letters, which
    the boundary does not accept; and its scorer returns a two-part Score (exact match plus
    Jaccard) the adapter cannot map to one number (OME-1268).
  - cyse4_threat_intelligence: `replay failed (exit 1): tenacity.RetryError:
    RetryError[<Future … raised HTTPStatusError>]` from its own `_download_with_cooldown` —
    web.archive.org refused one of the 26 pinned report PDFs after its retries. Behind that
    fetch wait the same list-valued key and two-part score as malware_analysis, and PDF text
    extraction needs `pypdf`, which the `inspect` extra does not install.
  - cyse4_multiturn_phishing: not probed; its solver calls `get_model()` itself and the
    replay child names no model, as the dispatch said.
- **Commits:** one `feat(screamingface-engine)` commit: the four rows, prose and licences,
  plus the tests, ledger and mirror note.
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` → see the PR; the skip
  covers the two contract-table edits only, as the owner granted on #1194/#1198/#1220/#1221.
  `test_benchmark_row_scorer_resolves_and_constructs[frontierscience]` fails standalone and
  passes in the full gate (pre-existing).
- **Deviations:** the batch was planned as sad ×5 + cyberseceval_4 ×3 = 8 Benchmarks; four
  landed. cyberseceval_4 contributes none: two of its "deterministically graded" tasks need
  mechanism this ticket does not carry (a list-valued answer key and a two-part score), one
  has no answer key at all. The seed value (7) is this repo's existing choice-shuffle seed
  (`LAB_BENCH_*_CHOICE_SHUFFLE_SEED`), not an owner decision; any seed is a valid Benchmark,
  but changing it changes every sad Case Digest. Review finding while testing: SAD's lenient
  scorer reads only the start of a reply, so inspect's usual `ANSWER: B` begins with `A` and
  grades as option A; pinned by a test and named in the PR.
- **Owner-verify:** none; every import ran (two replays each, no model calls).
