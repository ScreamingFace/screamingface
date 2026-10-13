---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-13
finished: 2026-10-13
---

# nltk-data-at-image-build — prepare a local Task's nltk data at image build

## Intent

OME-1527 Work order #11 (requirement R8, PR 11 of 20). ifeval's checker tokenizes with nltk
(`punkt`, `punkt_tab`), and the grading job has no network. The hand-built ifeval already
downloads the corpus at image build; the plugin lane prepares only `cases.json` and
`targets/`, so ifeval could not move to a local Task (Work order #15). This unit lets a Case
Preparation row name the nltk resources its scorer reads: the image build downloads them into
the bundle, a pinned digest seals them into the Benchmark Revision, and the installer points
nltk at the bundle so grading reads it offline.

## Planned changes

- `screamingface_engine/benchmarks/nltk_data.py` (new): the shared download, offline reader
  and digest; the hand-built ifeval's `prepare_nltk` and `grading.configure_nltk` delegate to it.
- `screamingface_engine_inspect/prepare.py`: `TaskReplayCasesSpec.nltk_resources` and
  `nltk_data_digest`.
- `screamingface_engine_inspect/task_replay.py`: Case Preparation downloads and checks the
  seal before `cases.json`; a failure or a different seal skips the board by name.
- `screamingface_engine_inspect/benchmarks.py`: the two revision pins (only when set) and the
  installer pointing nltk at `<bundle>/nltk_data`.
- `screamingface_engine_inspect/importer.py`, `task_replay_rows.py`: `--nltk-resource`, which
  downloads once at import and writes the names and the seal on the row.

## Test plan

- New `tests/unit/inspect/test_nltk_data_at_image_build.py` over a stand-in row (gsm8k's
  BenchmarkSpec, a canned one-Case replay, a fixture-writing `nltk.download`): no pin when
  unset; names + seal move the revision; half a declaration refused; corpus written before
  `cases.json`; a different seal or a failed download skips by name; grading finds the
  resource in the bundle with sockets and the downloader disabled; the importer seals.
- Appended to `test_task_replay_rows.py`: the row round-trips the two fields; absent stays absent.
- Unchanged and passing: `test_published_revisions.py` (no published revision moves),
  `test_ifeval_prepare.py` (the hand-built ifeval still authorizes before downloading).

## Acceptance

- A row declaring `nltk_resources` + `nltk_data_digest` prepares `<bundle>/nltk_data/` at
  image build and grades with nltk reading it offline.
- No published revision moves; the hand-built ifeval prepares and grades as before.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the two appended row tests.
- **Commits:** see the PR (feat(screamingface-engine): prepare a local Task's nltk data at
  image build).
- **Gates:** relevant tests only, with the inspect extra: the new suite (11),
  `test_task_replay_rows.py`, `test_published_revisions.py`, `test_judged_benchmark_assembly.py`,
  `test_task_replay_assembly.py`, `test_import_replay.py`, `test_importer_command.py`,
  `test_list_target.py`, `test_ifeval_prepare.py` (206 passed); in a clean extra-less venv the
  inspect suites skip and `test_ifeval_prepare.py` passes. ruff check + format clean; pyright
  (extra-less and with the extra) 0 errors on touched files; append-only check vs
  upstream/main passes (no pre-existing test edited, no approval entry needed). Full suite left
  to the pre-push hook and CI.
- **Deviations:** none. Mutation-checked: disabling the installer's nltk pointing, or the
  prepare step, fails the suite (the first run of the offline test passed with the pointing
  disabled because the build's download had registered the folder in the same process; the
  test now resets nltk's path between build and grading).
- **Review fix:** a failed download or seal now removes `nltk_data/` so a SKIPPED bundle ships
  no unsealed bytes, and the installer points nltk only at a finished bundle (`cases.json`
  present), raising `NltkDataMissingError` when that bundle has no corpus folder; 3 tests
  appended, each mutation-checked.
- **Owner-verify:** nothing to press for this PR alone. No row declares the field yet; the
  first real download and seal happen when ifeval's local Task is imported (Work order #15)
  with `--nltk-resource punkt --nltk-resource punkt_tab`, and the next image build after that
  merge proves the nltk index still serves those bytes.
