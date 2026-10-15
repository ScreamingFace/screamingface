---
ticket: OME-1481
stack: screamingface-engine
status: done
started: 2026-10-15
finished: 2026-10-15
---

# OME-1481-pr1-frames-task — FRAMES (articles given) as a local inspect Task, judged by the paper's prompt

## Intent

Serve FRAMES in the paper's "Oracle" setting: every question's gold Wikipedia articles,
frozen in the published snapshot (`khoaguin/frames-wikipedia-2024-09-19` at `6ada7fb7`), are
pasted into the prompt, and the house Judge grades each reply with the paper's Figure 6
auto-rater prompt, TRUE scoring 1.0 and FALSE 0.0. One local Task file in inspect's shape
(the MuSiQue recipe) with a judged scorer (the DRACO recipe), fed to the same importer.
Decisions 1 to 10 on OME-1481.

## Planned changes

- `src/screamingface_engine_inspect/local_tasks/frames/{__init__.py,frames.py,README.md}` —
  new: the loader (questions file and snapshot at pinned commits, each sha256-checked, joined
  by row index and checked by prompt sha256), the Candidate prompt (articles then the
  question, one user message), the Figure 6 judge prompt and its decision reader, the judged
  scorer through `judge_until_parsed`, the `frames_oracle` Task.
- `src/screamingface_engine_inspect/prepare.py` — the importer-generated `frames_oracle`
  Task-replay row; questions 77 and 141 excluded as a named deviation (decisions 9, 10).
- `src/screamingface_engine_inspect/benchmarks.py` — the importer-generated `frames_oracle`
  row, completed by hand: the judge pinned (`JudgeSpec`, house judge), provenance, licence,
  Frontier Score 0.729, no Draft Feedback.
- `tests/unit/inspect/test_local_task_frames.py` — new.
- Table rows in the shared catalogue tests that list every Benchmark (declaration, family,
  published revision), approved in `.claude/test-change-approvals/OME-1481.json` if needed.
- `docs/tasks/2026-10-05-OME-1481-frames-articles-given.md` — mirror;
  `docs/work/2026-10-12-OME-1481-frames-snapshot.md` — the snapshot's ledger (its builder PR
  was closed unmerged; the builder lives beside the data on Hugging Face).

## Test plan

- Candidate prompt bytes: a row renders to a pinned literal (articles in link order, then
  the question), and the gold answer is not in it.
- Judge prompt bytes: Figure 6 transcribed from the paper's LaTeX source, pinned as a
  literal; the judge sees the question, never the articles.
- Decision reader: `Decision: TRUE` / `FALSE` in the shapes judges write them (quoted, bold,
  lower case), the last decision wins, no decision → None (redrawn).
- Through the real grading hook with a scripted judge: TRUE → 1.0, FALSE → 0.0, no decision
  on three draws → `judge_reply_invalid`; the judge's route, pinned params and messages.
- A Candidate 400 on one of three Cases fails that Case (`aigateway_http_400`), coverage
  reads 2 of 3, and the run completes (decision 4).
- Loader joins: a questions file and snapshot whose prompt sha256 disagree are refused; an
  article key missing from the snapshot is refused.
- The rows: id `frames_oracle`, origin `screamingface`, no provenance gaps, the judge pinned,
  822 Cases, 77 and 141 excluded.

## Acceptance

- `frames_oracle` registers from the local Task; Case Preparation matches the Case Digest
  with 822 Cases; tests above green in the inspect lane; ruff and pyright clean on touched
  files.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `.claude/test-change-approvals/OME-1481.json` (the three
  table rows, one per catalogue test, awaiting the owner's OK on the PR). No
  `STAND_IN_METADATA` row was needed: the stand-in lanes pass without one.
- **Import:** `importer …frames.frames:frames_oracle --key frames_oracle
  --keep-sample-metadata --excluded-sample-id 77 --excluded-sample-id 141`
  (`HF_HUB_DISABLE_XET=1`, `benchmarks` extra): 824 Samples yielded, 2 excluded, 822 Cases,
  Case Digest `5ac0520b…`; three Case Sources recorded, each pinned by revision
  (`google/frames-benchmark` @ `58d9fb63`, the snapshot's two files @ `6ada7fb7`). Every
  TODO resolved by hand from the paper: title, description, focus, tier `medium` (owner to
  confirm after the first paid run), paper, authors and BibTeX from the arXiv source, harness
  = the questions repo at its pin (the paper links no code), licence Apache-2.0 with the
  articles' CC BY-SA 4.0 in the note, human baseline NotPublished, Frontier Score 0.729
  (Gemini-Pro-1.5-0514, Table 3). The importer did not detect the judge (its model is the
  scorer's default), so `scorer_kwargs` and the `JudgeSpec` were added by hand, as for draco.
- **Prepare:** `screamingface_engine.benchmarks.prepare --bundle frames_oracle` reproduces
  822 Cases and the same Case Digest in 22 s; `cases.json` is 74 MB; prompts run median
  78,022 and at most 728,489 characters. Case 1 (FRAMES row 0) reads articles then question,
  and its gold answer is not in its input; FRAMES row 540 has 19 articles and names the
  missing one in its Grading Material.
- **Judge prompt:** transcribed from the paper's LaTeX source (`auto_rate_prompt.tex`, arXiv
  2409.12941v1), not the PDF: each forced line break in the source is a newline, and the
  curly apostrophe and en dash are kept.
- **Revision:** `eb27d52bf8431b07`, pinned in `test_published_revisions.py`.
- **Commits:** see the PR.
- **Gates:** `test_local_task_frames.py` (20), plus the catalogue tests that list every
  Benchmark (`test_published_revisions`, `test_benchmark_declaration`,
  `test_inspect_imported_benchmarks`, `test_imported_catalogue_activity`,
  `test_inspect_task_replay_benchmarks`, `test_case_source_links`,
  `test_benchmark_provenance_conformance`, `test_benchmark_provenance`): all green. Ruff and
  format clean; pyright clean on touched files with the inspect extra and without it. The
  append-only check, run alone, passes with the approval file. Full suite left to the pre-push
  hook and CI.
- **Deviations:** (1) Questions 77 and 141 are left out through the row's
  `excluded_sample_ids` (a declared named deviation that Case Preparation re-checks), not by
  the loader. (2) The ticket called FRAMES "the first local Task with a Judge"; DRACO landed
  first (#1395), so FRAMES reuses its judge path and nothing in it is new. (3) The
  over-window test drives the aggregate with the connector's real 400 error row rather than a
  whole run.
