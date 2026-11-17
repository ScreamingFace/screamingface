---
ticket: unfiled   # Linear skipped by the user's decision (2026-11-16): no issue, no epic, no `Refs: OME-N`
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-16
finished:
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
- `packages/screamingface`: the example notebook `21_futurex_past`.
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
  study's FutureX scores exactly.
- Every gate is green except the append-only check on the shared tables, which needs an `OME-N`
  approval (spec §9).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, with these differences:
  - The level-1/2 label rules and the reply reader live in `grading.py`, beside the level-3/4
    rules, instead of `futurex_past.py`. This avoids an import cycle.
  - `pyproject.toml`: the new `vendor/` joins the ruff, pyright and coverage exclusions that
    every other vendored scorer has.
  - The fixture generator is committed as
    `tests/fixtures/futurex_past_study/make_replication_fixture.py` instead of living in `.docs/`.
    Rerun against the study package, it reproduces `replication.json` byte for byte.
  - A seventh shared table gains the two keys: `test_whole_run_metric.py`. It is the list of rows
    whose non-mean headline is an owner decision.
- **Commits:** see `git log futurex-past-local-task` (no OME id: Linear skipped).
- **Gates:**
  - `screamingface-engine`: the append-only check is red, as expected, on exactly the seven
    shared table files (spec §9; they need an `OME-N` approval manifest). Every other gate, run by
    hand, is green: ruff check, ruff format, pyright (extra-less, as CI runs it), layering, and
    pytest with 9,357 passed and 96.35% coverage (floor 80).
  - The inspect lane (`uv run --extra inspect pytest tests/unit/inspect`): 3,201 passed.
  - The `screamingface` and `repo` stacks: all gates green.
- **Deviations:**
  - Spec §4.2 said the router sees only lists. It now routes **every** level-3/4 question, as
    upstream's `route_metric` does.
  - Spec §6 said `withhold`. Both rows use `coverage_declare`, because the Engine refuses
    `withhold` with a whole-run metric (OME-1642). It also matches the study's NO_RESPONSE rule
    and the paper's §3.4.2.
  - A number in prose goes to the judge whole. Upstream judges the first comma piece of its
    LLM-extracted answer.
