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
  2,000,000-byte frozen-copy cap, `cases.json` size, peak resident memory on read+parse against
  the 2,560 MiB per-run budget.

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
  132,154; none over the importer's 8 MB; ONE Case over the gateway's 2,000,000-byte frozen-copy
  entry cap, so a captured run cannot freeze that one call (the capture says `failed`, the run
  goes on), as 17 of MMMU's Cases did. `cases.json` 18.5 MB, read and parsed at 92.5 MiB
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
