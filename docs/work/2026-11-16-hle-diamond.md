---
ticket: OME-1863
stack: screamingface-engine
status: done
started: 2026-11-16
finished: 2026-11-16
---

# hle-diamond — add HLE-Diamond as its own Benchmark

## Intent

[HLE-Diamond](https://huggingface.co/datasets/cais/hle-diamond) is the authors' cleaned
successor to Humanity's Last Exam: 1,000 vetted questions. `hle` cannot stand in for it (397
questions missing, 80 corrected answers, 124 reworded questions), so a score comparable with
the Diamond leaderboard needs its own Benchmark. This unit adds `hle_diamond` as a local Task
that reuses inspect_evals' hle prompt and judge over the Diamond dataset. `hle` does not change.

Owner decisions (2026-11-16): the dataset card's "do not re-share" ask is accepted as for
`hle`; the Benchmark publishes the overall score and the stated confidence only, no per-half
scores.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/hle_diamond/`
  (`__init__.py`, `hle_diamond.py`, `README.md`) — the local Task.
- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py` — the generated
  Case Preparation entry.
- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py` — the catalogue
  row, filled by hand from `hle`'s.
- `apps/screamingface-engine/tests/unit/inspect/test_local_task_hle_diamond.py` — the Task's
  own contract (dataset pin, ids, metadata, prompt and scorer are inspect_evals').
- `apps/screamingface-engine/tests/unit/inspect/test_hle_diamond_cases.py` — parity: the
  Candidate and the judge read what the Task hands them.
- Shared tables the importer and the row machinery need (fingerprint literal, stand-in
  metadata).
- `docs/benchmarks-fidelity/` — the Fidelity Record.
- `docs/tasks/OME-1863-*.md` — the mirror, closed at PR-open.

## Test plan

- Task contract: the loader reads `cais/hle-diamond` at the pinned commit; a row becomes the
  Sample inspect_evals' `record_to_sample` builds, plus the added `partition` metadata; the
  solver, scorer, generation settings and epoch reducer equal inspect_evals' hle Task's.
- Parity: one text row and one picture row through the real Task, capture and scorer adapter;
  the Candidate sees the system prompt + question (+ picture bytes), the judge's prompt is
  inspect's byte for byte.
- Row: registration, fingerprint and the extra-less catalogue lanes pass with the new row.

## Acceptance

- `hle_diamond` registers with 1,000 Cases from `cais/hle-diamond@04eeb7ef`, Case Digest
  sealed, judge glm-5.3-flash, `failure_policy="withhold"`.
- `hle`'s row, Case Digest and published revision are unchanged.
- Touched tests, ruff and pyright pass.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `importer.py` (one rule, below), `test_benchmark_declaration.py`
  (the fifth per-Benchmark table) and `.claude/test-change-approvals/OME-1863.json` (the five
  prior test tables that gain a row). No stand-in metadata entry: `regex_judge` reads none.
  Fidelity Record: `apps/screamingface-engine/docs/benchmarks-fidelity/hle_diamond.md`.
- **Commits:** `a7e78f15f` the Benchmark; `682644804` this outcome, the mirror and the
  frontier-score comment; `9e870b6e5` the Fidelity Record (`not-comparable`: the judge differs,
  as on `hle`; everything else measured matches); a last commit declares the record's two
  findings (the system prompt sent as user text on the row, both `OURS` lines in the README).
- **Gates:** relevant tests only (owner rule): the 2 new test files, the 5 edited tables, every
  catalogue-wide row sweep and every importer test, 1,747 passed; ruff clean; pyright on the
  touched files, extra-less as CI runs it, 0 errors. Mutation: dropping the `partition` line
  turns 4 tests red. `hle`'s fingerprint unchanged (`d30effc2a0698079`).
- **Deviations:**
  - The planned `hle_diamond_` Case-id prefix was dropped. The Engine numbers Cases 1..N per
    Benchmark and the Case Digest leaves inspect's Sample id out, so it protected nothing.
  - The importer refused a local Task whose scorer lives in inspect_evals (`_home_in_eval_package`);
    it now accepts that for local Tasks only. `test_a_scorer_from_another_evals_package_is_still_refused`
    still passes.
  - `hle`'s BibTeX moved into `_HLE_CITATION`, shared by both rows (same value, same fingerprint).
  - Frontier score is 74.3% (Claude Fable 5.2), the top no-tools row of the authors' table, not
    the ticket's 59.9% (GPT-6 Astra's row in the same table).
  - Added after review: the picture notebook (`18_picture_benchmarks`, via
    `scripts/build_notebooks.py`) runs `hle_diamond` too. Its first five Cases are text, so the
    cell names `cases=[1, 501]` (a reasoning text Case and a knowledge picture Case) instead of
    `limit=2`; `test_picture_benchmarks_notebook.py` gains the id (approval entry added).
- **Local smoke (2026-11-16, owner's run):** `hle_diamond` Cases 1-2 on the local stack with
  gemini-3-flash-preview: both scored 0 (answers 0 and 2 against 624 and 8), the glm-5.3-flash
  judge graded each in one try, confidence 85, coverage 1.0, $0.0027 Candidate cost. The picture
  Case (501) is not run yet.
