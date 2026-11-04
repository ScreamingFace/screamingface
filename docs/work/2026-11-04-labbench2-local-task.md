---
ticket: OME-1733
stack: screamingface-engine
status: done
started: 2026-11-04
finished: 2026-11-04
---

# labbench2-local-task — LABBench2 FigQA2 and TableQA2 image mode as a local Task (PR 1 of 2)

## Intent

LABBench2 ([arXiv 2604.09554](https://arxiv.org/abs/2604.09554)) is the successor to LAB-Bench.
Its two picture subsets, FigQA2 image (101 questions) and TableQA2 image (100), are unsaturated
and single-shot: one figure or table picture plus a question, a free-text answer graded by an
LLM judge against an ideal answer. inspect_evals lists LABBench2 only as an external eval, so
nothing in the pinned `inspect-evals==0.20.0` knows it. This unit writes it as a **local Task**
in inspect's shape, so PR 2 can import the two Benchmarks with the existing importer.

Owner decisions this unit follows (2026-10-28 on OME-1733, and 2026-11-04):

- image variants only; licence CC BY-SA 4.0 on LAB-Bench v1 terms, figures' terms unknown;
- dataset `EdisonScientific/labbench2` at `3678e7e38748477d0606407468db9cd7e2f2e667`;
- judge `openrouter/anthropic/claude-sonnet-4.5`, the authors' and the inspect port's default,
  temperature 0 pinned in the row;
- "unsure" scores 0, the authors' rule; a reply with no verdict is redrawn, then the Case
  counts 0 (the authors' evaluator scores any judge failure 0.0).

Reference harness: the authors' [EdisonScientific/labbench2](https://github.com/EdisonScientific/labbench2)
at `0cabab27f6a23a5bc060a4699205709f1be7e93f`. It carries two changes the inspect port
([Generality-Labs/lab-bench](https://github.com/Generality-Labs/lab-bench/tree/081864af494b180ecf6aae3f7333e384c0d227af/src/lab_bench_2)
at `081864a`) predates: the exact-match prompt's non-numeric rule (2026-10-07) and the
"Attached files" file-mode instruction (2026-10-15).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/lab_bench_2/`
  - `__init__.py` — package docstring.
  - `lab_bench_2.py` — loader (`load_rows`), `record_to_sample`, the judge scorer
    `lab_bench_2_exact_match`, `parse_verdict`, two `@task`s.
  - `figures.py` — list one question's files in the public GCS bucket and download them under
    the replay cache, md5-checked against the listing, atomic, bounded retries.
  - `vendor/labbench2.py` — the authors' exact-match judge prompt and file-mode instruction,
    byte for byte, CC BY-SA 4.0 header linking the pinned commit.
  - `vendor/lab_bench_port.py` — the inspect port's verdict regex and last-match rule, MIT
    header linking the pinned commit.
  - `README.md` — the Benchmark's dataset, prompt, scoring, deviations, licence, identity.
- `apps/screamingface-engine/tests/unit/inspect/test_local_task_lab_bench_2.py` — new.
- ledger (this file) and mirror `docs/tasks/2026-11-04-OME-1733-labbench2-image-benchmarks.md`.

PR 2 (separate branch, stacked): the importer run (two TaskReplayCasesSpec + two BenchmarkSpec
rows), the row tables in the inspect tests, the picture notebook rows.

## Test plan

New file only; no prior test changes.

- Candidate prompt: a row renders one user message, the question then the authors' "Attached
  files" lines, then the picture as a file under the cache; a `prompt_suffix` is appended after
  a blank line.
- Rows: a row with no question, no ideal, no files prefix, or `mode.file` false fails the build
  by name; a dataset of the wrong size fails the build.
- Figures: a fake bucket (local HTTP server) serves the listing and the bytes; the download lands
  under `INSPECT_EVALS_CACHE_DIR/lab_bench_2/…`; a md5 mismatch fails; a listing with no file
  fails; a blob name escaping the prefix (`..`) is refused; a cached good file is not fetched
  again.
- Judge prompt: the vendored text equals the authors' prompt at the pinned commit (sha256 pin).
- Verdict: last `result:` line wins; JSON `"result": "correct"` reads; `result = "correct"`
  (code) is no verdict; unsure is a verdict scoring 0.
- Scorer, with a scripted judge: correct → 1.0, incorrect → 0.0, unsure → 0.0, an unparseable
  reply redrawn then a verdict, three unparseable replies → `JudgeReplyUnparseable`; an empty
  answer scores 0 without calling the judge; the judge sees the question text exactly as the
  Candidate saw it, the ideal answer, and the answer unstripped.

## Acceptance

- `test_local_task_lab_bench_2.py` green; ruff, ruff format, pyright clean on touched files,
  including extra-less pyright.
- A real build of both Tasks, run once by hand: 101 and 100 Samples, every picture inside the
  replay cache, each one PNG.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `apps/screamingface-engine/pyproject.toml` (the new
  `vendor/` folder joins the ruff and pyright exclusions, as ifeval's, musique's and
  arc_agi_2's vendored code does) and `vendor/__init__.py`.
- **Commits:** see the PR; one commit on `OME-1733-pr1-labbench2-local-task`.
- **Gates:** `tests/unit/inspect/test_local_task_lab_bench_2.py` 32 passed (with the inspect
  extra) and 1 skipped (extra-less, as CI); ruff check, ruff format and pyright clean on the
  package and the test, pyright also extra-less. Real build, run by hand with `HF_TOKEN`
  against the gated dataset and the public bucket: FigQA2 image 101 Samples, TableQA2 image
  100, Case ids 1..N, 0 pictures outside the replay cache, every Case sealed by
  `picture_case_text` as one text part then one picture, largest Case 5.53 MB (FigQA2) and
  1.99 MB (TableQA2); downloads took 220 s and 155 s.
- **Deviations:**
  - Code and tests were written in one pass, then run, not test-first.
  - The figures are fetched with our own urllib and md5-checked, not through
    `inspect_ai.util.download`: that would need 201 sha256 pins in the source. The Case Digest
    pins the bytes, the GDPval precedent.
  - Reference harness is the authors' current `0cabab27`, not the inspect port's older copy;
    named in the README.
- **Owner verify (PR 2):** the importer run that writes the two rows needs `HF_TOKEN` and
  downloads about 115 MB per replay (two replays); the paid smoke run follows the rows.
