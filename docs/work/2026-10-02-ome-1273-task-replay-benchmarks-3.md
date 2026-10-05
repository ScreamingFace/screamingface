---
ticket: OME-1273
stack: screamingface-engine
status: done
started: 2026-10-02
finished: 2026-10-05
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

## Amendment 2026-10-05 — sad_stages_full and mitre_frr join this PR (owner direction)

Two of the refusals below become Benchmarks, by spec R18 and R19 (amended 2026-10-05). Owner
decisions 2026-10-05: R19's claim is a row flag plus a per-row test (not an implicit rule);
mitre_frr's licence is `mit` (the eval's code: adapted from Meta PurpleLlama, MIT License); no
Draft Feedback for mitre_frr (a pass/fail check would let a Fusion re-word a draft until it
slips past the refusal regex); the importer takes both as flags, so the rows are generated.

**Planned changes**

- `prepare.py` — `TaskReplayCasesSpec.excluded_sample_ids`; the exclusion helper becomes
  public (`without_excluded_samples`) so capture reuses it, never a second copy.
- `capture.py` — `captured_case_records` drops the excluded Samples before capture.
- `import_replay.py`, `importer.py`, `task_replay_rows.py` — `--excluded-sample-id` (repeatable)
  and `--no-answer-key` reach both replays and the generated row.
- `benchmarks.py` — `BenchmarkSpec.scorer_reads_answer_key`; `_check_answer_key_opt_in`
  accepts no Judge only with it, on the eval's own scorer; `_task_replay_pins` adds the
  excluded ids when set. Rows: `sad_stages_full`, `cyse4_mitre_frr`.
- Tests: `test_capture.py` / `test_task_replay_assembly.py` / `test_judged_benchmark_assembly.py`
  / importer tests for the mechanism; the two keys join the task-replay, family and tier tables.
- Docs: `CONTEXT.md` (Answer key, Grading Material), `adding-an-imported-benchmark.md`.

**Test plan**

- Exclusion: the listed ids are dropped and the rest renumbered 1..N; a missing id refuses by
  name; the ids move the Benchmark Revision only when set (the 19 rows on main keep theirs).
- Key-less: no Judge + no flag refuses (prior test stays); flag + eval's own scorer assembles;
  flag on an `inspect_ai.scorer` built-in refuses; flag on a row with a key or a Judge refuses;
  every flagged row grades one reply the same against an empty and a non-empty key.
- mitre_frr grades with no network: a compliant reply 1.0, "I cannot help with that" 0.0.
- Importer: both flags reach the request, the seal and the generated row.

**Acceptance**

- Both keys imported by the importer with two agreeing replays; gates green; six Benchmarks.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus, from the 2026-10-05 amendment: `capture.py`,
  `import_replay.py`, `importer.py`, `task_replay_rows.py`, the spec (R18, R19), `CONTEXT.md`
  and `adding-an-imported-benchmark.md`; tests in `test_capture.py`,
  `test_import_replay.py`, `test_task_replay_rows.py`, `test_task_replay_assembly.py`,
  `test_judged_benchmark_assembly.py` and `test_inspect_importer.py`. `importer.main` lost
  its flag and Hugging Face-facts lines to two helpers (ruff's statement cap).
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
  | sad_stages_full (2026-10-05) | 797 of 800 | a5d0851ddeee | cc-by-4.0 |
  | cyse4_mitre_frr (2026-10-05) | 750 | d62289a80a9e | mit (owner, 2026-10-05) |

  sad_stages_full leaves out `stages_full:14`, `:58`, `:102` (empty body), a Named Deviation
  on the row (R18). cyse4_mitre_frr's one Case Source is PurpleLlama's `mitre_frr.json` at
  commit fe05293b, no upstream sha256 (the commit and the Case Digest are its pins); no
  answer key, graded by the eval's own refusal regex with `scorer_reads_answer_key=False`
  (R19); acceptance rate, not flipped; no Draft Feedback (owner, 2026-10-05). Both imported
  by the importer (`--excluded-sample-id` ×3 with `--task-arg seed=7`; `--no-answer-key`),
  two agreeing replays each, no model calls.

- **Refused, in the importer's own words** (nothing patched to let them through). The first
  two became Benchmarks on 2026-10-05 by spec R18 and R19 (above); kept here as the record:
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
- **Commits:** two `feat(screamingface-engine)` commits: the four sad rows of 2026-10-02
  with their prose, licences, tests, ledger and mirror note; then the 2026-10-05 amendment
  (R18, R19, sad_stages_full, cyse4_mitre_frr) with its review fixes.
- **Gates (2026-10-05, rebased on main 0e28fe49):** `run_gates.py screamingface-engine
  --skip-append-only` ALL GREEN (ruff, format, pyright, layering, full pytest with coverage).
  The skip now also covers, none of them changing an assertion: five test doubles in
  `test_inspect_importer.py` that gained a `**_` parameter (signature only, owner-approved
  2026-10-05); `sad_stages_full` joining `_SAD_KEYS` in
  `test_inspect_task_replay_benchmarks.py`; the sad/mitre entries and their comments in the
  family table of `test_inspect_imported_benchmarks.py` (the `"reply_only"` family and the
  check-surface test's comment); the tier table in `test_benchmark_declaration.py`.
  Earlier note:
  `run_gates.py screamingface-engine --skip-append-only` → see the PR; the skip
  covers the two contract-table edits only, as the owner granted on #1194/#1198/#1220/#1221.
  `test_benchmark_row_scorer_resolves_and_constructs[frontierscience]` fails standalone and
  passes in the full gate (pre-existing).
- **Deviations:** the batch was planned as sad ×5 + cyberseceval_4 ×3 = 8 Benchmarks; four
  landed on 2026-10-02, six after the 2026-10-05 amendment (owner direction), which added
  mechanism code the plan step had ruled out (R18, R19). cyberseceval_4 contributes one,
  mitre_frr; its other two "deterministically graded" tasks need mechanism this ticket does
  not carry (a list-valued answer key and a two-part score, OME-1268, noted there on
  2026-10-05). The seed value (7) is this repo's existing choice-shuffle seed
  (`LAB_BENCH_*_CHOICE_SHUFFLE_SEED`), not an owner decision; any seed is a valid Benchmark,
  but changing it changes every sad Case Digest. Review finding while testing: SAD's lenient
  scorer reads only the start of a reply, so inspect's usual `ANSWER: B` begins with `A` and
  grades as option A; pinned by a test and named in the PR.
- **Review (sf-code-review on b98f250bc, 2026-10-05):** nothing blocking. Fixed: assembly now
  refuses a check surface on a reply-only row (the importer's generated row turns it on for
  any free-text key-less task); the per-row R19 test asserts only empty-key == keyed-key, so
  an honest future scorer is not held to mitre's grades; `_validated_answer_key`'s docstring
  names reply-only scorers; the `inspect_ai.scorer:` prefix has one home
  (`prepare.INSPECT_SCORER_PREFIX`). Not fixed, pre-existing: `test_published_revisions.py`
  freezes no Task-replay revision (the reviewer checked by hand: none of the 23 moved).
- **Owner-verify:** none; every import ran (two replays each, no model calls).
