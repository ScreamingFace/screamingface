---
ticket: OME-1477
stack: screamingface-engine
status: done
started: 2026-10-28
finished: 2026-10-30
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
- **Import (real Hub data at `MMMU/MMMU` `171b0ef7`):** 847 Cases. First sealed on the laptop
  (Case Digest `08e8974a…`, revision `98430e6d5f4d79ec`); the laptop's own build-path replay
  agreed, but that only proved the laptop agrees with itself.
- **Re-sealed on linux/amd64 (review round, 2026-10-29):** CI's image build got a different
  digest. inspect_evals re-encodes every picture with Pillow (`thumbnail` + PNG save), and
  Pillow's macOS wheel compresses with zlib-ng while the Linux wheel uses zlib: same pixels,
  different PNG bytes. The import re-run inside the linux/amd64 Engine image gives Case Digest
  `3fe742a9…`, the same value CI's strict image build printed on run 40685859823. Published
  revision `5b008891134ef4c1` from `benchmark_bump.py`. A prepare on a Mac now sees this
  bundle as changed and skips it.
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
- **Owner-verify (PR 1):** none for this PR; the paid and state-of-the-art runs are OME-1671.

### PR 2 — `mmmu_open` (2026-10-30)

- **Actual files:** the `mmmu_open` rows in `prepare.py` and `benchmarks.py`, one row each in
  the five test tables (row counts 88→89 and 71→72), new
  `tests/unit/inspect/test_mmmu_open_cases.py`, the OME-1477 approval re-pointed at the PR 2
  branch (it now covers both PRs' rows, as OME-1696 did), this ledger and the mirror, closed.
  No engine code change: OME-1755 already keeps the Sample's question for the judge.
- **Import (real Hub data at `MMMU/MMMU` `171b0ef7`, inside the linux/amd64 Engine image built
  from this branch, 18 min under emulation):** 53 Cases, Case Digest `3078a742…`,
  `case_set_digest` `d4387286…`, `keep_sample_input=True` written by the importer. No Case was
  refused: none is picture-only, none would drop earlier turns. 52 Cases carry one picture, one
  carries two; largest Case 657,527 bytes (`validation_Pharmacy_26`), `cases.json` 4.2 MB. The
  Mac-built copy of the same Case was 558,635 bytes, the same Pillow split PR 1 hit.
- **Build path:** a second run in the same image, the image build's own
  `prepare_replayed_cases`, reproduced count and Case Digest.
- **Byte check, all 53 Cases:** inspect's own `eval()` of inspect_evals' `mmmu_open` Task, free
  `mockllm/model` as Candidate and `mockllm/judge` as judge (only the scorer's model swapped).
  For every Sample the Candidate's prompt (role, part order, text, each picture's bytes and type)
  matched exactly one Case, the target matched, and our adapter's judge prompt was byte-equal to
  inspect's, without the "Answer the question using a single word or phrase." line. Both arms
  made one judge call per Case. Our grade was `invalid_score_value` on all 53 because the mock
  judge writes no GRADE line; that is the stand-in, not the row.
- **Decisions:** judge gpt-5.4 through the gateway, the uccb/xstest pin (owner, 2026-10-28);
  licence apache-2.0 as accepted for PR 1, replacing the importer's `TODO`; tier `medium`, as
  for PR 1, since no source scores the open questions alone; policy `withhold` (a per-Case mean
  over the judge's grade, like uccb); human baseline 0.886 kept from eval.yaml with a
  not-like-for-like note; frontier score `NotPublished`, because the paper and the lab figures
  score the whole validation split and never split by question type. Published revision
  `8ce88e420239ae4d` from `benchmark_bump.py`.
- **Tests:** the eight files the brief names plus the new one, 766 passed with the inspect
  extra. The new file fails on both mutants tried: the two pictures swapped in the Case, and the
  adapter ignoring the kept question. ruff, ruff format and pyright (with and without the extra)
  clean on the 8 touched Python files.
- **Owner-verify (PR 2):** confirm the tier, the empty frontier score and the kept human
  baseline; CI's "Build the deployable images" is the only check that proves the Linux seal.
