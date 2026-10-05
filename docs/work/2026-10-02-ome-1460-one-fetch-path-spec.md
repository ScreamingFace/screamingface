---
ticket: OME-1460
stack: repo
status: done
started: 2026-10-02
finished: 2026-10-02
---

# ome-1460-one-fetch-path-spec — the spec and plan for one Case Preparation path

## Intent

OME-1460 folds the Hugging Face path into Task replay: every Imported Benchmark is prepared
by calling the eval's own task function, the recorder forces each Hub fetch to the revision
the declaration pins, and the 28 Hugging Face-path rows get a new Benchmark Revision under
their existing keys. The ticket is already spec-grade; this unit writes it down as the
reviewable `docs/spec/` artifact, checks every claim against `main` and the installed
inspect packages, and writes the `docs/plan/` artifact that fixes the two PRs, their
RED-first tests and the owner presses. Docs only; the code is the follow-up PR stack the
plan defines (spec before plan before code).

## Planned changes

- `docs/spec/2026-10-02-ome-1460-one-fetch-path.md` (new).
- `docs/plan/2026-10-02-OME-1460-one-fetch-path.md` (new).
- `docs/tasks/2026-10-02-OME-1460-one-fetch-path.md` (new mirror; the ticket stays in
  progress, this PR does not close it).
- `docs/work/2026-10-02-ome-1460-one-fetch-path-spec.md` (this ledger).

## Test plan

- No code. Every claim the spec makes is checked by reading `main` `ec11a0608`, the
  installed `inspect-ai` 0.3.263 / `inspect-evals` 0.20.0 / `datasets` 5.0.0, and the
  Linear ticket; each check is listed in the Outcome. The three mermaid diagrams are
  rendered with `mmdc` and read before commit. Repo gates: `run_gates.py repo`.

## Acceptance

- The spec carries R-numbered requirements, a Runs / Taken / Never-runs line, the failure
  modes F1 to F5 from the ticket, the ticket's five acceptance items plus the ones the
  reading forced, Known limitations and Open questions.
- The plan carries D-numbered decisions, a task 0 refusal sweep before any code, the
  two PRs as tasks with RED-first tests and files, a review-focus list, the step-7
  sequencing dependency and every owner press.
- The owner reviews the spec before any plan task starts.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** `5832a20b9` docs(screamingface-engine): spec and plan for one Case Preparation path; plus the ledger-close commit.
- **Gates:** `run_gates.py repo` ALL GATES GREEN (append-only, run_gates tests, mirror-status tests, pre-push tests, loop parity, mirror status). The three mermaid diagrams rendered with `mmdc` 11.14.0 and read: stacked lanes, strictly downward flow, no overlaps. Every symbol the spec names was printed from `main` `ec11a0608` (`BENCHMARK_CASES` 28 rows; `_revision_pins`, `_task_replay_pins`, `_cases_declaration`; `CaseSourceRecorder.install`, `PRIMITIVES`; `replay_environment`, `prepare_replayed_cases`; `captured_case_records`; `read_inspect_task` and its four `TaskReplayRoute` sites; `test_published_revisions.py` 18 literals; `test_inverted_grade.py:82`), the 19 task files at inspect_evals 0.20.0 (every `*_DATASET_REVISION` equals our pin; `shuffle`/`seed`/`shuffle_choices`/`system_message`/`.filter` per task), inspect_ai 0.3.263 `hf.py:122-221` (`revision` forwarded to `load_dataset`; cache bypassed when `revision` is set), the CI image job's strict and token flags, and the paid inspect smoke lane. Owner-verify: approve the spec before any plan task starts; the open questions and D1–D8 need an answer before PR A / PR B.
- **Deviations:** the facts the reading contradicted, each carried into the spec:
  - the ticket's "27 Benchmarks" are 28 rows of `BENCHMARK_CASES` (xstest's two rows
    counted once); the spec and acceptance count rows, 28;
  - the ticket's "17 frozen literals" are 18 in `test_published_revisions.py` plus one in
    `test_inverted_grade.py` (gsm8k's again): 19 literal sites move, none stays; the 10
    rows imported since 2026-09-24 are not frozen (open question kept);
  - "the recorder adds `revision=` to a call that has none" bites none of the 28: every
    one of the 19 evals behind them already passes a 40-hex sha equal to our pin
    (inspect_evals 0.20.0); on the fold the mechanism VERIFIES (F2) rather than adds, and
    F1 bites the Task-replay rows that fetch from the Hub with no pin (medqa, bbq, piqa);
  - "inspect's seeded order replaces ours" holds for one row (mmlu, `seed=42` upstream);
    14 rows shuffle unseeded upstream (and lab_bench's six task functions take no
    argument at all), so the double run would refuse them; the spec forces the
    declaration's seed through inspect's own shuffle (D1);
  - "text identical" is false for musr and xstest, whose system messages today's rows do
    not bake and capture renders (D3), and for gsm8k and winogrande unless their few-shot
    task arg is pinned to 0 (D2);
  - onet_m6's six excluded ids and xstest's gated fetch have no Task-replay home today;
    the spec adds both to the declaration (R6, R8, R9);
  - the ifeval e2e golden is a hand-built Engine Benchmark (`benchmarks/ifeval/`), not an
    Imported Benchmark: no golden re-record; the paid press that touches inspect bundles is
    the paid inspect smoke lane, recorded as a recommended re-press;
  - `packages/screamingface/tests/public_surface_snapshot.json` is the SDK's API photograph
    and carries no revision: it does not change; the `--skip-append-only` ask covers the two
    revision-literal tests and the deleted Hugging Face-path tests;
  - the ticket's three PRs are two (the owner collapsed the fold halves and the deletion
    into one PR on 2026-10-05, review of PR #1223: the concept is one and the fold is
    mechanical; D5 records the waiver of the 500-line cap) and the image-side child is CHANGED, not unchanged (it must apply the same forced
    pins, or F3 fails at build).
