---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-12
finished: 2026-10-12
---

# contracteval-local-task — serve ContractEval as a local inspect Task, delete its folder

## Intent

OME-1527 Work order #7 (PR 7 of 20). ContractEval lived in a nine-file hand-built folder
(`benchmarks/contracteval/`) that only the hand-built serving spine could serve. With the
whole-run metric (R1, #1325) and the empty answer key (R5, #1353) in the plugin lane, it moves
to a local Task under `screamingface_engine_inspect/local_tasks/contracteval/`, fed to the same
importer as inspect_evals, keeping its id `contracteval`. The three things that must stay the
paper's: prompt bytes, grading rule, headline score.

## Planned changes

- `local_tasks/contracteval/{__init__,grading,contracteval}.py` + `README.md`: the loader
  (`hf_dataset` at the pinned parquet commit), the scorer, the whole-run `contracteval_f1`
  metric, the `@task`; `grading.py` is the hand-built `grading.py` moved verbatim plus the
  hand-built reducer's F1 formula.
- `benchmarks.py` / `prepare.py`: the two importer-generated rows, provenance carried over from
  the hand-built definition, `origin="screamingface"`, `notebook="13_contracteval"`.
- Delete `benchmarks/contracteval/` (9 files) and its 9 test files; port the parity test.
- `builtins.py`: drop the registration; `contract.py` + SDK `_report_primitives.py`: retire
  `contracteval_grading_failed` and `polarity_mismatch` (no emitter left).
- SDK `_runtime/cli.py`: drop contracteval from the hand-built prepare list (like musique).
- SDK notebook 13: setup and metric cells follow what the lane serves.
- Shared tests that named the folder: stage parity, early-score timing, case positions,
  failure classes, the early-grade fixture, declaration table, family table, revision literal,
  the whole-run opt-in guard.

## Test plan

- `tests/unit/inspect/test_local_task_contracteval.py` (new): conservation literals (eight
  canned replies graded as the hand-built checker graded them; run F1 0.6667 = hand-built,
  mean would be 0.625; always-declining 0.0), prompt-bytes literal, `[]` and one-span keys
  through Case Preparation, the re-blessed golden's verdict facts, the row.
- `tests/unit/test_contracteval_parity.py`: same reference functions, new module.

## Acceptance

- Prompt bytes of all 4,182 Cases equal the hand-built bundle's (checked at import).
- The headline equals the hand-built F1 on canned replies, pinned as a literal.
- No `benchmarks/contracteval/` folder; no code emits the retired failure codes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `test_inspect_task_replay_benchmarks.py` /
  `test_imported_catalogue_activity.py` run unchanged (contracteval joins both no-network lanes
  by enumeration), `tests/e2e/test_boards.py` (SDK; contracteval leaves the hand-built replay
  tuple), `docs/adding-a-benchmark-manually.md` (one stale example), and
  `.claude/test-change-approvals/OME-1527.json`.
- **Import:** `importer …contracteval:contracteval --key contracteval --empty-answer-key-allowed
  --whole-run-metric honour` (HF_HUB_DISABLE_XET=1): 4,182 Cases, Case Digest `55a3c9b1…`,
  Case Source `theatticusproject/cuad-qa` @ `d9c4ee02` (the hand-built pin). Every TODO(review)
  resolved from the hand-built definition: title/description/focus, difficulty `medium`,
  paper/authors/citation/harness, licence CC-BY-4.0 (CUAD; harness MIT), human baseline
  NotPublished, Frontier Score 0.644 GPT 4.1 mini, notebook `13_contracteval`, whole-run metric
  reviewed (F1 in 0..1, higher is better).
- **Prompt bytes:** both bundles prepared from the real dataset and compared Case by Case:
  0 of 4,182 inputs differ, 0 answer keys differ (2,938 `[]`, 762 one-span lists).
- **Revision:** `f9a076a10a6ae4c6` (hand-built) → `04cde6eac3938ddf` (local Task). The free
  unit golden (`test_contracteval_migration_golden.py`) is deleted with its routes: what moved
  is the revision (now hashed from the Case Digest, Task reference, Hub pin, whole-run metric
  and the Task's `.py` source), the route prefix (the plugin's shared routes), and the check
  record (the plugin's `inspect_scorer` Check replaces `contracteval-check.v1`). The golden
  reply's verdict facts (correct, clause Case, not declined, Jaccard 0.7) are re-pinned in the
  new test.
- **Numbers carried / dropped:** headline F1 carried exactly; `correct` and `scored_cases`
  carried (their ratio is the old accuracy); per-Case `is_positive` / `abstained` / `jaccard`
  carried as Check evidence. Dropped (the lane publishes one whole-run number and refuses a
  dict): precision, recall, F2, the four confusion-matrix counts, `no_related_clause_rate`,
  `false_no_related_clause_rate` (laziness), `jaccard_mean`. Also gone: the hand-built running
  F1 snapshot mid-run (the plugin lane has no early score).
- **Commits:** see the PR.
- **Gates:** relevant files only (listed in the PR); ruff + format clean; extra-less pyright 0
  errors on touched files. Full gate = pre-push hook + CI.
- **Deviations:** `polarity_mismatch` retired beside `contracteval_grading_failed` (both lost
  their only emitter); the hand-built context-size tripwire and the advisory sampling constants
  were not ported (the Case Digest seals every context; the notebook carries its own params).
  The local `screamingface up` Engine (no inspect extra) no longer lists contracteval; deployed
  Engines carry the extra.
- **Owner-verify:** one paid contracteval run after merge (the Engine with the inspect extra),
  its F1 read beside the paper's 0.644 (GPT 4.1 mini); and the SDK notebook 13 opened against
  `just local-stack-notebooks` once.
