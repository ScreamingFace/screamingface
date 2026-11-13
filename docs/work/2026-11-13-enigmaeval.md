---
ticket: OME-1874
stack: screamingface-engine
status: done
started: 2026-11-13
finished: 2026-11-13
---

# enigmaeval — EnigmaEval puzzle-hunt puzzles as a local Task, one Benchmark

## Intent

[EnigmaEval](https://arxiv.org/abs/2502.08859) (CAIS and Scale AI) is 1,161 puzzle-hunt
puzzles, most with pictures, each answered by a word or short phrase and graded by exact match.
No inspect Task exists; the reference grader is the authors' plain-Python harness in
[centerforaisafety/simple-evals](https://github.com/centerforaisafety/simple-evals/tree/6614edf59833140fb77e61758bbb2674b54a445e/enigmaeval)
on branch `dev` at `6614edf5`. This unit writes it as a **local Task** in inspect's shape and
imports it as one Benchmark, `enigmaeval`, whose Candidate gets the authors' system and user
prompts and whose reply is graded by the authors' own answer reader and normaliser. One Attempt
per Case, no judge.

Data: Hugging Face [`cais/EnigmaEval`](https://huggingface.co/datasets/cais/EnigmaEval) v2 at
`9ed38dabb105ad900ef850a937014d8653ae9f94`, split `test`, 1,161 rows (gated, automatic).

Owner decisions this unit follows (dispatch of 2026-11-13, then the rulings on the measurement):

- one Benchmark for all puzzles; the card names the 232 hard ones (MIT Mystery Hunt 68, Labor
  Day Extravaganza 154, GMPuzzles 10) so a split stays possible;
- licence: ship all; the card names each source's terms and says the non-commercial puzzles
  come out if ScreamingFace goes commercial; the canary stays on the card and the Cases;
- pictures: the authors' loader exactly, every picture re-saved as PNG by Pillow, palette and
  other modes to RGB. Not a deviation. The PNG re-save is a format change only, so GMPuzzles'
  no-derivatives terms hold. Pillow's bytes are platform-bound, so the Case Digest is sealed on
  linux/amd64 inside the Engine image (the MMMU, MathVista and ZeroBench recipe);
- Ring Toss (1 puzzle, no licence named): shipped, "licence not stated, served for evaluation
  use only";
- the image sentence follows the authors' code (`[image_1]` in the text), not the card;
- the system prompt reaching the Candidate as the first text of its user turn is a declared
  deviation (an Engine limitation).

## Measurement (before sealing)

Raw parquet at the pinned commit, sha256 `00e89624…3392`, 345,273,199 bytes. 1,336 pictures:
1,329 PNG, 5 GIF, 2 JPEG; modes RGBA 1,288, RGB 43, P 5. At most 20 pictures in one puzzle
(row 228), the cap. Three puzzles are over the 8,000,000-byte Case cap with their pictures
inline, and the authors' PNG re-save does not bring them under:

| row | task_id | source | pictures | stored bytes | after the authors' re-save |
|---|---|---|---|---|---|
| 257 | `69f3aee766ce8458f2f20eb8` | Puzzle Potluck | 1 | 8,879,854 | 7,265,308 |
| 258 | `69f3aee766ce8458f2f20eb0` | Puzzle Potluck | 1 | 10,324,507 | 8,994,741 |
| 283 | `69f3aee766ce8458f2f20fa8` | PuzzledPint | 7 | 19,760,759 | 15,277,751 |

## Open owner question

- **The three Cases over the 8 MB cap** (rows 257, 258, 283 above): the team decides drop vs
  other. Built PROVISIONALLY with the three held out by task_id in one named constant beside
  the prepare row, so the call flips in one place; 1,158 Cases sealed. This is not a decision.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/enigmaeval/`
  - `__init__.py`, `README.md` (the card);
  - `enigmaeval.py` — loader at the pinned revision, the authors' prompt builder restated (its
    f-strings carry a trailing space the repo's whitespace hook would strip from a copy),
    `record_to_sample`, the exact-match scorer, the `@task`;
  - `vendor/simple_evals.py` — the authors' answer reader, normaliser, answer-type and picture
    re-save functions and the two tips files, verbatim below our header (whitespace-only lines
    emptied, the hook again), MIT.
- `apps/screamingface-engine/pyproject.toml` — the vendor dir joins the ruff, pyright and
  coverage fences.
- `prepare.py` — `TaskReplayCasesSpec` row + the held-out constant; `benchmarks.py` —
  `BenchmarkSpec` row.
- Row tables: `test_benchmark_declaration.py`, `test_failure_policy_rows.py`,
  `test_inspect_imported_benchmarks.py`, `test_published_revisions.py`,
  `test_benchmark_fingerprints.py`; `.claude/test-change-approvals/OME-1874.json`.
- New test `tests/unit/inspect/test_local_task_enigmaeval.py`.
- Mirror `docs/tasks/2026-11-13-OME-1874-enigmaeval.md`.

## Test plan

- RED first: the new test file, failing on import until the Task module exists.
- Prompt: for a real normal row and a real MIT Mystery Hunt row, the system and user text the
  Task builds hash to the authors' `PromptMaker` output, computed once from the authors' code at
  the pinned commit.
- Normaliser: the copied reader/normaliser grade set answers, `|` alternatives and replies with
  no tags as the authors' code does; vendored code hashes to the authors' functions.
- Loader: held-out ids missing → refused; wrong row count → refused.
- Outside judge: the authors' own `fetch_puzzles` + `grade_puzzles` message builder run over all
  1,161 rows in scratch; every kept Case's text and picture bytes equal the authors' message.
- Row tables, then ruff + pyright (extra-less, as CI) on the touched files.

## Acceptance

- `enigmaeval` registered, 1,158 Cases, Case Digest sealed on linux/amd64, `needs_hf_token`,
  no TODO left, one Attempt, no judge.
- The named test files pass; ruff and pyright clean on the touched files.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. New: `local_tasks/enigmaeval/` (`__init__.py`, `enigmaeval.py`,
  `README.md`, `vendor/__init__.py`, `vendor/simple_evals.py`, `vendor/LICENSE`),
  `tests/unit/inspect/test_local_task_enigmaeval.py`,
  `.claude/test-change-approvals/OME-1874.json`, the mirror. Changed: `pyproject.toml` (the
  vendor dir in the ruff, pyright and coverage fences), `prepare.py` (the held-out constant and
  the row), `benchmarks.py` (the row), the five row tables. No `STAND_IN_METADATA` entry: the
  scorer reads no metadata. No notebook change: the row uses `12_inspect_evals_benchmarks`, as
  the LABBench2 rows did at first.
- **Commits:** one, `feat(screamingface-engine): add EnigmaEval puzzle-hunt Benchmark as a local
  Task (OME-1874)`.
- **Import, sealed on linux/amd64** (the Engine Dockerfile's builder stage built with
  `--platform linux/amd64` plus a `uv sync --frozen --no-dev --extra benchmarks` layer; OrbStack,
  Rosetta; the worktree's `src/` mounted read-only; written to scratch copies of the two files
  and merged by hand): `python -m screamingface_engine_inspect.importer
  screamingface_engine_inspect.local_tasks.enigmaeval.enigmaeval:enigmaeval --key enigmaeval
  --excluded-sample-id …` ×3, 3 min 16 s. 1,158 Cases (1,161 yielded, 3 excluded), Case Digest
  `2534208d6af2d6c7544bff23a086dd4624080242a77606deff20f08ccc413418`, case-set digest
  `58b8cd38…`. The same import on the Mac gave `dc765b66…` (Pillow's PNG bytes differ by
  platform), so the Mac seal was discarded. The build path in the same image
  (`python -m screamingface_engine.benchmarks.prepare --bundle enigmaeval`) reproduced 1,158
  Cases and `2534208d…` in 95 s. Published revision `863b8c98762520a2` from
  `benchmark_bump.py` (new Benchmark: published id = fingerprint on the day).
- **Outside judge, inside the Linux image:** the authors' own `fetch_puzzles` (forced to the
  pinned revision) and `PromptMaker`, with `grade_puzzles`' message builder, over all 1,161
  rows: every one of the 1,158 Cases matched its puzzle exactly (system text, user text, every
  picture's data URI byte for byte and in order, target, canary); the 112 text-only Cases are
  the system and user text joined by a blank line; the 3 unserved puzzles are exactly the held-out
  ones. Negative control: one flipped byte in the largest Case's first picture left exactly that
  Case unmatched.
- **Sizes (Linux bundle):** 1,327 pictures, all PNG, at most 20 per Case; largest Case 5,811,802
  bytes (limit 8,000,000); largest picture 4,842,304 bytes as base64 (under Anthropic's 5 MB).
  `cases.json` 400,215,759 bytes; reading and parsing all of it in a fresh process peaks at
  2,310 MiB resident, close to the 2,560 MiB per-run budget. A run reads only the selected
  Cases since OME-1790 (`cases.offsets`), so this is an upper bound, but it is the tightest of
  any Benchmark so far.
- **Prompt facts:** no row lacks a question, so the authors' PDF prompt never runs; no MIT
  Mystery Hunt row has previous answers; 69 gold answers carry a comma, 5 a `|`.
- **Gates** (`.venv` with the inspect extra, then `uv run --isolated` for the extra-less lane):
  `test_local_task_enigmaeval.py` 36 passed; with the five row tables 831 passed; the
  row-sweeping files that assemble or grade every row (`test_inspect_task_replay_benchmarks.py`,
  `test_imported_catalogue_activity.py`, `test_benchmark_provenance_conformance.py`,
  `test_published_revision.py`, `test_fidelity_check_catalogue.py`, `test_unlisted_rows.py`,
  `test_failure_policy_revisions.py`, `test_function_scorer_arguments.py`,
  `test_benchmark_provenance_assembly.py`, `test_imported_case_selection_run.py`,
  `test_retrieval_policy_on_row.py`, `test_judge_reads_the_sample_input.py`,
  `test_whole_run_metric.py`) 741 passed; extra-less, the new file and the five tables, 15
  passed, 8 skipped. The new test fails on two mutants (the system prompt's trailing space
  dropped: 6 failed; the MIT dispatch inverted: 7 failed). ruff check, ruff format and pyright
  (extra-less, as CI) clean on every touched Python file outside `vendor/`.
- **Deviations from the plan:** the prompt builder is restated rather than copied (the trailing
  space); the vendored functions are copied with whitespace-only lines emptied, pinned by a
  strip-then-hash test. The licence note is under the 255-character limit, so the per-source
  counts and the format-change sentence also live in the row comments, the description and the
  card. The frontier score is `NotPublished`: the paper's numbers are on the first release, and
  dashboard.safe.ai showed no EnigmaEval score when read.
- **Declared deviations on the row:** the system prompt arrives as the first text of the user
  turn; only the reply's text is read (no fallback to reasoning text); three puzzles held out,
  provisionally.
- **Owner-verify:** the three over-cap puzzles (open question above; flip in
  `ENIGMAEVAL_HELD_OUT_OVER_CASE_CAP`, then re-seal on linux/amd64, which moves the Case Digest and
  the fingerprint); push, PR body and the Linear link both ways; CI's "Build the deployable
  images" as the deployment proof of the Linux seal; the paid smoke (two Cases of `enigmaeval`,
  one with pictures and one text-only); the 2,310 MiB full-read peak against the run budget; the
  tier (`hard`) and the frontier score against the live dashboard; a Fidelity Record (OME-1471
  agent).
