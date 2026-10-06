---
ticket: OME-1460
stack: screamingface-engine
status: in_progress
started: 2026-10-06
finished:
---

# one-fetch-path-fold — every Imported Benchmark prepared by Task replay; the Hugging Face path deleted

## Intent

PR B of OME-1460 (spec `docs/spec/2026-10-02-ome-1460-one-fetch-path.md`, plan
`docs/plan/2026-10-02-OME-1460-one-fetch-path.md`, D5: two PRs). PR A (#1237) taught Task
replay to force a declaration's Hub commit and seeds. This PR moves the 30 Benchmarks still
prepared by the Hugging Face path onto Task replay, each under its existing key with a new
Benchmark Revision, then deletes the Hugging Face reader, its registry (`BENCHMARK_CASES`,
`CasesSpec`), its writer and `pins.py`. One preparation path, one declaration shape, one
importer command. Closes the ticket.

## Planned changes

- `docs/spec/2026-10-02-ome-1460-one-fetch-path.md`: R12 amended from the Task 0 sweep (30
  rows, not 28; mmlu, hellaswag, frontierscience explained; licences decided).
- `prepare.py`: 30 rows out of `BENCHMARK_CASES`, 30 into `TASK_REPLAY_CASES` (source pins,
  task args, seeds, exclusions, gate, licence, a fold note each); then `BENCHMARK_CASES`,
  `CasesSpec` and the Hugging Face writer deleted (spec R17).
- `benchmarks.py`: provenance comments; descriptions that promise our own shuffle corrected;
  paws and race_h credit their source; `_revision_pins`, `_dropped_question_pins` deleted.
- `importer.py`: the Hugging Face reader and its routes deleted; `main` always imports by
  Task replay; `--shuffle-seed` / `--choice-shuffle-seed` forwarded (D7).
- `task_replay_rows.py`, `scorer_adapter.py`: the leftovers R17 names.
- `pins.py`: deleted (D8).
- Tests: 18 literals in `test_published_revisions.py` and 1 in `test_inverted_grade.py` move
  (owner approval manifest); gsm8k, mmlu, frontierscience benchmark tests re-pointed;
  lab_bench answer-position test; the R15 no-network grading lane; Hugging Face-path tests
  deleted with their code.
- `CONTEXT.md` (Task replay entry), `apps/screamingface-engine/docs/importing-an-inspect-eval.md`,
  `docs/adding-an-imported-benchmark.md` (R18, R19).
- `docs/tasks/2026-10-02-OME-1460-one-fetch-path.md`: closed.

## Test plan

- Each re-imported row: Case count, kept Sample ids and text verdict match the Task 0 sweep.
- lab_bench: no row has its target at one letter for every Case (D1, Review Focus 10).
- Every `TASK_REPLAY_CASES` key grades a stand-in answer with outbound network blocked (R15).
- The importer CLI imports by Task replay without a flag and forwards the seeds.
- The moved literals freeze the new revisions; the 22 URL-only and 5 Hub-pinned Task-replay
  revisions from PR A do not move.

## Acceptance

- Spec acceptance 1–8 (9 met by the merged spec).
- `run_gates.py screamingface-engine` and `run_gates.py repo` green.

## Licence decisions (owner, 2026-10-06)

- gsm8k, mmlu: `mit` from their Hub cards (cleared list).
- hellaswag: `mit`, per rowanz/hellaswag (owner decision 2026-09-22, carried over).
- winogrande: `cc-by-4.0`; allenai/winogrande's README says "CC-BY" with no version.
- paws: Google's PAWS licence ("may be freely used for any purpose"); credit Google LLC as
  the data source.
- race_h: non-commercial research only (CMU's RACE terms); credit and link the source page.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
