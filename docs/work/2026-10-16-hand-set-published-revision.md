---
ticket: OME-1610
stack: python
status: done
started: 2026-10-16
finished: 2026-10-22
---

# hand-set-published-revision — Every Benchmark publishes a hand-set version ID; a fingerprint test is the alarm

## Intent

A Benchmark's published version ID (its revision) is what submissions and the leaderboard key
on. Before this unit most Benchmarks published an ID computed from their definition, including
source code, so a code move with an unchanged exam minted a new ID and emptied the leaderboard
(draco-3pass, OME-1527). This unit makes the published ID hand-set on every Benchmark (today's
value, so nothing moves on prod), pins each Benchmark's computed fingerprint in a test as the
alarm, and adds a bump command that prints the WARNING and the lines to edit. The rule (when
an ID may move, how, what it costs, human sign-off, announcing it) is written where agents and
people read it.

Stacked on OME-1701 PR 7 (#1515): OME-1701 holds 8 rows and seeds
`test_benchmark_fingerprints.py`, which this unit extends to every Benchmark.

## Planned changes

Owner decisions 2026-10-16: medxpert in scope; bump command = script + just recipe; the
published-revisions test stays and gains the unpinned rows. 2026-10-22: stack on OME-1701;
enforce "every row sets one" with a catalogue test (the field stays optional, so test stand-ins
are untouched); the rule uses the frozen-revisions bar (move only on a fundamental change:
changed Case set or a new Benchmark; a grading fix, refactor or package bump holds).

- `screamingface_engine_inspect/single_shot.py` — `ImportedBenchmark.fingerprint`; the
  copied-row check compares fingerprints as well as revisions.
- `screamingface_engine_inspect/benchmarks.py` — every row (85) sets `published_revision`;
  the field's note carries the rule.
- `screamingface_engine/benchmarks/medxpert/definition.py` — hand-set `REVISION`; the computed
  one becomes `FINGERPRINT`.
- `scripts/benchmark_bump.py` + Engine `justfile` mounted in the root `justfile`.
- Tests: `test_benchmark_fingerprints.py` pins all 86; `test_published_revision.py`'s allow-list
  becomes "every row sets one"; `test_published_revisions.py` gains the unpinned rows;
  `test_benchmark_bump.py` new.
- Docs: `docs/adding-an-imported-benchmark.md` section, local Task README pointers, CHANGELOG.

## Test plan

- A fingerprint pin per Benchmark (86); its failure message names both paths.
- Every catalogue row sets `published_revision`.
- A copied row with the same key and published id but a different fingerprint is refused.
- medxpert publishes its hand-set id; its fingerprint is pinned.
- The bump command prints the WARNING and the edit lines, and writes no file.

## Acceptance

- No Benchmark's published ID is computed; every row sets it; a definition change turns its
  fingerprint test red; the bump command prints the WARNING; a code move keeps the ID.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus: 7 prior identity tests in 6 files
  (`test_letter_list_key_imports`, `test_local_task_gdpval`, `test_nltk_data_at_image_build`,
  `test_retrieval_policy_on_row`, `test_scorer_draft_feedback`, `test_whole_run_metric`) read
  `.fingerprint` instead of `.benchmark.revision`; 14 local Task READMEs (not 8: six had no
  Identity section and gained one); the guide's four "the revision moves" lines now say the
  fingerprint moves; `.claude/test-change-approvals/OME-1610.json`; the task mirror.
- **Commits:** see the PR.
- **Gates:** relevant tests only (owner rule): the 32 test files that read a Benchmark's
  revision or import the changed code, 1303 passed; ruff check + format and extra-less pyright on
  the 14 touched `.py` files clean. Full suite left to CI and the pre-push hook.
- **Deviations:** no separate `benchmark_fingerprint` function: `ImportedBenchmark.fingerprint`
  carries the value, and the tests and the bump command read it after assembly (YAGNI). The field
  stays `str | None` and a catalogue test enforces it (owner decision 2026-10-22), instead of a
  required field. 7 prior tests edited with owner approval (they test the computed hash, which
  now lives in `.fingerprint`). Published ids: none moved (all 85 rows + medxpert pinned).
