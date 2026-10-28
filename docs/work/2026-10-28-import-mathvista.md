---
ticket: OME-1479
stack: screamingface-engine
status: done
started: 2026-10-28
finished: 2026-10-28
---

# import-mathvista — import MathVista (testmini) from inspect_evals as a picture Benchmark

## Intent

MathVista is maths reasoning over pictures (charts, plots, geometry figures, puzzles): 1,000
testmini questions, 540 multiple choice and 460 free-form (418 integer, 20 float to one decimal,
20 float to two decimals, 2 lists). inspect_evals has it (`mathvista`, v0.20.0). Pictures in
Cases work since OME-1271, so the import is the LAB-Bench FigQA/TableQA pattern (OME-1327): one
Task-replay declaration plus one BenchmarkSpec row. Onboarding only; the paid and SOTA runs are
OME-1673.

The ticket's open question was the eval's custom solver. Reading inspect_evals' code: the solver
branches only on `question_type` (multiple choice → inspect's single-answer template over the
choices; free-form → a fixed "ANSWER: $ANSWER" template around the dataset's own `query` text,
which already carries the precision and unit hint). Task replay runs that solver for real and
records what it hands the model at `generate`, so no render rule of our own is written. The
scorer reads `state.metadata["question_type"]`; the importer keeps Sample metadata for every
non-inspect scorer, so that is kept too.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`, `.../benchmarks.py`
  — the two rows the importer writes; prose, provenance and baselines by hand.
- Per-Benchmark test tables, one row each: `test_benchmark_declaration.py`,
  `test_failure_policy_rows.py` (row counts), `test_inspect_imported_benchmarks.py` (family,
  seeded set), `test_published_revisions.py`, `test_benchmark_fingerprints.py`.
- A new test pinning the conserved prompt per answer type against inspect's own rendering.
- `.claude/test-change-approvals/OME-1479.json` for the prior-test edits.
- `docs/tasks/` mirror for OME-1479.

## Test plan

- RED first: the per-Benchmark tables gain the `mathvista` row before the import writes it.
- Outside judge (scratch, real rows): inspect's own `eval()` with the local mock model over all
  1,000 testmini rows; every Case's text parts and picture bytes equal what inspect sent the
  model, per answer type; kept metadata and target equal the Sample's.
- The importer's second replay reproduces the Case Digest.

## Acceptance

- `inspect-mathvista` registered, 1,000 Cases, every picture inline, under the 8 MB Case limit.
- Licence line in the diff, cleared by the owner.
- Relevant inspect-lane tests, ruff and pyright green on the touched files.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `prepare.py` and `benchmarks.py` (the `mathvista` rows), the five test
  tables, `tests/unit/inspect/replayed_cases_helpers.py` (one stand-in metadata entry, because
  the eval's scorer reads `question_type` and the shared grading lanes failed without it), new
  `tests/unit/inspect/test_mathvista_picture_cases.py`,
  `.claude/test-change-approvals/OME-1479.json`, `docs/tasks/2026-10-05-OME-1479-import-mathvista.md`.
  No importer or engine change.
- **Commits:** one, `feat(screamingface-engine): import MathVista's testmini set with its pictures`.
- **Import (real Hub data at `AI4Math/MathVista` `2b6ad694`, inspect_evals' own pin):**
  `--shuffle-seed 20260917` (the eval calls `hf_dataset(shuffle=True)` with no seed; the
  documented seed, as for race_h and uccb). 1,000 Cases, Case Digest `1f45337d…`, 254 s and
  2.38 GB peak on the laptop; the first attempt died on a Hugging Face CDN download error and
  the retry passed. The build path's replay (`prepare_replayed_cases`) reproduced the digest,
  194 s. Published revision `cc2aeecb949b920a` from `benchmark_bump.py`.
- **Size check:** one picture per Case (cap 20); largest Case 735,304 bytes (pid 902), median
  36,829, none over the importer's 8 MB nor the frozen copy's 2,000,000-byte entry cap.
  `cases.json` 87.3 MB, read and parsed at 551 MB resident (budget 2,560 MiB). Pictures:
  805 PNG, 189 JPEG, 6 WebP.
- **Byte check (outside judge):** inspect's own `eval()` with the free `mockllm/model` on all
  1,000 Samples: each one's sent message (picture, then text, picture bytes and media type)
  matched exactly one Case, and its target, choices and metadata equal that Case's Grading
  Material (540 multiple choice, 418 integer, 40 float, 2 list). Negative control: one flipped
  byte in the largest Case's picture left exactly that Sample unmatched.
- **Licence counts checked against the Cases' own `source` metadata:** TabMWP 62, IconQA 62,
  ScienceQA 9, DVQA 62 (195 NonCommercial); ChartQA 50 (GPL-3.0); FigureQA 62, KVQA 60,
  DocVQA 12 (134 unknown); 31 sources in all.
- **Gates:** 30 cross-row test files with the inspect extra, 1,901 passed; the 4 failures in
  `test_benchmark_display_metadata.py` / `test_benchmark_protocol.py` are pre-existing (the
  unlisted wmdp rows, OME-1714) and those two files pass extra-less (27 passed), as CI runs
  them. The new test passes, and both its tests fail on the mutant `keep_sample_metadata=False`.
  ruff, ruff format, pyright with and without the extra clean on the 9 touched Python files.
- **Deviations:** none from the plan's design. Tier `medium`, not `easy`: the best
  lab-published score is 0.903 (Qwen3.5-397B-A17B, its own model card), at the "~90%+" edge of
  "easy", but the same cards put GPT-5.2 at 0.83 and Claude Opus 4.5 at 0.80, so there is still
  headroom across the field; MMMU (0.842) and FigQA (0.889) are `medium` too. Owner to confirm.
  This branch is off main, not stacked on MMMU (#1589): both edit the same five tables and
  the row counts (87→88), so whichever merges second needs its counts moved to 89 / 72.
- **Owner-verify:** confirm the tier. The paid and state-of-the-art runs are OME-1673.
