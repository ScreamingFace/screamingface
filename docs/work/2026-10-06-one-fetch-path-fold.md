---
ticket: OME-1460
stack: screamingface-engine
status: done
started: 2026-10-06
finished: 2026-10-06
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

- **Actual files:** as planned, plus `revision_inputs.py` (pins.py's three plugin-wide
  revision inputs, moved verbatim), `tests/unit/inspect/test_importer_command.py` (the
  one-path command), `tests/unit/inspect/replayed_cases_helpers.py` (Benchmark tests prepare
  their Cases by Task replay's own rendering), the deleted `scripts/sweep_task_replay_fold.py`
  and `docs/diagrams/importer-pipeline.*`, and the approval in
  `.claude/test-change-approvals/OME-1460.json`. Diff against PR 1 of 2: 36 files changed, 1565 insertions(+), 7833 deletions(-).
- **Commits:** the spec amendment; the inert-seed refusal; `--keep-sample-metadata`; the
  non-ASCII excluded id fix; the 30-row fold with re-pointed tests and 20 literal moves; the
  deletion; the R15 no-network lane and the lab_bench answer test; the docs; the approval; the
  importer Protocol fix.
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` ALL GATES GREEN (ruff,
  format, pyright, layering, pytest with coverage); without the skip, the append-only check
  approves all ten changed prior test files (OME-1460.json) and flags only the two deleted
  files, which no blob approval can cover. Pyright without the `inspect` extra (CI's shape)
  clean. `run_gates.py repo` green. Every one of the 30 rows was sealed by the real two-run
  import against its live sources (run 2 is the image-side child every build runs).
- **Deviations:**
  - 30 rows, not 28: coconot's two arrived with OME-1371 (spec amended).
  - The 30 rows landed in one commit, not two halves (P5): both halves were imported in one
    pass; the fold notes still name each row's change.
  - Two importer additions the plan did not name: a declared seed nothing applies is refused
    (R10's promise needed the import child to report which seeds it used), and
    `--keep-sample-metadata` (coconot's Judge reads Sample metadata while its scorer is
    inspect's own, which alone drops it; without the flag coconot would grade blind).
  - onet_m6's Thai excluded ids exposed an ASCII-only guard in the row writer; the ids land
    inside a JSON string literal, so only an unreadable id is refused now.
  - `pins.py` also held three plugin-wide revision inputs; they moved verbatim to
    `revision_inputs.py` (house pattern), so no Benchmark Revision moved for them.
  - 20 frozen literals moved, not 19: frontierscience freezes its own revision in its own test.
  - Ten prior test files changed, not three: generic tests used the gsm8k Hugging Face row as a
    fixture through a shared helper; all re-pointed with the owner's approval (2026-10-06).
  - One prior scorer test passed only by test order (the judge provider registers on import);
    it now imports the provider itself.
  - `import_replay.py` is 480 lines, over the 450 guideline; its two new helpers belong with the
    import's run, and splitting it would move public names other modules import.
  - boolq's licence `cc-by-sa-3.0` is carried over from its Hugging Face-path row; it is not
    on the cleared list, so the owner confirms it in review.
  - The review agent's config (`.claude/agents/sf-code-review.md`) still names
    `screamingface_engine_inspect/pins.py`; it is owner territory and left for a review-agent
    PR.
  - Review round: the eight fold rows whose eval's own scorer keeps Sample metadata (aime ×2,
    lab_bench ×6) now say so in their fold notes, and the how-to states the rule once; an
    eval-seeded shuffle is pinned as not counting as an applied seed; the no-network lane is
    pinned non-empty; prepare.py is read and written as UTF-8 (onet_m6's Thai ids).
