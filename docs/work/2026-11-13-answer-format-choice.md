---
ticket: OME-1906
stack: screamingface-engine
status: done
started: 2026-11-13
finished: 2026-11-13
---

# answer-format-choice — every Benchmark page states the answer format its grader reads (PR 1 of 2: inspect's choice)

## Intent

A submitter (deana, seffic, liorrk) paid for a full MMLU-Pro run whose model wrote
`ANSWER: $C`; inspect's `choice` scorer reads that as no answer, so 68 of 200 replies scored 0
(OME-1886). The grader stays as it is (it matches inspect, and our own 7 full runs, 84,224
replies, contain no such reply). Instead, every Benchmark's leaderboard description ends with
one sentence stating the answer format its grader reads, so a submitter can check a 20-Case
smoke run before paying for the whole Benchmark. The sentence is written once per scorer
(95 rows share 38 scorers) and appended by the Engine, so it cannot drift per row, and every
example reply it quotes is graded through the row's real grader in a test. The description is
not part of the revision, so no published revision or fingerprint moves; the scoreboard's seed
job copies the new description on the next deploy (`update_or_create`).

PR 1 of 2: the table, the append, the tests, and the 35 rows graded by `inspect_ai.scorer:choice`.
PR 2 of 2: the other 37 scorers (60 rows), and a test that every row has a sentence.

## Planned changes

- NEW `apps/screamingface-engine/src/screamingface_engine_inspect/answer_formats.py` — the per-scorer table and the append
- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py` — `_assemble` publishes the described text
- NEW `apps/screamingface-engine/tests/unit/inspect/test_answer_formats.py`
- `apps/screamingface-engine/CHANGELOG.md`
- `docs/tasks/2026-11-13-OME-1906-answer-format-on-benchmark-pages.md` (mirror, at PR-open)

## Test plan

- Every `choice` row's published description ends with the choice sentence; its hand-written prose is kept in front.
- Every accepted example in the sentence scores 1 and every rejected example scores 0, through each `choice` row's real grader, no network.
- A row whose scorer has no entry yet publishes its description unchanged (PR 1 scope).
- The revision does not move: every row's fingerprint test stays green untouched.

## Acceptance

- `/v1/benchmarks` serves the sentence for all 35 `choice` rows; the fingerprint and published-revision tests pass unedited.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned: `answer_formats.py` (new), `benchmarks.py` (one call site + import), `test_answer_formats.py` (new), `CHANGELOG.md`, the mirror and this ledger. No prior test edited.
- **Commits:** the PR 1 of 2 commit on `OME-1906-pr1-answer-format-choice`.
- **Gates:** run only the files this touches, per the owner's relevant-tests rule. With the inspect extra: `test_answer_formats.py` 73 passed; together with the 14 files that read descriptions, the catalogue, fingerprints or published revisions, 1224 passed and 3 failed. The 3 are `test_benchmark_display_metadata.py` catalogue tests that fail the same way on a checkout without this change (an empty catalogue for wmdp_bio with the extra installed); extra-less, as CI runs it, that file passes 19/19. ruff check, ruff format and pyright clean on the 3 touched Python files. Mutation check: moving `ANSWER: (B)` into the accepted examples turns the grading test red (`[1.0, 0.0, …] != [1.0, 1.0, …]`).
- **Deviations:** none from the plan. Found while checking: the scoreboard copies descriptions with `update_or_create` on every deploy (`apps/scoreboard/src/scoreboard/scores/store.py`), so no scoreboard change is needed; the leaderboard page renders `benchmark.description` as text.
