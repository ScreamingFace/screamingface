---
ticket: OME-1477
stack: screamingface-engine
status: done
started: 2026-10-28
finished: 2026-10-28
---

# import-mmmu — import MMMU (multiple choice and open) as picture Benchmarks

## Intent

MMMU is a college-level exam over 30 subjects where every question carries one to seven
pictures. inspect_evals ships it as two tasks: `mmmu_multiple_choice` (847 questions, the
eval's `choice()` scorer) and `mmmu_open` (53 questions, graded by `model_graded_fact`, a
Judge). Since OME-1271 a Case carries its pictures inline, and LAB-Bench FigQA and TableQA
(OME-1327, #1556) proved the path, so MMMU becomes two Task-replay data rows. Onboarding
only: no paid run and no state-of-the-art run (that is OME-1671).

## Planned changes

- Size check first (no code): every place a whole Benchmark's Cases are held at once, against
  MMMU's measured 3.78 MB largest Case and ~281 MB whole set.
- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`, `.../benchmarks.py`
  — the importer's rows for `mmmu_multiple_choice` and `mmmu_open`, then the prose, tier,
  provenance and baselines by hand.
- The importer fix for the `prompt_template` then `multiple_choice` chain named on the ticket,
  only if a real import shows the captured prompt differs from what inspect_evals sends.
- The per-Benchmark test tables, one row each: `test_benchmark_declaration.py`,
  `test_failure_policy_rows.py` (and its row counts), `test_inspect_imported_benchmarks.py`,
  `test_published_revisions.py`, `test_benchmark_fingerprints.py`.
- `.claude/test-change-approvals/OME-1477.json` for those prior-test edits.
- `docs/tasks/` mirror for OME-1477.

## Test plan

- RED first: the test-table rows for both keys, failing until the rows exist.
- Byte check: run inspect_evals' own Task offline on a few real rows (its solvers, a stand-in
  model that records what it is sent) and compare with the captured Cases, pictures included.
- The importer's own second replay reproduces the Case Digest.

## Acceptance

- Both rows registered as `inspect-mmmu_multiple_choice` / `inspect-mmmu_open`, 847 and 53
  Cases, pictures inside, licence matching the dataset card and an existing precedent, no
  TODO left, no check surface.
- No existing Benchmark's id or revision moves.
- Relevant inspect-lane tests, ruff and pyright green on the touched files.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `prepare.py` and `benchmarks.py` (the `mmmu_multiple_choice` rows), the five
  test tables, new `tests/unit/inspect/test_mmmu_picture_cases.py`,
  `.claude/test-change-approvals/OME-1477.json`, `docs/tasks/2026-10-05-OME-1477-import-mmmu.md`.
  No importer change: Task replay runs the `prompt_template` then `multiple_choice` chain for
  real, so the fix the ticket named was not needed.
- **Commits:** one, `feat(screamingface-engine): import MMMU's multiple-choice task with its pictures`.
- **Size check (2026-10-28):** nothing blocks. Per Case 3.78 MB under the importer's 8 MB and
  the gateway's 8 MiB; at most 5 pictures under 20. `cases.json` is 265 MB (multiple choice) and
  read plus parse peaked at 1,381 MB resident, under the 2,560 MiB per-run budget (FigQA, 330 MB,
  peaked 1,611 MiB). The one strain: the gateway's frozen-copy entry cap is 2,000,000 bytes, and
  17 of the 847 Cases are bigger than that on their own, so a captured run cannot freeze those
  calls (the capture says `failed`; the run itself goes on).
- **Import (real Hub data at `MMMU/MMMU` `171b0ef7`):** 847 Cases, Case Digest `08e8974a…`,
  27 min and 4.97 GB peak on the laptop; the build path's replay (`prepare_replayed_cases`)
  agreed, 11 min. Published revision `98430e6d5f4d79ec` from `benchmark_bump.py`.
- **Byte check:** inspect's own `eval()` with the free mockllm model on 8 Cases (1 to 5
  pictures, the largest Case included): role, part order, text and every picture's bytes and
  type identical to the Case. `mmmu_open` too, 6 Cases.
- **Gates:** 22 cross-row test files with the inspect extra, 1,548 passed; 4 failures in
  `test_benchmark_display_metadata.py` / `test_benchmark_protocol.py` are pre-existing (the
  unlisted wmdp rows, OME-1714) and pass extra-less, as CI runs them. New test passes and fails
  on both mutants (template line removed, pictures swapped). ruff, ruff format, pyright with and
  without the extra clean on the 8 touched Python files.
- **Deviations:** `mmmu_open` (53 Cases) imported but held out of the diff: the scorer adapter
  hands `model_graded_fact` the prompt the Candidate saw, while inspect hands it the Sample's
  original question, so our judge's question starts with "Answer the question using a single
  word or phrase." Owner decision 2026-10-28: ship multiple choice now, hold `mmmu_open`
  until the judge fix (OME-1755) lands; it then ships on this ticket with gpt-5.4 as judge.
  Frontier score GPT-5 0.842 (OpenAI, 2025-08) read from the vendor page itself on 2026-10-28
  ("84.2% on MMMU", pass@1 with thinking). Licence apache-2.0 accepted by the owner.
- **Owner-verify:** none for this PR; the paid and state-of-the-art runs are OME-1671.
