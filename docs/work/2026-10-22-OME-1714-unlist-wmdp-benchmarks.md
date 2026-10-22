---
ticket: OME-1714
stack: screamingface-engine (+ packages/screamingface notebook prose)
status: done
started: 2026-10-22
finished: 2026-10-22
---

# OME-1714 — unlist the WMDP Benchmarks from the public catalogue

## Intent

Product (OME-1714) wants WMDP-Bio, WMDP-Chem and WMDP-Cyber off the public Leaderboard catalogue:
listed, they read as an invitation to optimise Fusions for hazardous-knowledge elicitation. The
owner chose to unlist rather than delete (2026-10-22): the Benchmarks stay installed and runnable
by id, and disappear from every listing (SDK `sf.benchmarks.list()`, Scoreboard seed).

Spec: `docs/spec/2026-10-22-OME-1714-unlist-wmdp-benchmarks.md`.
Plan: `docs/plan/2026-10-22-OME-1714-unlist-wmdp-benchmarks.md`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/definition.py` — `unlisted` mark
- `apps/screamingface-engine/src/screamingface_engine/rest/benchmarks.py` — list skips it
- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py` — spec field + 3 rows
- `apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py` — thread it through
- `apps/screamingface-engine/tests/unit/test_benchmark_unlisted.py` — new
- `apps/screamingface-engine/tests/unit/inspect/test_unlisted_rows.py` — new
- `packages/screamingface/scripts/build_notebooks.py` + `examples/12_inspect_evals_benchmarks.ipynb`
- `CONTEXT.md` — Unlisted Benchmark

## Test plan

- Default: a Benchmark is listed; no `unlisted` key on the catalogue entry or resource.
- `GET /v1/benchmarks` omits an Unlisted Benchmark and serves the listed one unchanged.
- `GET /v1/benchmarks/{id}` still answers 200 for an Unlisted Benchmark.
- The Unlisted spec rows are exactly `wmdp_bio`, `wmdp_chem`, `wmdp_cyber`.
- The assembled WMDP-Bio Benchmark is unlisted; gsm8k is not (inspect extra).
- The three published revisions are unchanged (existing pin).

## Acceptance

- Spec §4, items 1–5.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `docs/spec/`, `docs/plan/` and this ledger; no file beyond
  the plan.
- **Commits:** `6b28556fe` feat(screamingface-engine): take the WMDP Benchmarks off the public
  catalogue as Unlisted · docs commit (this one).
- **Gates:** extra-less venv — `tests/unit/test_benchmark_unlisted.py`,
  `tests/unit/inspect/test_unlisted_rows.py`, `test_benchmark_origin.py`,
  `test_benchmark_display_metadata.py`, `inspect/test_failure_policy_rows.py`: 32 passed, 5
  skipped; ruff check + format + pyright on the six touched files: clean. Inspect venv —
  `test_unlisted_rows.py`, `test_published_revisions.py`, `test_failure_policy_revisions.py`,
  `test_inspect_imported_benchmarks.py`, `test_benchmark_declaration.py`: 670 passed (the three
  published revisions unchanged). SDK — `check_notebooks.py` passes; the notebook diff is the one
  prose line. The pre-push hook runs the Engine suite.
- **Deviations:** none. The ticket title says "remove"; the owner chose unlist over delete
  (2026-10-22), recorded in the spec.
- **Owner-verify:** after the Engine deploy, the platform operator removes the three Scoreboard
  rows on prod and dev with `python -m scoreboard.retire_benchmark --benchmark <id>
  --include-engine-owned --yes` (0 Scores, 0 baselines on each, measured 2026-10-22).
