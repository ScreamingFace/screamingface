---
ticket: OME-1855
stack: screamingface-engine
status: done
started: 2026-11-09
finished: 2026-11-09
---

# import-zerobench — import ZeroBench's 100 main questions as a picture Benchmark at pass@1

## Intent

ZeroBench (Roberts et al., 2025) is 100 hand-written visual reasoning questions, each over one
or more pictures, built so that every frontier model scored 0% at release; the best pass@1 on
the official board today is 43.2. inspect_evals 0.20.0 ships it as
`inspect_evals.zerobench.zerobench:zerobench`, reading the gated Hub dataset
`jonathan-roberts1/zerobench` (split `zerobench`, 100 rows) at the eval's own pinned revision
`13c35e52`. The eval's own `zerobench_scorer` grades the LAST `{…}` in the reply by exact
match against the answer, so no judge is spent. Pictures in Cases work since OME-1271 and the
MathVista / MMMU imports proved the Pillow-thumbnail path, so this is one Task-replay
declaration plus one BenchmarkSpec row, sealed on linux/amd64. Onboarding only; the paid smoke
and any state-of-the-art run are the owner's.

Decisions already taken by the owner (dispatch, 2026-11-09): main set only
(`zerobench_subquestions` is out); import with `--task-arg k=1` because the task's default
`Epochs(5, [pass_at_1, pass_at_5, 5_of_5_reliability])` is refused by the importer (OME-1458),
so the Benchmark is one-sample pass@1 (plain accuracy over 100 Cases); `--shuffle-seed 20260917`
(the eval shuffles with no seed); tier `hard`; policy `withhold`; licence: the card states no
SPDX licence, the gate says "do not share answers publicly or use for training" with a canary,
so the licence field takes the repo's no-licence form (`unknown` / `NotPublished`) and the gate
terms go in the row comment and `license_note`; gold answers never appear in any artifact.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`, `.../benchmarks.py`
  — the two rows the importer writes (inside the linux/amd64 Engine image); prose, provenance,
  tier, baselines and licence by hand. Published revision from `scripts/benchmark_bump.py`.
- Per-Benchmark test tables, one row each: `test_benchmark_declaration.py` (withhold,
  single_shot, hard), `test_failure_policy_rows.py` (row counts 93→94, 76→77),
  `test_inspect_imported_benchmarks.py` (family free_text, seeded set), `test_published_revisions.py`,
  `test_benchmark_fingerprints.py`.
- New `tests/unit/inspect/test_zerobench_picture_cases.py`: stand-in rows through the real task,
  the real picture save and the real capture; the Case holds the question text plus the eval's
  instruction line and every picture in order; the scorer grades the last-braces answer.
- Picture notebook: `packages/screamingface/scripts/build_notebooks.py` (PICTURE_BENCHMARKS,
  SEALED_ON_LINUX, one `run_two_cases` cell), regenerated `examples/18_picture_benchmarks.ipynb`,
  `tests/test_picture_benchmarks_notebook.py` (nine ids), the README's notebook line.
- `.claude/test-change-approvals/OME-N.json` for the prior-test edits, once the ticket exists.
- `docs/tasks/` mirror at PR-open.

## Test plan

- RED first: the five table rows for `zerobench`, failing until the importer writes the rows.
- The new picture-Cases test, failing on two mutants (instruction line removed; pictures swapped).
- Outside judge (scratch, inside the Linux image): inspect's own `eval()` with the free
  `mockllm/model` over all 100 Samples; each sent message (text, pictures, bytes, media type)
  matches exactly one Case and its target equals that Case's Grading Material; a negative control
  with one flipped picture byte leaves exactly one Sample unmatched.
- The importer's second replay reproduces the Case Digest; a Mac prepare is expected to differ
  (Pillow PNG bytes), as for MathVista and MMMU.
- Size check: pictures per Case, largest Case bytes against the importer's 8 MB and the gateway's
  frozen-copy entry cap (10 MiB since OME-1756: the 8 MiB request cap plus 2 MiB of response
  headroom), `cases.json` size, peak resident memory on read+parse against the 2,560 MiB
  per-run budget (a run reads only the selected Cases since OME-1790, so this is an upper bound).

## Acceptance

- `inspect-zerobench` registered, 100 Cases, every picture inline, Case Digest sealed on
  linux/amd64, `needs_hf_token=True`, no TODO left, no check surface, `attempts` = 1.
- No existing Benchmark's id or revision moves.
- Tests named in the dispatch green with and without the inspect extra; ruff, ruff format and
  pyright clean on every touched Python file; the notebook check and its test green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `prepare.py` and `benchmarks.py` (the `zerobench` rows), the five test
  tables, new `tests/unit/inspect/test_zerobench_picture_cases.py`; in `packages/screamingface`:
  `scripts/build_notebooks.py`, the regenerated `examples/18_picture_benchmarks.ipynb`,
  `tests/test_picture_benchmarks_notebook.py` (nine ids, `_ALL_NINE`) and the README's notebook
  line; `.claude/test-change-approvals/OME-1855.json`;
  `docs/tasks/2026-11-09-OME-1855-import-zerobench.md`. No importer or engine change.
- **Commits:** one, `feat(screamingface-engine): import ZeroBench's main questions at pass@1
  with their pictures`.
- **Import (real Hub data at `jonathan-roberts1/zerobench` `13c35e52`, inspect_evals' own pin,
  inside the linux/amd64 Engine image built from this branch; OrbStack, Rosetta):**
  `--task-arg k=1 --shuffle-seed 20260917`. 100 Cases, Case Digest `7b1b680a…`, case-set
  digest `4f5c4adb…`, `needs_hf_token=True` and `keep_sample_metadata=True` written by the
  importer (the Hub says gated, auto; the scorer is the eval's own). The build path
  (`screamingface_engine.benchmarks.prepare --bundle inspect-zerobench`) in the same image
  reproduced the count and the digest in 35 s. At k=1 the task logs "Maximum value in top_n (5)
  must be less than or equal to k (1). Defaulting to top_n={1, k}" and builds
  `Epochs(1, ["pass_at_1"])`, which the importer takes as one Attempt. Published revision
  `b0afce4bf40156bf` from `benchmark_bump.py`. The eval names every picture file `.png` but
  saves the bytes in the picture's own format, so 101 of the 108 pictures are JPEG bytes under a
  `.png` name; the Case labels each picture by its bytes (`image/jpeg`), as `picture_input.py`
  does for FigQA. No Mac seal was made.
- **Size check (the Linux bundle):** 108 pictures over 100 Cases, 1 to 3 per Case (cap 20);
  101 JPEG, 7 PNG; largest picture 1,078,950 bytes. Largest Case 2,487,332 bytes, median
  132,154; none over the importer's 8 MB, and none over the gateway's 10 MiB frozen-copy entry
  cap (OME-1756 sized it from the 8 MiB request cap; the first draft of this ledger cited the
  old 2,000,000-byte cap, under which this one Case would not have been frozen). `cases.json` 18.5 MB, read and parsed at 92.5 MiB
  resident (budget 2,560 MiB), measured inside the Linux image.
- **Byte check (outside judge), inside the Linux image against the Linux bundle:** inspect's own
  `eval()` of the zerobench Task with k=1 and the free `mockllm/model` over all 100 Samples:
  each Sample's user message (the text, then every picture's bytes, in order) matched exactly
  one Case, and its target and metadata (`question_images`, `image_attribution`) equal that
  Case's Grading Material, 100 of 100. Media-type labels audited separately: all 108 Case labels
  equal the bytes' real type; inspect labels 101 JPEG pictures `image/png` from the file name.
  Negative control: one flipped byte in the largest Case's first picture left exactly that one
  Sample unmatched.
- **Gates:** `tests/unit/inspect/` with the inspect extra, 2,957 passed, 0 failed (the four
  display-metadata / protocol failures earlier ledgers named did not appear on this main); the
  five tables plus the new file, 786 passed with the extra; extra-less lane (the five tables, the
  new file, `test_span_export_wiring.py`, `test_cli.py`): 34 passed, 8 skipped. The new test
  fails on both mutants (the instruction line dropped; the pictures reversed). ruff, ruff format
  and pyright (extra-less) clean on the 8 touched Engine files and the 2 package files;
  `check_notebooks.py` exit 0; the notebook test 4 passed.
- **Deviations:** licence: the card and the project page state no licence, so the rows take the
  repo's no-licence form (`unknown` in prepare.py, `NotPublished` plus a `license_note` on the
  card) with the gate terms in the comments; the dispatch pointed at HLE's approach, but HLE's
  card says MIT, so only its comment style could be copied, not its value. The leaf is filed in
  the project the epic and its sibling OME-1733 sit in (😱 ScreamingFace Q4), not the card's V1.
  The byte check matches content; the media-type labels differ by design (above). The frontier
  score's `as_of` is the read month, since the board dates no entry.
- **Owner-verify:** the paid smoke (two Cases from the picture notebook, or `limit=2`) and CI's
  "Build the deployable images" are the only proofs of the Linux seal in the deployment; confirm
  the tier (`hard`) and the licence footing.

## 2026-11-09, second pass — re-import at inspect's five Attempts with the mean fold

### Intent

PR #1709 (OME-1856, branch `OME-1856-attempts-mean-fold`) taught the importer and the Engine a
second fold rule: a Task whose FIRST declared reducer is inspect's own `pass_at(1)` over N
epochs imports as `attempts=N, epoch_reducer="pass_at_1"`, and the marking room scores each
Case as the share of its graded Attempts at full marks, inspect's `pass_at(1)` exactly
(`docs/spec/2026-11-09-attempts-mean-fold.md`). ZeroBench is the Benchmark that needed it, so
this pass replaces the k=1 row with inspect's defaults: each question asked 5 times, Benchmark
score = mean over the Cases run of each Case's mean over 5 Attempts. That is the number
inspect_evals publishes as pass@1 and the number the official board's five-sample pass@1
column holds, so the frontier score 0.432 becomes like-for-like. The branch merges
`upstream/OME-1856-attempts-mean-fold` (no rebase) and the PR retargets to that branch until
#1709 merges. Owner decisions (dispatch, 2026-11-09): inspect's defaults (no `k` argument);
inspect-comparable over paper-comparable (inspect's 1024 px thumbnails: 3 of the 100 questions
carry 9 to 25 MB pictures, over the 8 MB Case cap); pass@5 and 5-of-5 reliability stay
unpublished and are named as dropped; the catalogue says "mean over 5 Attempts", never a bare
"pass@1"; the sub-question count is stated as 334 by the dataset card (inspect_evals' eval.yaml
says 335); no gold answer anywhere.

### Planned changes

- `prepare.py` zerobench row: `task_args` gone (inspect's defaults), the k=1 paragraph replaced,
  `# NAMED DEVIATION` lines for the dropped reducers and for the picture media-type label (the
  Case labels by the bytes, inspect by the `.png` file name; 108 of 108 bytes identical); the
  1024 px thumbnail noted as inspect_evals' own construction and the comparability-to-paper gap.
  Case Digest expected unchanged (`7b1b680a…`: same Cases, same pictures), to be confirmed.
- `benchmarks.py` zerobench card: `attempts=5`, `epoch_reducer="pass_at_1"`, the description
  rewritten for the mean rule, the frontier comment no longer "NOT like-for-like", one paragraph
  on why this Benchmark is comparable to inspect_evals rather than to the paper; the published
  revision moves (`task_args` and `attempts` are pinned), recomputed with `benchmark_bump.py`.
- The five row tables: the new revision literal; `test_zerobench_picture_cases.py` adjusted if
  the capture now sees epochs=5; `.claude/test-change-approvals/OME-1855.json` re-pinned.
- SDK: search for a user-facing "any of N Attempts" phrase tied to the catalogue's `attempts`;
  if one exists, STOP and report (no wire field in this unit).
- Picture notebook: the ZeroBench markdown cell (5 Attempts, 5× cost, mean over Attempts),
  `18_picture_benchmarks.ipynb` regenerated.
- Mirror, ticket OME-1855 (blocked by OME-1856), PR #1706 body and base.

### Test plan

- Re-import inside the linux/amd64 Engine image built from this branch (merged with #1709):
  expect `attempts=5`, `epoch_reducer="pass_at_1"`, `pass_at_5` and `5_of_5_reliability`
  dropped, 100 Cases, Case Digest `7b1b680a…`; the build path reproduces count and digest.
- Byte check repeated inside the image: inspect's own `eval()` with the free `mockllm/model`
  at the Task's defaults, all 100 Samples matched on text, pictures, bytes, media type, target;
  negative control.
- Tests (named): with the inspect extra, the five tables + `test_zerobench_picture_cases.py` +
  `test_attempts_mean_fold.py` + `test_imported_attempts.py`, then the whole
  `tests/unit/inspect/` lane once; extra-less: the five tables + the picture test +
  `test_span_export_wiring.py` + `test_cli.py`; ruff, ruff format, pyright (extra-less) on the
  touched files; `check_notebooks.py` and `test_picture_benchmarks_notebook.py` with the
  notebook extra. The picture test still fails on its two mutants.

### Outcome (second pass)

- **Branch:** merged `upstream/OME-1856-attempts-mean-fold` (e361aacdd) into this branch, no
  conflicts, no rebase; PR #1706 retargeted to that branch so its diff shows only ZeroBench,
  back to `main` once #1709 merges.
- **Import (inside the linux/amd64 Engine image built from this merged branch; OrbStack,
  Rosetta; the owner's cached Hub login):** `python -m screamingface_engine_inspect.importer
  inspect_evals.zerobench.zerobench:zerobench --key zerobench --shuffle-seed 20260917`, no `k`
  argument, written to a scratch copy of the two files (the importer refuses a key that already
  exists) and merged into the rows by hand. The importer accepted the Task: `attempts=5`,
  `epoch_reducer="pass_at_1"`, `pass_at_5` and `5_of_5_reliability` named as not reproduced in
  the generated comment; 100 Cases; Case Digest `7b1b680accca5198fdfc490483805dd621927fe31e01305ca5505186129ee060`
  and case-set digest `4f5c4adb…`, both unchanged from the k=1 import (same Cases, same
  pictures). The build path (`screamingface_engine.benchmarks.prepare --bundle
  inspect-zerobench`) in the same image with the new rows mounted reproduced 100 Cases and the
  digest in 34.4 s. Published revision `9155d9581e103c0a` from `benchmark_bump.py` (was
  `b0afce4bf40156bf`, never merged or published, so no CHANGELOG line and no leaderboard
  result moves).
- **Byte check (outside judge), inside the Linux image against the new bundle:** inspect's
  own `eval()` of the zerobench Task AT ITS DEFAULTS (epochs=5) with the free `mockllm/model`:
  500 sample records (100 Samples × epochs 1 to 5); every record matched exactly one Case on
  the text, the pictures' bytes and their order, and every Case was matched exactly 5 times;
  target and metadata (`question_images`, `image_attribution`) equal the Case's Grading
  Material on 500 of 500. Picture labels: all 108 Case labels equal the bytes' real type;
  inspect labels the 101 JPEG pictures `image/png` from the file name (505 records). Negative
  control: one flipped byte in the largest Case's first picture left exactly 5 records (one
  per epoch) unmatched.
- **Size check (the Linux bundle), unchanged:** 108 pictures over 100 Cases (1 to 3 each), 101
  JPEG and 7 PNG; largest picture 1,078,950 bytes; largest Case 2,487,332 bytes, median
  132,154; none over the importer's 8 MB cap, none over the gateway's 10 MiB frozen-copy entry
  cap (OME-1756); `cases.json` 18.5 MB, read and parsed at 92.5 MiB resident.
- **Sub-question count:** the dataset card and README say 334, inspect_evals' eval.yaml says
  335; the card states "334 by the dataset card (inspect_evals' eval.yaml says 335)". Not
  imported either way.
- **Card and row:** description rewritten for the mean rule ("Benchmark score = mean over the
  cases run of each Case's mean over 5 Attempts, an Attempt counting as right only on an exact
  match"), like-for-like with inspect_evals' pass@1 and the board's five-sample column, the
  frontier comment no longer "NOT like-for-like", "imposes no generation settings" kept with
  the default-settings and temperature-0 notes, and one passage on why the Benchmark is
  comparable to inspect_evals rather than to the paper (full resolution unreachable: 3 of 100
  questions carry 9 to 25 MB pictures, over the 8 MB Case cap and Anthropic's 5 MB image
  limit; inspect's 1024 px pictures are what every inspect user runs; the paper's greedy pass@1
  is a temperature the Candidate owns). The Cases row drops `task_args`, replaces the k=1
  paragraph, and carries two `# NAMED DEVIATION` lines (the reducers not reproduced; the
  picture media type from the bytes where inspect labels by the `.png` name, bytes identical on
  108 of 108). The 1024 px thumbnail is noted as inspect_evals' own construction, the gap to
  the paper, not a deviation from inspect.
- **Engine fix the first mean row exposed:** `test_whole_run_metric.py::
  test_no_published_row_opts_in_so_no_revision_moves` (prior, OME-1527) asserts that a row
  with no whole-run metric pins nothing under `_whole_run_metric_pins`; OME-1856 left the
  `epoch_reducer` pin in that helper for every row, so the first `pass_at_1` row failed it.
  Fixed in `benchmarks.py`, not in the test: `_whole_run_metric_pins` pins the reducer only
  beside a whole-run metric, and `_attempts_pins` pins it on a row with no metric (the mean
  rule is Attempts identity, spec D17). ARC-AGI-2's pin tuple is unchanged
  (`test_benchmark_fingerprints` green) and zerobench's fingerprint is the same
  `9155d9581e103c0a` before and after the move (`benchmark_bump.py`: "nothing to bump").
  Pinned in the new `test_zerobench_asks_each_case_five_times_and_folds_them_by_the_mean`.
- **SDK wording (STOP finding, reported, nothing changed):** the SDK has a user-facing phrase
  tied to the catalogue's `attempts`: `_ui/cards.py` `attempts_meaning` and
  `attempts_chip_html` render "any of N Attempts · N Candidate Invocations per Case" for every
  Benchmark with `attempts > 1`, and `_ui/report_view.py` (line 995) says "any of N Attempts"
  in the Case Result pane header. For ZeroBench those read the wrong fold. The catalogue entry
  carries no fold rule, so the fix is a wire field (OME-1856's own known limitation); not added
  in this unit, reported for the owner's decision.
- **Tests:** with the inspect extra, the five tables + `test_zerobench_picture_cases.py` +
  `test_attempts_mean_fold.py` + `test_imported_attempts.py` + `test_whole_run_metric.py`:
  848 passed; the whole `tests/unit/inspect/` lane: 2,976 passed, 0 failed (the first run,
  before the pin fix, had the 1 failure above). Extra-less: the five tables + the picture test
  + `test_span_export_wiring.py` + `test_cli.py`: 34 passed, 8 skipped. ruff, ruff format and
  pyright (extra-less) clean on the 5 touched Engine files and `build_notebooks.py`;
  `check_notebooks.py` exit 0; `test_picture_benchmarks_notebook.py` 4 passed. The picture
  test still fails on both mutants (instruction line dropped: 1 failed, 7 passed; pictures
  reversed: 1 failed, 7 passed).
- **Records:** `.claude/test-change-approvals/OME-1855.json` re-pinned (new blobs for the two
  revision tables); mirror updated; the ticket's TLDR, Before / After, Data Flow, Architecture
  and limitations rewritten for the five-Attempt rule, blocked by OME-1856.
- **Deviations (second pass):** (1) the `_attempts_pins` / `_whole_run_metric_pins` fix above
  is an Engine change outside "rows only"; the owner may prefer it on #1709's branch. (2) The
  known-limitations block carries four bullets, not three: the SDK phrase is a limitation of
  this PR a reviewer would otherwise file. (3) The ticket title loses "at pass@1" (the card's
  rule says never a bare pass@1). (4) The fidelity record named in the dispatch
  (`.claude/worktrees/audit-zerobench/.../inspect-zerobench.md`) does not exist on this
  machine; D3 (the media-type label) was taken from the dispatch text, the other deviations
  are those this ledger records.
- **Owner-verify:** the SDK phrase decision (a wire field for the fold rule, a new unit under
  OME-1458 / OME-1299); #1709's merge, then retarget #1706 to `main`; CI's "Build the
  deployable images" on this head (the only deployment proof of the Linux seal); the paid smoke
  of two Cases (ten Candidate calls).
