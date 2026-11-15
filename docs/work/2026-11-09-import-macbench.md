---
ticket: OME-1854
stack: screamingface-engine
status: done
started: 2026-11-09
finished: 2026-11-09
---

# import-macbench — import MaCBench (chemistry and materials picture questions) as a Benchmark

## Intent

MaCBench is 1,153 chemistry and materials science questions in 34 subsets, every one a
picture (an AFM image, a hand-drawn molecule, a crystal structure, an adsorption isotherm, a
spectrum, a patent plot, a lab photo) with a question about it. inspect_evals 0.20.0 ships it
as the task `macbench` (one user message, the eval's own answer-tag scorer, no judge). Pictures
in Cases work since OME-1271 and MMMU, MathVista, HLE and LABBench2 proved the path, so
MaCBench becomes one Task-replay Benchmark, `inspect-macbench`, under the vision epic
OME-1330. Onboarding only: no paid run.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`, `.../benchmarks.py`
  — the importer's `macbench` rows (`--shuffle-seed 20260917 --letter-list-key
  --whole-run-metric mean`), then the prose, tier, provenance and baselines by hand.
- `apps/screamingface-engine/src/screamingface_engine_inspect/named_deviations/macbench/macbench.py`
  — only if the eval's own scorer mis-grades a right multi-letter reply written in another
  order or spacing (the chembench 0.20.0 bug): letters graded as a set, numbers untouched.
- The per-Benchmark test tables, one row each: `test_benchmark_declaration.py`,
  `test_failure_policy_rows.py` (and its row counts), `test_inspect_imported_benchmarks.py`,
  `test_published_revisions.py`, `test_benchmark_fingerprints.py`.
- New `tests/unit/inspect/test_macbench_picture_cases.py` (stand-in rows through the real
  task and capture) and, with the deviation, `test_named_deviation_macbench.py` (tripwire).
- `packages/screamingface/scripts/build_notebooks.py` (PICTURE_BENCHMARKS + one cell),
  regenerated `examples/18_picture_benchmarks.ipynb`, `tests/test_picture_benchmarks_notebook.py`,
  the README's notebook line.
- `.claude/test-change-approvals/OME-N.json` for the prior-test edits; `docs/tasks/` mirror.

## Test plan

- Free probe first: the eval's own `macbench_scorer` over a stand-in reply `[ANSWER]C, A[/ANSWER]`
  against `A,C` (decides whether the deviation exists).
- RED: the five table rows fail until the rows exist; the picture-cases test fails until the
  rows exist; the tripwire asserts v0.20.0's wrong verdict and ours.
- Size check (the MMMU method): pictures per Case vs 20, largest Case vs 8 MB and the
  gateway's 10 MiB frozen-copy entry cap (OME-1756), `cases.json` size, peak resident memory on read
  and parse vs 2,560 MiB; numeric vs multiple-choice counts; licence from the card.
- Byte check (outside judge, the MathVista method): inspect's own `eval()` with the free
  `mockllm/model` over all 1,153 Samples; each sent message matched to exactly one Case and
  its target and metadata to that Case's Grading Material; negative control with one flipped
  byte.
- Mutants: the new test fails when the picture is moved and when the tolerance is ignored.

## Acceptance

- `inspect-macbench` registered, 1,153 Cases, every picture inline, no TODO left, licence from
  the card (`mit`), no check surface, tier `medium`, policy `withhold`.
- No existing Benchmark's id or revision moves.
- The named test lanes, ruff, ruff format and pyright green on the touched files; the picture
  notebook rebuilt and its test green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `prepare.py` and `benchmarks.py` (the `macbench` rows), new
  `named_deviations/macbench/{__init__,macbench}.py`, the five test tables,
  `replayed_cases_helpers.py` (one stand-in metadata entry: the scorer reads `task_type`),
  `test_scorer_source_pins.py` (`_DEVIATING_ROWS` gains `macbench`, as each deviation PR of
  OME-1701 did), new `test_macbench_picture_cases.py` and `test_named_deviation_macbench.py`,
  `packages/screamingface/scripts/build_notebooks.py`, the regenerated
  `examples/18_picture_benchmarks.ipynb`, `tests/test_picture_benchmarks_notebook.py`
  (`_ALL_EIGHT` → `_ALL_NINE`), the README's notebook line,
  `.claude/test-change-approvals/OME-1854.json`, `docs/tasks/2026-11-09-OME-1854-import-macbench.md`.
  No importer or engine-core change.
- **Commits:** one, `feat(screamingface-engine): import MaCBench with its pictures`.
- **Import (real Hub data at `jablonkagroup/MaCBench` `ca13e7af`, the eval's own pin, not
  gated):** `--shuffle-seed 20260917` (the eval shuffles each of its 34 subsets with no seed),
  `--letter-list-key` (comma-joined multi-letter keys), `--whole-run-metric mean`. 1,153 Cases,
  Case Digest `d265b015…`, case-set digest `b1a05539…`, `keep_sample_metadata=True` written by
  the importer (eval-owned scorer). Sealed on the laptop: the eval wraps each row's own `data:`
  URI in a `ContentImage` and opens no picture, so no Pillow re-save and no platform split; the
  build path's `prepare_replayed_cases` on the same bundle reproduced count and digest (151 s,
  1,492 MiB peak). Published revision `a8d8e6ccc379924f` from `benchmark_bump.py` (moved from `f6cb6e028f58c0f2` on 2026-11-09 when the deviation header gained the upstream comment link; never published; the
  fingerprint on the day the row was added; `c1b519147b8b2bdc` before the deviation's header
  gained the Case counts, never published).
- **Size check:** one picture per Case (cap 20), all PNG. Largest Case 1,692,138 bytes (Case
  98), median 78,653; none over the importer's 8 MB nor the gateway's 10 MiB (OME-1756) frozen-copy
  cap. `cases.json` 196 MB; read and parsed at 598 MiB resident (budget 2,560 MiB). 779
  multiple-choice Cases (19 with several right letters), 374 numeric (146 carry the dataset's
  precomputed window, read as absolute; 228 fall back to 1% relative). Licence on the card: MIT,
  with an evaluation-only notice and a canary string in every row.
- **Multi-letter grading (checked with the eval's own scorer, free):** against the key `A,C`,
  `[ANSWER]A,C[/ANSWER]` and `[ANSWER]a,c[/ANSWER]` score right; `C, A`, `A, C`, `A C` and `C,A`
  score 0. Numbers grade inside their window (1.505 vs 1.5 at 1% right, 1.6 wrong; 1.04 vs 1.0
  at an absolute 0.05 right, 1.06 wrong). So the chembench deviation is mirrored:
  `named_deviations/macbench/macbench.py`, PR #2591's `multiple_choice_letters` verbatim inside
  v0.20.0's own `macbench_scorer` shape; the row's `scorer=` points at it; the tripwire asserts
  v0.20.0's wrong verdict and ours.
- **Byte check (outside judge):** inspect's own `eval()` of inspect_evals' `macbench` Task with
  the free `mockllm/model` over all 1,153 Samples (log read back with attachments resolved):
  every sent message (text parts, picture bytes, media type, order) matched exactly one Case,
  and its target, choices and metadata equal that Case's Grading Material (779 mcq, 374 mae).
  Negative control: one flipped byte in the largest Case's picture left exactly that Sample
  unmatched.
- **Gates (the named lanes):** `tests/unit/inspect/` with the inspect extra: 2,972 passed
  (2,971 + the scorer-source-pins test after its set gained `macbench`; the 4 known
  display-metadata/protocol failures did not appear, those files live under `tests/unit/` and
  pass extra-less). Extra-less: the five tables, the two new files, `test_benchmark_display_metadata.py`,
  `test_benchmark_protocol.py`, `test_span_export_wiring.py`, `test_cli.py`: 61 passed, 9 skipped.
  New tests: 22 passed with the extra; the picture test fails on three mutants (pictures moved
  after the text: 1 failed; Sample metadata not kept: 3 failed; the scorer ignoring the Case's
  window: 1 failed). ruff, ruff format and pyright (with and without the extra) clean on the 12
  touched Engine files; ruff, ruff format and pyright clean on the client package's two files;
  `check_notebooks.py` clean; `test_picture_benchmarks_notebook.py` 4 passed.
- **Deviations:** (1) a prior test outside the five tables and the notebook test changed:
  `test_scorer_source_pins.py`'s `_DEVIATING_ROWS` lists every row graded by our own scorer, so
  the Named Deviation the unit asked for adds `macbench` there (the same one-key edit each
  OME-1701 deviation PR made); recorded in the approval JSON, flagged for the owner on the PR.
  (2) The card names the project "😱 ScreamingFace V1"; Linear now shows the same project id as
  "😱 ScreamingFace Q4" (the epic and OME-1733 sit there), so the leaf was filed in it. (3) Frontier
  score `NotPublished` (the paper reports per-task averages; the leaderboard space is asleep;
  inspect_evals' gpt-5.2 0.726 grades letters as text); human baseline `NotPublished`.
- **Owner-verify:** the paid smoke on `inspect-macbench` after merge (two Cases from the picture
  notebook); confirm the tier and the `_DEVIATING_ROWS` edit on the PR.
