---
ticket: OME-1952   # filed by the ScreamingFace maintainer on review (2026-11-17); Linear otherwise skipped
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-11-16
finished: 2026-11-16
---

# futurex-past-local-task — serve FutureX-Past as a local inspect Task

## Intent

[FutureX-Past](https://huggingface.co/datasets/futurex-ai/Futurex-Past) is the resolved-question
archive of the FutureX live forecasting benchmark (Zeng et al., arXiv 2508.11987; Apache-2.0).
It is not among the Engine's hosted Benchmarks, so ScreamingFace fusions of forecasting committees
cannot be scored on it. This unit adds it as a local inspect Task under
`screamingface_engine_inspect/local_tasks/`, imported with the existing importer, with the
benchmark's own prompt passed through verbatim and the FutureX authors' per-level scoring, plus a second Benchmark, `futurex_past_study`, that scores with the contributor's study rules so the study's published numbers can be replicated.

**Process note:** the Linear steps of the root `CLAUDE.md` SDLC (epic-first, issue at PR-open,
`Refs: OME-N`, branch rename, mirror in `docs/tasks/`) are skipped by the contributor's decision;
the ScreamingFace team said the Linear step may be skipped. `ticket` stays `unfiled`.

## Planned changes

Spec `docs/spec/2026-11-16-futurex-past-local-task.md` and plan
`docs/plan/2026-11-16-futurex-past-local-task.md`, both approved by the contributor on 2026-11-16.

- `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/`:
  `__init__.py`, `futurex_past.py` (loader, reply reader, level-1/2 rules, scorer, tier-weighted
  metric, `@task futurex_past`), `grading.py` (the level-3/4 judge rules), `futurex_past_study.py`
  (`@task futurex_past_study`), `vendor/study_metrics.py` (the study's `metrics.py`, byte for
  byte), and `README.md`.
- `prepare.py` and `benchmarks.py`: two generated and hand-filled rows.
- New tests: `test_local_task_futurex_past.py`, `test_futurex_past_grading.py`,
  `test_local_task_futurex_past_study.py`, `test_futurex_past_study_replication.py`, plus fixtures.
- Shared test tables: stand-in metadata, declaration, family, failure policy, published revision,
  and fingerprint.
- `packages/screamingface`: the example notebook `22_futurex_past`.
- `apps/screamingface-engine/docs/benchmarks-fidelity/futurex_past.md` and
  `futurex_past_study.md`.

## Test plan

- Loader: pins and sha256, verbatim `input`, parsed `target`, `<id>|<end_time>` ids, both schemas,
  and `[Yes]`.
- Reply reader: the last box, nesting, no box, and the comma split.
- Level-1/2 label rules and set F1.
- Level 3–4, against a scripted judge: number, string, ranking, unordered set, the router and its
  fallback, the short-cuts, σ, and an unparseable judge reply.
- Both metrics: tier-weighted, renormalised, and the plain-mean fallback.
- Study: the vendor sha256, the 100 positions, and replication of the stored study scores
  (including fused-medoids 0.302).

## Acceptance

- `futurex_past` registers with 2,036 Cases from `8299bfa1`, judged by the house judge, with a
  tier-weighted headline.
- `futurex_past_study` registers with 1,118 Cases from `3c2e3969`, with no judge. It reproduces the
  study's reported FutureX score for all 27 models and the fused-medoids committee.
- Every gate is green except the append-only check on the shared tables, which needs an `OME-N`
  approval (spec §9).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, with these differences:
  - The level-1/2 label rules and the reply reader live in `grading.py`, beside the level-3/4
    rules, instead of `futurex_past.py`. This avoids an import cycle.
  - `pyproject.toml`: the new `vendor/` joins the ruff, pyright and coverage exclusions that
    every other vendored scorer has.
  - `vendor/study_formats.py`, the study's `bench_formats.py`, is also vendored. It is the
    study's reply reader and interpretability gate (review round, below).
  - Fixtures: `replication.json` (first round) and `replication_all_models.json` (review round),
    both built by the committed `tests/fixtures/futurex_past_study/make_replication_fixture.py`.
  - A seventh shared table gains the two keys: `test_whole_run_metric.py`. It is the list of rows
    whose non-mean headline is an owner decision.
- **Commits:**
  - `c8dadab6c` adds the Benchmarks.
  - `e463be2e9` applies the review and first-audit fixes.
  - The next commit fixes the second audit's two findings.
  - A Fidelity Records commit, then a Codex-review fix. The branch was then rebased onto
    `origin/main` `cc5cfd36d` and re-authored as Yiming Liao <yliao1@umbc.edu>, which changed
    every hash. A last commit refreshes the records from a fourth audit pass at `55d7f087f`.
  - The records: `futurex_past` is `not-comparable`, by design (judge model; closed-book), with
    every deviation declared. `futurex_past_study` is `unverified`: grading is the study's to
    the last bit, and only the declared sampling difference stays open. `just engine
    fidelity-check` reports both as fresh.
  - No OME id: Linear is skipped.
- **Review round** (sf-code-review, and both sf-benchmark-fidelity audits at `c8dadab6c`):
  - `futurex_past`:
    - a whole-box `\text{}` wrapper is now removed at levels 1-2;
    - `{,}` is read as a comma;
    - a number in prose reaches the judge as its first comma piece;
    - option letters reach the rank judge sorted;
    - the router reply is parsed as upstream parses it;
    - a failed router's redraws stay in evidence;
    - a Case without a level beside leveled Cases leaves the headline, instead of switching it to
      the plain mean;
    - the token caps, the router's ask budget, the "yes anywhere" match reading and the
      `\textbf` limit are declared in the README or on the row.
  - `futurex_past_study`:
    - Unusable replies are now marked and left out of the headline. The study dropped a reply with
      no usable answer (no box, or a box its `interpret_answer` rejects) from both sides, through
      `rank.score_entry`. The first version scored such replies 0 and kept them, which moved 21 of
      27 study model scores.
    - A test now reproduces all 27 models and the fused-medoids committee, and every one of the
      study's 38 exclusions.
    - The match is to 1e-12, not bit-exact: Python 3.11 and 3.12 round `statistics.fmean`'s last
      bit differently, and the study's kit gives our values under 3.12.
- **Second audit round** (both auditors, at `e463be2e9`):
  - `futurex_past`, U7: the whole-box unwrap was greedy, so options wrapped one by one were
    misread. The unwrap is now brace-balanced, and each item loses its own wrapper
    (`reply_tokens`).
  - `futurex_past`, U6: an abstained Case whose grading failed leaves the headline. This is now
    declared on the row and in the README.
  - `futurex_past_study`: the README now states the committee-tie difference (a Candidate-side
    difference of at most +0.0071) and the per-Case value of an unusable Case.
  - The study auditor found a `.pyc` in the study package. One of this session's own runs wrote
    it, and it has been removed.
- **Codex review** (OpenAI Codex CLI, read-only, 3 rounds, approved):
  - `to_float` now reads only a whole plain number. `1e3` reads as 1000, and an expression such
    as `1/2` or `10^3` goes to the judge, where before it was half-read as 1 or 10.
  - A malformed number (`e3`) reaches the judge instead of raising.
  - `number_score` returns 0 for a prediction one σ or more away, or a non-finite one, instead of
    overflowing on `1e200`.
- **Study provenance** (from a later copy of the contributor's study package: its `DATASETS.md`,
  Hugging Face download records and selection record):
  - The study downloaded FutureX-Past at `3c2e3969` on 2026-08-08 01:29 UTC, with file sha256
    `55ecf4f1…`. The pin had been inferred from content; it is now confirmed.
  - The README now states how the study chose its 100 questions: a 2026-02-16 training cutoff,
    seeds 20260808 and 20260815, every model answered, no purely numeric key. Only the README
    changed, so the fingerprints do not move.
  - `apps/screamingface-engine/docs/crowd-wisdom-study-datasets.md` answers a maintainer's four
    questions in one place: the dataset commits and download dates, the exact BTF-3 prompt (copied
    byte for byte from the study's as-sent template), yes/no only with no web search, and numeric
    FutureX answers with no `std`.
- **Gates (final head):**
  - `screamingface-engine`: ruff, format, pyright (extra-less, as CI runs it), layering, and
    pytest are green: 9,357 passed, 96.35% coverage. The append-only check against `origin/main`
    is red on exactly the seven shared table files (spec §9; they need an `OME-N` approval
    manifest).
  - The inspect lane (`uv run --extra inspect pytest tests/unit/inspect`): 3,267 passed.
  - The `screamingface` and `repo` stacks: all gates green.
- **Deviations** (spec §11 records them as amendments):
  - Routing covers every level-3/4 question.
  - Both rows use `coverage_declare`, because OME-1642 refuses `withhold` with a whole-run
    metric.
  - The level-3/4 reading rules now match upstream.
  - The study Benchmark drops unusable replies.
  - The published revisions are `futurex_past` = `118a7a5a5df8e185` and `futurex_past_study` =
    `0d516b151df8c19e`, each the fingerprint of the finished code. Earlier drafts had
    `cbe050d3…`/`c3b5c2b7…`, `baf0c231…`/`a006da2f…` and `25b22985…`/`c7f36b93…`. Neither
    Benchmark was ever published.
